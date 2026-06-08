"""Heuristic language detection for job postings.

ATS scrapes rarely populate the structured ``languages_required`` field — the real
requirement is implicit in the *language the posting is written in*. A vacancy written
in German almost always needs German on the job, even when it never says so. For an
international candidate who reads only en/fr, those postings are a poor fit and should
be filterable. This module infers the dominant language from marker words (no network,
no heavy NLP dependency).
"""

from __future__ import annotations

import re

# Common, high-frequency function words per language. Function words are far more
# reliable language signals than topical vocabulary (which is often English loanwords).
_MARKERS: dict[str, set[str]] = {
    "de": {"und", "der", "die", "das", "mit", "für", "sie", "wir", "bei", "eine", "einen",
           "sind", "oder", "auch", "werden", "deutsch", "kenntnisse", "erfahrung", "aufgaben",
           "bieten", "im", "von", "zu", "den", "ein", "ist", "als", "wie", "unsere"},
    "fr": {"le", "la", "les", "des", "une", "et", "pour", "avec", "vous", "nous", "dans",
           "sur", "est", "sont", "votre", "expérience", "nos", "au", "du", "en", "ce",
           "qui", "vos", "compétences", "poste"},
    "it": {"il", "la", "di", "che", "per", "con", "una", "sono", "nostro", "esperienza",
           "del", "gli", "nel", "alla", "tuo", "azienda", "lavoro", "competenze"},
    "en": {"the", "and", "with", "for", "you", "we", "are", "is", "to", "of", "your",
           "experience", "our", "team", "role", "skills", "work", "as", "in", "will"},
}


def posting_language(text: str) -> str | None:
    """Best-guess dominant language code ("de"/"fr"/"it"/"en"), or None if unclear."""
    words = re.findall(r"[a-zà-ÿ]+", text.lower())
    if len(words) < 8:  # too little text to judge
        return None
    counts = {lang: sum(1 for w in words if w in markers) for lang, markers in _MARKERS.items()}
    if re.search(r"[äöüß]", text.lower()):  # umlauts/eszett are a strong German tell
        counts["de"] += 3
    best = max(counts, key=lambda k: counts[k])
    return best if counts[best] >= 3 else None


# Explicit "you must speak language X" requirements — these are HARD: a posting may be
# written in English yet demand native/C2 German, which the language-of-posting check
# alone would miss. Matched case-insensitively against title+description.
_REQUIRES: dict[str, "re.Pattern[str]"] = {
    "de": re.compile(
        r"verhandlungssicher\w*\s+deutsch|fließend\w*\s+deutsch|stilsicher\w*\s+deutsch|"
        r"sehr\s+gute\s+deutschkenntnisse|muttersprache\s*\(?\s*deutsch|"
        r"deutsch\s*(?:\(?\s*(?:c1|c2)|kenntnisse\s+(?:erforderlich|zwingend|vorausgesetzt)|"
        r"\s+(?:erforderlich|zwingend|vorausgesetzt)|\s*-?\s*muttersprache)|"
        r"(?:fluent|native|proficient|excellent)\s+german|"
        r"german\s*(?:\(?\s*(?:c1|c2)|language\s+skills|fluen\w+|native|required|mandatory|"
        r"essential|proficiency)", re.IGNORECASE),
    "fr": re.compile(
        r"français\s+(?:courant|natif|langue\s+maternelle)|courant\s+en\s+français|"
        r"maîtrise\s+(?:parfaite\s+)?du\s+français|(?:fluent|native)\s+french|"
        r"french\s*(?:\(?\s*(?:c1|c2)|fluen\w+|native|required|mandatory)", re.IGNORECASE),
    "it": re.compile(
        r"(?:fluent|native)\s+italian|italian\s*(?:\(?\s*(?:c1|c2)|required)|"
        r"italiano\s+(?:fluente|madrelingua)", re.IGNORECASE),
}


def requires_unspoken_language(languages: list[str], text: str) -> str | None:
    """Return a language code the posting HARD-requires but the candidate lacks, else None."""
    spoken = {lang.lower() for lang in languages}
    for lang, pattern in _REQUIRES.items():
        if lang not in spoken and pattern.search(text):
            return lang
    return None


def candidate_can_read(languages: list[str], title: str, description: str) -> bool:
    """Whether a candidate who speaks ``languages`` can actually take this posting.

    Two HARD checks: (1) the posting must not explicitly require a language they lack
    (e.g. an English ad demanding native German); (2) a posting written in de/fr/it is
    only OK if they read it. English (or undetectable) postings otherwise pass — English
    is the lingua franca of the intl-friendly employers our audience targets.
    """
    text = f"{title}\n{description}"
    if requires_unspoken_language(languages, text):
        return False
    spoken = {lang.lower() for lang in languages}
    lang = posting_language(text)
    if lang is None or lang == "en":
        return True
    return lang in spoken
