"""EU Job Agent — Streamlit dashboard.

Run with:  streamlit run src/job_agent/ui/app.py
(install the UI extra first:  uv pip install -e '.[llm,ui]')

Ties the pipeline together: build a candidate profile (optionally parsed from a CV
via DeepSeek), see a visa-aware ranked shortlist, generate non-fabricated cover
letters, and track applications through their lifecycle. Degrades gracefully with
no LLM key — matching/tracking work offline; only CV-parse and cover-letter need it.

IMPORTANT — why everything renders inside ``main()``:
Streamlit re-executes the *entry script* on every rerun (e.g. a button click). The
entry point (``streamlit_app.py``) reaches this code via ``from ... import main``.
A module body runs only on its FIRST import, so if we rendered at module level the
page would draw once on initial load and then go blank on every rerun (Python skips
the cached re-import). Putting the rendering in ``main()`` — which the entry script
calls every run — fixes that. This was the real cause of "any button → white screen".
"""

from __future__ import annotations

import os

import streamlit as st

from job_agent.config import get_settings
from job_agent.matching import shortlist
from job_agent.matching.language import candidate_can_read
from job_agent.matching.seniority import is_junior_friendly
from job_agent.models.application import ApplicationStatus
from job_agent.models.candidate import CandidateProfile, Track
from job_agent.observability import InMemoryObservability, start_run
from job_agent.tracker import Tracker
from job_agent.tracker.state_machine import ALLOWED_TRANSITIONS
from job_agent.ui.demo_data import demo_jobs

# Languages the candidate can pick (ISO-639-1 -> label). Major European languages plus
# Czech and Chinese, per the target audience.
# Visa-feasibility tiebreak when two jobs are equally relevant (green above yellow).
_LEVEL_RANK_UI = {"green": 2, "yellow": 1, "red": 0}

_LANGS: dict[str, str] = {
    "en": "English", "de": "Deutsch (German)", "fr": "Français (French)",
    "it": "Italiano (Italian)", "es": "Español (Spanish)", "pt": "Português (Portuguese)",
    "nl": "Nederlands (Dutch)", "pl": "Polski (Polish)", "cs": "Čeština (Czech)",
    "sv": "Svenska (Swedish)", "da": "Dansk (Danish)", "ru": "Русский (Russian)",
    "zh": "中文 (Chinese)",
}

# Countries the candidate can target. Skewed to EU policy / international-relations hubs
# (Brussels for the EU institutions, The Hague for intl law, Geneva/Vienna for UN bodies).
_COUNTRIES: dict[str, str] = {
    "EU": "🌍 All of Europe (incl. Switzerland)",
    "CH": "🇨🇭 Switzerland (Geneva)", "BE": "🇧🇪 Belgium (Brussels / EU)",
    "NL": "🇳🇱 Netherlands (The Hague)", "DE": "🇩🇪 Germany", "AT": "🇦🇹 Austria (Vienna)",
    "FR": "🇫🇷 France", "IT": "🇮🇹 Italy (Rome)", "PL": "🇵🇱 Poland", "CZ": "🇨🇿 Czechia",
}

# Degree-granting country (the single biggest lever on visa feasibility — a *local*
# degree unlocks the labour market). "" = no European degree (e.g. studied at home).
_DEGREE_COUNTRIES: dict[str, str] = {
    "": "— none / non-European degree —",
    "CH": "🇨🇭 Switzerland", "DE": "🇩🇪 Germany", "AT": "🇦🇹 Austria", "NL": "🇳🇱 Netherlands",
    "BE": "🇧🇪 Belgium", "FR": "🇫🇷 France", "IT": "🇮🇹 Italy", "ES": "🇪🇸 Spain",
    "PL": "🇵🇱 Poland", "CZ": "🇨🇿 Czechia", "SE": "🇸🇪 Sweden", "DK": "🇩🇰 Denmark",
    "IE": "🇮🇪 Ireland", "GB": "🇬🇧 United Kingdom",
}


def _application_store():
    """Persist applications to Supabase when configured, else keep them in memory."""
    s = get_settings()
    if s.supabase_url and s.supabase_key:
        try:
            from job_agent.db.client import SupabaseClient
            from job_agent.persistence.supabase import SupabaseApplicationStore

            return SupabaseApplicationStore(SupabaseClient())
        except Exception:  # noqa: BLE001 - fall back to in-memory if Supabase is unavailable
            return None
    return None


