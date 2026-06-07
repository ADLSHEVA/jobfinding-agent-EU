"""EU Job Agent — Streamlit dashboard.

Run with:  streamlit run src/job_agent/ui/app.py
(install the UI extra first:  uv pip install -e '.[llm,ui]')

Ties the pipeline together: build a candidate profile (optionally parsed from a CV
via DeepSeek), see a visa-aware ranked shortlist, generate non-fabricated cover
letters, and track applications through their lifecycle. Degrades gracefully with
no LLM key — matching/tracking work offline; only CV-parse and cover-letter need it.
"""

from __future__ import annotations

import os

import streamlit as st

# On Streamlit Community Cloud, config comes from the dashboard "Secrets" (no .env in
# the repo). Mirror them into the environment so pydantic-settings (config.py) reads
# them. Locally this is a no-op (there is no secrets file; .env is used instead).
try:
    for _k, _v in st.secrets.items():
        os.environ.setdefault(_k, str(_v))
except Exception:  # noqa: BLE001 - no secrets configured → fine
    pass

from job_agent.config import get_settings  # noqa: E402
from job_agent.matching import shortlist  # noqa: E402
from job_agent.models.application import ApplicationStatus  # noqa: E402
from job_agent.models.candidate import CandidateProfile, Track  # noqa: E402
from job_agent.observability import InMemoryObservability, start_run  # noqa: E402
from job_agent.tracker import Tracker  # noqa: E402
from job_agent.tracker.state_machine import ALLOWED_TRANSITIONS  # noqa: E402
from job_agent.ui.demo_data import demo_jobs  # noqa: E402

st.set_page_config(page_title="EU Job Agent", layout="wide")
st.caption("build 2026-06-07-g")  # version heartbeat: if you see this, the latest code is live


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


# --- session state -----------------------------------------------------------
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


# --- sidebar: candidate profile ---------------------------------------------
# Explicit ``key=`` on every widget so Streamlit's auto-generated IDs are stable
# across reruns.  Without them, changing one widget's *value* can shift the
# hash-based key of a neighbouring widget on Community Cloud, triggering a
# DuplicateWidgetID or a silent white-screen.  (See commit f04e55f.)
st.sidebar.header("Candidate")
nationality = st.sidebar.text_input("Nationality (ISO-2)", value="CN", key="wdg_nationality")
degree_country = st.sidebar.text_input("Degree country (ISO-2, or blank)", value="CH", key="wdg_degree_country")
field = st.sidebar.text_input("Field", value="international relations", key="wdg_field")
skills_raw = st.sidebar.text_area("Skills (comma-separated)",
                                  value="policy analysis, advocacy, stakeholder engagement",
                                  key="wdg_skills")
languages_raw = st.sidebar.text_input("Languages (ISO-639-1, comma)", value="en, fr", key="wdg_languages")
track_choices = st.sidebar.multiselect("Tracks", ["private", "intl_org"],
                                       default=["private", "intl_org"], key="wdg_tracks")

if llm_enabled:
    cv_text = st.sidebar.text_area("…or paste a CV and parse it", height=120, key="wdg_cv_text")
    if st.sidebar.button("Parse CV with DeepSeek", key="btn_parse_cv") and cv_text.strip():
        from job_agent.parsing import parse_cv

        start_run("cv-parse")
        parsed = parse_cv(cv_text, _llm_ask())
        st.session_state.parsed_cv = parsed  # enables the CV-variant export later
        st.sidebar.success(f"Parsed: {parsed.field} · {', '.join(parsed.skills[:4])}")
        field, skills_raw = parsed.field, ", ".join(parsed.skills)
        languages_raw = ", ".join(parsed.languages)
        degree_country = parsed.degree_country or degree_country
else:
    st.sidebar.info("Set LLM_API_KEY (DeepSeek) to enable CV parsing & cover letters.")

try:
    profile = CandidateProfile(
        nationality=nationality.strip().upper(),
        degree_country=degree_country.strip().upper() or None,
        field=field.strip(),
        skills=[s.strip() for s in skills_raw.split(",") if s.strip()],
        languages=[lang.strip().lower() for lang in languages_raw.split(",") if lang.strip()],
        tracks=[Track(t) for t in track_choices] or [Track.private],
    )
