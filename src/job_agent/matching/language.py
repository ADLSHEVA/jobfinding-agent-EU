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


def candidate_can_read(languages: list[str], title: str, description: str) -> bool:
    """Whether a candidate who speaks ``languages`` can read this posting.

    English (and undetectable) postings are assumed readable — English is the lingua
    franca of intl-friendly employers and our target audience reads it. A posting in
    de/fr/it is readable only if the candidate lists that language.
    """
    spoken = {lang.lower() for lang in languages}
    lang = posting_language(f"{title}\n{description}")
    if lang is None or lang == "en":
        return True
    return lang in spoken