def _job_store():
    """A SupabaseJobStore when configured, else None (jobs just aren't persisted)."""
    s = get_settings()
    if s.supabase_url and s.supabase_key:
        try:
            from job_agent.db.client import SupabaseClient
            from job_agent.persistence.supabase import SupabaseJobStore

            return SupabaseJobStore(SupabaseClient())
        except Exception:  # noqa: BLE001
            return None
    return None


def _render() -> None:
    """Draw the whole page. Called once per script run by ``main``."""
    # --- session state -------------------------------------------------------
    if "tracker" not in st.session_state:
        st.session_state.tracker = Tracker(_application_store())
    if "obs" not in st.session_state:
        st.session_state.obs = InMemoryObservability()
    if "letters" not in st.session_state:
        st.session_state.letters = {}  # job external_id -> cover letter text

    tracker: Tracker = st.session_state.tracker
    obs: InMemoryObservability = st.session_state.obs
    settings = get_settings()
    llm_enabled = bool(settings.llm_api_key)

    def _llm_ask():
        from job_agent.agents.llm import LLMClient

        return LLMClient(obs=obs).ask

    # --- sidebar: candidate profile -----------------------------------------
    # Explicit ``key=`` on every widget so Streamlit's auto-generated IDs are stable
    # across reruns.  Without them, changing one widget's *value* can shift the
    # hash-based key of a neighbouring widget on Community Cloud, triggering a
    # DuplicateWidgetID or a silent white-screen.  (See commit f04e55f.)
    st.sidebar.header("Candidate")
    nationality = st.sidebar.text_input("Nationality (ISO-2)", value="CN", key="wdg_nationality")
    degree_country = st.sidebar.selectbox(
        "Degree country", options=list(_DEGREE_COUNTRIES),
        index=list(_DEGREE_COUNTRIES).index("CH"),
        format_func=lambda c: _DEGREE_COUNTRIES[c], key="wdg_degree_country",
        help="The country that granted your highest relevant degree — the single biggest "
             "lever on visa feasibility. A local degree usually unlocks the labour market "
             "(e.g. a Swiss degree exempts the priority check in Switzerland).")
    field = st.sidebar.text_input("Field", value="international relations", key="wdg_field")
    skills_raw = st.sidebar.text_area("Skills (comma-separated)",
                                      value="policy analysis, advocacy, stakeholder engagement",
                                      key="wdg_skills")
    experience = st.sidebar.text_area(
        "Experience / past internships (free text)", height=200, max_chars=8000,
        key="wdg_experience",
        value="Internship at an EU public affairs consultancy: drafted policy briefs, "
              "monitored EU legislation, supported stakeholder engagement and advocacy.",
        help="Up to 8000 characters — paste a full CV or several internship descriptions. "
             "Jina semantically matches this against postings, so a role close to your past "
             "experience surfaces even when it shares no exact keywords. Also seeds the "
             "live search.")
    languages_selected = st.sidebar.multiselect(
        "Languages you speak", options=list(_LANGS), default=["en", "fr"],
        format_func=lambda c: _LANGS[c], key="wdg_languages",
        help="Used both for matching and to hide postings written in a language you "
             "don't read (e.g. German-only Swiss vacancies).")
    track_choices = st.sidebar.multiselect(
        "Employer types to include", ["private", "intl_org"],
        default=["private", "intl_org"], key="wdg_tracks",
        format_func=lambda t: {
            "private": "🏢 Private sector (companies, SMEs, start-ups)",
            "intl_org": "🌐 International organisations (UN/WHO-type)",
        }[t],
        help="🏢 Private sector = normal work-permit rules (visa depends on your "
             "nationality + degree country). 🌐 International organisations use a "
             "host-country legitimation card (national work permit bypassed) — visa is "
             "rarely the barrier, but entry is competitive and usually via internship/JPO.")
    years_exp = st.sidebar.number_input(
        "Years of work experience", min_value=0.0, max_value=40.0, value=0.0, step=0.5,
        key="wdg_years_exp",
        help="Drives the junior-friendly filter: postings demanding clearly more than "
             "this (or senior-titled: Head/Lead/Director…) are hidden. Internships count "
             "lightly — a fresh graduate is ~0.")

    if llm_enabled:
        cv_text = st.sidebar.text_area("…or paste a CV and parse it", height=120, key="wdg_cv_text")
        if st.sidebar.button("Parse CV with DeepSeek", key="btn_parse_cv") and cv_text.strip():
            from job_agent.parsing import parse_cv

            start_run("cv-parse")
            parsed = parse_cv(cv_text, _llm_ask())
            st.session_state.parsed_cv = parsed  # enables the CV-variant export later
            st.sidebar.success(f"Parsed: {parsed.field} · {', '.join(parsed.skills[:4])}")
            field, skills_raw = parsed.field, ", ".join(parsed.skills)
            experience = cv_text  # the pasted CV becomes the semantic-matching text
            if parsed.languages:  # merge CV-detected languages into the selection
                languages_selected = sorted({*languages_selected, *(l.lower() for l in parsed.languages)})
            degree_country = parsed.degree_country or degree_country
    else:
        st.sidebar.info("Set LLM_API_KEY (DeepSeek) to enable CV parsing & cover letters.")

    profile = CandidateProfile(
        nationality=nationality.strip().upper(),
        degree_country=(degree_country or "").strip().upper() or None,
        field=field.strip(),
        experience=experience.strip(),
        skills=[s.strip() for s in skills_raw.split(",") if s.strip()],
        languages=list(languages_selected),
        years_experience=years_exp,
        tracks=[Track(t) for t in track_choices] or [Track.private],
    )
    st.sidebar.caption(f"DeepSeek spend this session: ${obs.total_cost_usd():.4f}")

    st.sidebar.divider()
    st.sidebar.header("Jobs source")
    source_mode = st.sidebar.radio("Source", ["Demo data", "Live (configured sources)"],
                                   key="wdg_source_mode")
    live_countries = st.sidebar.multiselect(
        "Countries to search", options=list(_COUNTRIES), default=["CH", "BE", "NL"],
        format_func=lambda c: _COUNTRIES[c], key="wdg_live_country",
        help="Pick 🌍 All of Europe for the widest net (one broad sweep across all "
             "supported countries, Switzerland included) — best for hitting volume. Or "
             "pick up to 4 specific hubs (each searched separately, slower).")

    def _load_jobs():
        """Demo data, or a real multi-source Scout run per selected country."""
        if not source_mode.startswith("Live"):
            return demo_jobs(), []
        from job_agent.agents import ScoutQuery
        from job_agent.discovery import (DiscoveryQuery, keep_jobs_in_country,
                                         keep_jobs_in_europe)
        from job_agent.discovery.seed_builder import load_seeds
        from job_agent.persistence import dedupe_jobs
        from job_agent.pipeline import brave_search_fn, build_live_scout, production_transports

        # Discovery search terms come from the field + a few salient words of the
        # experience text (a whole paragraph makes a useless Brave query). These TARGET
        # which companies/roles get found and also filter the JobRoom feed.
        _stop = {"with", "from", "this", "that", "your", "into", "work", "team", "experience",
                 "internship", "intern", "support", "supported", "including"}
        seen: list[str] = []
        for w in (profile.field.replace(",", " ").split()
                  + [w.strip(".,;:()").lower() for w in profile.experience.split()]):
            wl = w.lower()
            if len(wl) > 3 and wl not in _stop and wl not in seen:
                seen.append(wl)
        keywords = seen[:6] or ["policy", "international"]

        http_get, http_json, http_post = production_transports()
        search_fn = brave_search_fn(settings)  # the discovery engine (if BRAVE_API_KEY set)
        seeds = load_seeds("seeds/seeds.json")
        all_jobs: list = []
        errors: list[str] = []

        def _scout(cities, cap):
            return build_live_scout(
                http_get=http_get, http_json=http_json, http_post=http_post,
                seeds=seeds, search_fn=search_fn,
                search_cities=cities, search_max_companies=cap,
                reliefweb_appname=settings.reliefweb_appname,
                rapidapi_key=settings.rapidapi_key, obs=obs)

        if "EU" in [c.upper() for c in live_countries]:
            # All of Europe: ONE broad sweep (no city filter → Brave finds companies
            # widely, only ~6 calls), then keep everything located in a supported country.
            try:
                result = _scout(cities=1, cap=80).run(
                    ScoutQuery(DiscoveryQuery(country=None, keywords=keywords)))
                all_jobs.extend(keep_jobs_in_europe(result.jobs))
                errors.extend(result.errors)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"Europe-wide scout failed: {exc}")
        else:
            countries = [c.upper() for c in live_countries][:4] or ["CH"]
            per_country = max(20, 80 // len(countries))  # bound total fetch
            for country in countries:
                try:
                    result = _scout(cities=2, cap=per_country).run(
                        ScoutQuery(DiscoveryQuery(country=country, keywords=keywords)))
                    all_jobs.extend(keep_jobs_in_country(result.jobs, country))
                    errors.extend(result.errors)
                except Exception as exc:  # noqa: BLE001 - one country must not abort the rest
                    errors.append(f"{country}: live scout failed: {exc}")

        jobs = dedupe_jobs(all_jobs)  # same role can appear under multiple countries' fetches
        store = _job_store()
        if store is not None and jobs:
            try:
                store.upsert_jobs(jobs)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"persist failed: {exc}")
        return jobs, errors

    # --- main ----------------------------------------------------------------
    st.title("EU Job Agent")
    tab_matches, tab_apps = st.tabs(["🎯 Matches", "📋 Applications"])

    with tab_matches:
        # Compute ONLY when the button is clicked, then cache in session_state. Otherwise
        # every interaction (track / cover-letter) would re-run the whole expensive
        # discovery + embedding pipeline — which is what white-screened the cloud app.
        if st.button("🔍 Find / refresh jobs", type="primary", key="btn_find_jobs"):
            from job_agent.matching import default_similarity

            with st.spinner("Working… Live mode searches companies across Europe and ranks "
                            "them — this usually takes 1–2 minutes."):
                found, errs = _load_jobs()
                try:
                    st.session_state.ranked = shortlist(profile, found,
                                                        similarity=default_similarity())
                except Exception as exc:  # noqa: BLE001 - embeddings down → lexical fallback
                    st.session_state.ranked = shortlist(profile, found)
                    errs = list(errs) + [f"semantic ranking unavailable ({exc}); used lexical."]
                st.session_state.scout_errors = errs

        for _e in st.session_state.get("scout_errors", [])[:5]:
            st.warning(_e)
        ranked = st.session_state.get("ranked")
        if ranked is None:
            st.info("Set your profile in the sidebar, choose a source, then click "
                    "**🔍 Find / refresh jobs**.")
            display = []
        else:
            viable_only = st.checkbox(
                "✅ Only show jobs I can realistically take (hide 🔴 blocked visa routes)",
                value=True, key="wdg_viable_only")
            lang_only = st.checkbox(
                "🗣️ Only postings in a language I read (hide e.g. German-only vacancies)",
                value=True, key="wdg_lang_only")
            junior_only = st.checkbox(
                "🎓 Junior-friendly only (hide senior roles / multi-year experience asks)",
                value=True, key="wdg_junior_only")
            _embed_on = bool(settings.embedding_api_key)
            min_rel = st.slider(
                "🎯 Strong-match threshold (shown from all countries)",
                0.0, 0.90 if _embed_on else 0.50, 0.45 if _embed_on else 0.05, 0.01,
                key="wdg_min_rel",
                help=("Jobs at/above this score show from every selected country. Lower it "
                      "for more results, raise it for tighter matches. "
                      + ("Semantic matching is ON (Jina): ~0.45–0.6 is a good band."
                         if _embed_on else
                         "Only keyword matching is active (set EMBEDDING_API_KEY / Jina for "
                         "sharper semantic matching) — keep this low.")))
            _eu_mode = "EU" in [c.upper() for c in live_countries]
            _primary = next((c.upper() for c in live_countries if c.upper() != "EU"), "CH")
            _primary_label = "all of Europe" if _eu_mode else _primary
            partial_on = st.checkbox(
                f"➕ Also show partial / semi-relevant matches ({_primary_label})",
                value=True, key="wdg_partial",
                help="Surfaces semi-relevant roles — e.g. public-sector jobs or ones close "
                     "to your internship experience — that fall just below the strong-match "
                     "bar. In single/multi-country mode these are limited to your primary "
                     "(first) country to avoid flooding; in 🌍 All-of-Europe they show "
                     "Europe-wide. Strong matches always show regardless.")
            partial_floor = max(0.0, min_rel - 0.20)

            def _passes(r):
                if viable_only and r.feasibility.level.value == "red":
                    return False
                if lang_only and not candidate_can_read(
                        profile.languages, r.job.title, r.job.description):
                    return False
                if junior_only and not is_junior_friendly(
                        r.job.title, r.job.description, max_years=profile.years_experience):
                    return False
                if r.similarity >= min_rel:
                    return True  # strong match → any selected country
                # Partial match: above the lower floor; Europe-wide in EU mode, else only
                # in the primary country (to avoid flooding the list with weak matches).
                if not (partial_on and r.similarity >= partial_floor):
                    return False
                return _eu_mode or r.job.country.upper() == _primary.upper()

            # Rank by a BLEND of relevance and visa feasibility, so:
            #   • a relevant role where you qualify (🟢, e.g. local-degree advantage in
            #     Switzerland) ranks above an equally-relevant one that needs sponsorship
            #     (🟡), but
            #   • an unrelated 🟢 role still can't outrank a clearly more-relevant one.
            # Relevance dominates; the visa tier adds a moderate boost (not a hard tier,
            # which previously let visa-easy-but-irrelevant jobs top the list).
            _VISA_BOOST = {"green": 0.15, "yellow": 0.05, "red": 0.0}
            display = sorted(
                (r for r in ranked if _passes(r)),
                key=lambda r: r.similarity + _VISA_BOOST[r.feasibility.level.value],
                reverse=True)
            _partial_n = sum(1 for r in display if r.similarity < min_rel)
            if not _embed_on:
                st.warning("⚠️ Semantic matching is OFF — ranking is crude keyword overlap. "
                           "Set EMBEDDING_API_KEY (Jina, free) in Secrets for accurate "
                           "matching; otherwise unrelated roles can slip in.")
            st.caption(f"Showing {min(len(display), 50)} of {len(ranked)} found "
                       f"({_partial_n} partial), best match first · "
                       + ("semantic (Jina) ✅" if _embed_on else "keyword-only ⚠️")
                       + ". 🟢 you qualify · 🟡 employer sponsors · 🔴 blocked.")
        for i, r in enumerate(display[:50]):  # cap rendered cards — hundreds is too heavy
            job = r.job
            uid = f"{i}-{job.source}-{job.external_id}"  # UNIQUE key (ids repeat across sources)
            emoji = {"green": "🟢", "yellow": "🟡", "red": "🔴"}[r.feasibility.level.value]
            _partial = r.similarity < st.session_state.get("wdg_min_rel", 0.0)
            _tag = " · ↔ partial match" if _partial else ""
            with st.expander(f"{emoji} {job.title} · {job.company} · {job.city}, {job.country}  "
                             f"— score {r.score} (sim {r.similarity}){_tag}"):
                # Plain-language visa status for a non-technical candidate.
                lvl = r.feasibility.level.value
                if lvl == "red":
                    st.error(f"🔴 **Hard for your profile** — {r.feasibility.path}")
                elif r.feasibility.needs_employer_sponsorship:
                    st.warning(f"🟡 **Viable, but the employer must sponsor a work permit** — "
                               f"{r.feasibility.path}")
                else:
                    st.success(f"🟢 **You qualify directly — no employer sponsorship needed** — "
                               f"{r.feasibility.path}")
                for _note in r.feasibility.notes:
                    if _note:
                        st.caption(f"↳ {_note}")
                st.write(job.description)
                if job.url:
                    # Deep-link straight to the real posting on the company's ATS /
                    # careers page so the candidate can apply directly.
                    st.markdown(f"**[🔗 View & apply on the company's site →]({job.url})**")
                else:
                    st.caption("↳ No direct application link for this posting.")
                parsed_cv = st.session_state.get("parsed_cv")
                cols = st.columns(3)
                if llm_enabled and cols[0].button("✍️ Cover letter", key=f"cl-{uid}"):
                    from job_agent.matching import analyze_gap
                    from job_agent.writing import generate_cover_letter

                    start_run("write")
                    ask = _llm_ask()
                    gap = analyze_gap(profile, job, ask)
                    letter = generate_cover_letter(profile, job, ask, emphasis=gap.emphasis)
                    st.session_state.letters[uid] = letter
                if llm_enabled and parsed_cv and cols[1].button("📄 CV variant (.docx)",
                                                                key=f"cv-{uid}"):
                    from job_agent.matching import analyze_gap
                    from job_agent.writing import generate_cv_variant

                    start_run("cv-variant")
                    ask = _llm_ask()
                    gap = analyze_gap(profile, job, ask)
                    path = generate_cv_variant(parsed_cv, job, ask, matched=gap.matched)
                    with open(path, "rb") as fh:
                        st.download_button("⬇️ Download tailored CV", fh.read(), file_name=path.name,
                                           key=f"dl-{uid}")
                if cols[2].button("➕ Track application", key=f"tr-{uid}"):
                    tracker.create(job, profile.nationality, st.session_state.letters.get(uid))
                    st.session_state.pop("apps_cache", None)  # Applications tab reloads on ↻
                    st.success("Added — open the Applications tab and click ↻ Load / refresh.")
                if uid in st.session_state.letters:
                    st.text_area("Cover letter", st.session_state.letters[uid],
                                 height=240, key=f"lt-{uid}")

    def _refresh_apps() -> None:
        try:
            st.session_state.apps_cache = (
                tracker.applications(), {a.id for a in tracker.due_followups()})
        except Exception as exc:  # noqa: BLE001 - a store hiccup must not blank the page
            st.error(f"Could not load applications: {exc}")
            st.session_state.apps_cache = ([], set())

    with tab_apps:
        # Lazy: the Supabase read happens only on click, never on initial page load (a
        # blocking read at load was the likely cause of the blank page on the cloud).
        if st.button("↻ Load / refresh applications", key="btn_refresh_apps"):
            _refresh_apps()
        apps, due = st.session_state.get("apps_cache", ([], set()))
        if not apps:
            st.info("Click **↻ Load / refresh applications** to see your tracked applications.")
        for app in apps:
            flag = " ⏰ follow up" if app.id in due else ""
            st.markdown(f"**{app.job_title}** · {app.company} — `{app.status.value}`{flag}")
            nxt = sorted(s.value for s in ALLOWED_TRANSITIONS[app.status])
            if nxt:
                cols = st.columns(len(nxt) + 1)
                for i, status in enumerate(nxt):
                    if cols[i].button(status, key=f"adv-{app.id}-{status}"):
                        tracker.advance(app.id, ApplicationStatus(status))
                        _refresh_apps()
                        st.rerun()
            else:
                st.caption("(terminal)")
            st.divider()