except Exception as exc:
    st.error(f"Profile error: {exc}")
    st.stop()
st.sidebar.caption(f"DeepSeek spend this session: ${obs.total_cost_usd():.4f}")

st.sidebar.divider()
st.sidebar.header("Jobs source")
source_mode = st.sidebar.radio("Source", ["Demo data", "Live (configured sources)"], key="wdg_source_mode")
live_country = st.sidebar.text_input("Country (ISO-2)", value="CH", key="wdg_live_country")
live_keywords = st.sidebar.text_input("Keywords", value="policy", key="wdg_live_keywords")


def _load_jobs():
    """Demo data, or a real multi-source Scout run for live mode."""
    if not source_mode.startswith("Live"):
        return demo_jobs(), []
    from job_agent.agents import ScoutQuery
    from job_agent.discovery import DiscoveryQuery, keep_jobs_in_country
    from job_agent.discovery.seed_builder import load_seeds
    from job_agent.pipeline import brave_search_fn, build_live_scout, production_transports

    country = live_country.strip().upper() or None
    http_get, http_json, http_post = production_transports()
    scout = build_live_scout(
        http_get=http_get, http_json=http_json, http_post=http_post,
        seeds=load_seeds("seeds/seeds.json"),
        search_fn=brave_search_fn(settings),  # the discovery engine (if BRAVE_API_KEY set)
        search_cities=2,           # lighter on cloud memory + Brave quota than the default 3
        search_max_companies=40,   # bound the fetch so the cloud app doesn't run out of memory
        obs=obs,
    )
    query = ScoutQuery(DiscoveryQuery(
        country=country,
        keywords=[k.strip() for k in live_keywords.split(",") if k.strip()],
    ))
    try:
        result = scout.run(query)
        jobs = result.jobs
        # Sources/discovered tenants are cross-border → keep only target-country jobs.
        if country:
            jobs = keep_jobs_in_country(jobs, country)
        errors = list(result.errors)
        # Persist the relevant (in-country) jobs to Supabase if configured.
        store = _job_store()
        if store is not None and jobs:
            try:
                store.upsert_jobs(jobs)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"persist failed: {exc}")
        return jobs, errors
    except Exception as exc:  # noqa: BLE001 - surface, don't crash the UI
        return [], [f"live scout failed: {exc}"]


# --- main --------------------------------------------------------------------
st.title("EU Job Agent")
tab_matches, tab_apps = st.tabs(["🎯 Matches", "📋 Applications"])

with tab_matches:
    # Compute ONLY when the button is clicked, then cache in session_state. Otherwise
    # every interaction (track / cover-letter) would re-run the whole expensive
    # discovery + embedding pipeline — which is what white-screened the cloud app.
    if st.button("🔍 Find / refresh jobs", type="primary", key="btn_find_jobs"):
        from job_agent.matching import default_similarity

        with st.spinner("Working… Live mode discovers companies via search; can take a minute."):
            found, errs = _load_jobs()
            try:
                st.session_state.ranked = shortlist(profile, found, similarity=default_similarity())
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
    else:
        st.caption(f"{len(ranked)} viable jobs, ranked by visa feasibility then CV relevance "
                   f"(showing top {min(len(ranked), 50)}).")
    for i, r in enumerate((ranked or [])[:50]):  # cap rendered cards — hundreds would be too heavy
        job = r.job
        uid = f"{i}-{job.source}-{job.external_id}"  # UNIQUE widget key (ids can repeat across sources)
        emoji = {"green": "🟢", "yellow": "🟡", "red": "🔴"}[r.feasibility.level.value]
        with st.expander(f"{emoji} {job.title} · {job.company} · {job.city}, {job.country}  "
                         f"— score {r.score} (sim {r.similarity})"):
            st.write(f"**Visa path:** {r.feasibility.path}")
            st.write(f"**Sponsorship needed:** {r.feasibility.needs_employer_sponsorship} · "
                     f"**Signal:** {job.visa_signal.value} · **Track:** {job.track.value}")
            st.write(job.description)
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
            if llm_enabled and parsed_cv and cols[1].button("📄 CV variant (.docx)", key=f"cv-{uid}"):
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
