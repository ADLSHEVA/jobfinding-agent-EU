"""Heuristic seniority detection — keep the shortlist junior-appropriate.

The product targets junior / early-career international graduates, so postings that
demand years of experience (or are senior-titled: Head/Lead/Director…) are a hard
mismatch and should be filterable. Signals come from the title and the body text, in
the languages we crawl (EN/DE/FR/IT). No network, no NLP dependency.
"""

from __future__ import annotations

import re

# Senior-titled roles (multi-lingual). Word-boundary matched, case-insensitive.
_SENIOR_TITLE = re.compile(
    r"\b(senior|sr\.?|lead|principal|staff|head\s+of|director|chief|c[ft]o|ceo|vp|"
    r"vice[-\s]president|geschäftsführ\w*|leiter\w*|leitung|abteilungsleiter\w*|"
    r"teamlead\w*|responsable|directeur|directrice|dirigent\w*)\b",
    re.IGNORECASE)

# Explicitly junior/entry roles — these always pass, even if a body mentions years.
_JUNIOR_TITLE = re.compile(
    r"\b(junior|jr\.?|graduate|entry[-\s]?level|intern|internship|trainee|apprentice\w*|"
    r"werkstudent\w*|praktik\w*|absolvent\w*|einsteiger\w*|stagiaire|assistant\w*|"
    r"assistenz\w*|young\s+professional)\b",
    re.IGNORECASE)

# "5 years", "5+ years", "5-10 years", "min. 3 Jahre", "3 ans", "3 anni" → capture the
# first (minimum) number of years stated.
_YEARS = re.compile(
    r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?(?:years?|jahre[n]?|ans|anni|yrs?)\b",
    re.IGNORECASE)

# Phrases that signal a seasoned hire even with no number and no senior-y title.
_SENIOR_BODY = re.compile(
    r"mehrj[äa]hrige|langj[äa]hrige|fundierte\s+(?:berufs|kenntniss)|"
    r"einschl[äa]gige\s+berufserfahrung|proven\s+(?:track\s+record|experience)|"
    r"extensive\s+experience|solid\s+experience|several\s+years|seasoned|"
    r"experienced\s+professional|expérience\s+confirmée",
    re.IGNORECASE)


def required_years(text: str) -> int | None:
    """Lowest explicit years-of-experience requirement in ``text``, or None."""
    yrs = [int(m.group(1)) for m in _YEARS.finditer(text)]
    yrs = [y for y in yrs if y <= 40]  # ignore stray big numbers
    return min(yrs) if yrs else None


def is_junior_friendly(title: str, description: str, max_years: float = 2.0) -> bool:
    """Whether a posting is plausibly open to a candidate with ``max_years`` experience.

    Explicit junior/intern titles always pass; explicit senior titles never do. Otherwise
    a stated requirement above ``max_years`` (+1 grace year) rules it out.
    """
    title = title or ""
    body = f"{title}\n{description or ''}"
    if _JUNIOR_TITLE.search(title):
        return True
    if _SENIOR_TITLE.search(title):
        return False
    yrs = required_years(body)
    if yrs is not None and yrs > max_years + 1:
        return False
    # No senior title and no explicit year count, but the body demands a seasoned hire.
    if max_years < 2 and _SENIOR_BODY.search(body):
        return False
    return True