def main() -> None:
    """Entry point Streamlit re-runs on every interaction.

    Must run on *every* rerun (not just first import), so the entry script calls
    this each time. ``set_page_config`` has to be the first Streamlit call, before
    even ``st.secrets`` is touched.
    """
    st.set_page_config(page_title="EU Job Agent", layout="wide")
    st.caption("build 2026-06-08-aa")  # heartbeat: if you see this, the latest code is live

    # On Streamlit Community Cloud, config comes from the dashboard "Secrets" (no .env
    # in the repo). Mirror them into the environment so pydantic-settings reads them.
    try:
        for _k, _v in st.secrets.items():
            os.environ.setdefault(_k, str(_v))
    except Exception:  # noqa: BLE001 - no secrets configured → fine
        pass

    # Error boundary: a rerun that raises used to blank the page with no message.
    # Surface it on-page instead — but never swallow Streamlit's own control-flow
    # signals (st.stop / st.rerun), which are raised as exceptions by design.
    try:
        _render()
    except Exception as exc:  # noqa: BLE001
        if type(exc).__name__ in {"StopException", "RerunException", "RerunData"}:
            raise
        st.error("⚠️ The app hit an unexpected error (shown here so the page doesn't go blank):")
        st.exception(exc)


# Direct use — ``streamlit run src/job_agent/ui/app.py`` — runs THIS file as the entry
# script, so Streamlit re-executes it every rerun and this call fires each time.
# When reached via ``streamlit_app.py`` (the Cloud entry) this module is imported, so
# ``__name__`` isn't "__main__" and ``main()`` is NOT called here — the entry script
# calls it instead, which is what makes it run on every rerun. Do NOT call main() at
# import time, or the page would render once and blank on every subsequent rerun.
if __name__ == "__main__":
    main()
