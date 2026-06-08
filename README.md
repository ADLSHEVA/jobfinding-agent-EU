# EU Job Agent

A job-search agent for **junior international graduates** who want to build a career in
Europe — deliberately covering the **employers and international organisations that do
*not* recruit through LinkedIn** (SMEs on self-service ATS boards, public employment
services, and big employers that hire via their own career pages).

It builds a candidate profile (optionally parsed from a pasted CV), discovers live
postings across multiple sources, and ranks them by **visa feasibility + relevance**,
with hard filters for seniority and language. Runs as a Streamlit app; degrades
gracefully with no keys (demo data + offline matching).

Architecture patterns (dependency injection, multi-source Scout, observability,
offline-first testability) are adapted from the W-HS `job-agent-whs` reference project;
the domain model, source coverage, and the visa-feasibility engine are new.

## Two tracks

- **Track A — private / SME**: legal route is national work authorisation (EU Blue Card,
  post-study job-seeker permits, **local-degree exemptions**). Visa sponsorship is a
  *soft* signal, never a hard filter.
- **Track B — international organisations**: UN / EU / NGO roles + internships /
  traineeships / JPO. Host-country legitimation (national permit bypassed); very
  competitive at junior level.

## Visa feasibility — the core

Whether a candidate can take a job depends on
`(nationality, degree-country, years-experience) × job-country`:

- **EU/EEA/CH nationals** → free movement (🟢).
- **Non-EU with a LOCAL degree** in the job country → facilitated / exempt (🟢,
  e.g. CZ/PL: no permit; DE/AT/CH/NL: priority-check waived).
- **Non-EU JUNIOR without a local degree** → realistically **not sponsorable** for an
  entry-level role (🔴) — Blue-Card salary thresholds are out of reach and employers
  don't file a labour-market case for a junior. Their degree-country, posts that
  *advertise* sponsorship, and international organisations are the realistic routes.
- **Experienced** non-EU without a local degree → viable but employer files (🟡).

See `src/job_agent/visa/`. Results are ranked by a blend of relevance and feasibility,
not visa-first (a visa-easy but irrelevant role should not top the list).

> The encoded immigration rules are a starting point and must be verified against
> official sources before being shown to a user as advice.

## Sources

| Source | Coverage | Key needed |
| --- | --- | --- |
| **ATS discovery** (Brave Search → personio/greenhouse/lever/recruitee) | SMEs across Europe | `BRAVE_API_KEY` |
| **JobRoom** | Switzerland's official PES (job-room.ch) | — |
| **Arbeitsagentur** | German Federal Employment Agency | — |
| **Czech MPSV** | Czech official PES open data — incl. roles flagged open to non-EU workers (→ treated as explicit sponsorship) | — |
| **JSearch** (Google for Jobs) | Established employers via their own career pages (CH/DE/AT/FR/NL/IT/ES; not CZ/BE) | `RAPIDAPI_KEY` |
| **ReliefWeb** | Track-B intl-org jobs | `RELIEFWEB_APPNAME` (org-gated) |

Search one or more countries, or **🌍 All of Europe** (one broad sweep). EURES is
omitted (its public endpoint is dead).

## Matching & filters

- **Relevance**: semantic via Jina embeddings (`EMBEDDING_API_KEY`) — strongly
  recommended; falls back to crude keyword overlap otherwise. The pasted CV /
  experience text feeds the match, so roles close to your internships surface.
- **Seniority**: hides senior-titled roles and ones demanding multi-year experience
  (junior-friendly only).
- **Language**: hides postings written in — or hard-requiring — a language you don't
  list (e.g. German-only Swiss vacancies, or an English ad demanding native German).
- **Relevance threshold + partial tier**: strong matches show from all countries;
  semi-relevant ones show only in your primary country (or Europe-wide in All-of-Europe).
- **Apply links** point at the original employer posting.

## Running the app

```bash
uv sync --extra dev
uv run pytest                       # 130+ tests, fully offline
uv run streamlit run streamlit_app.py
```

Deployed on Streamlit Community Cloud: entry point is `streamlit_app.py`, Python 3.13
(pinned via `runtime.txt` / `.python-version`; Streamlit < 1.5x — see `requirements.txt`).

## Configuration (Streamlit secrets / `.env`)

All optional — the app runs on demo data with none. See `.streamlit/secrets.toml.example`.

```toml
BRAVE_API_KEY      = "..."   # Live ATS discovery
EMBEDDING_API_KEY  = "..."   # Jina — semantic matching (EMBEDDING_BASE_URL/MODEL too)
RAPIDAPI_KEY       = "..."   # JSearch / Google for Jobs
LLM_API_KEY        = "..."   # DeepSeek — CV parsing & cover letters
SUPABASE_URL / SUPABASE_KEY  # persist tracked applications
```

## Status

Live multi-source discovery, visa-aware + semantic ranking, application tracking
(Supabase or in-memory), and CV-tailored cover letters (with an LLM key). Country
coverage: CH, DE, AT, FR, NL, BE, IT, PL, CZ (+ international-org hubs). Everything is
covered by an offline `pytest` suite.
