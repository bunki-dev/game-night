"""Content safety for a game played in living rooms, often with kids.

Player text (names, Hot Take answers) is masked before anyone sees it. Generated
content is constrained by the prompt and re-checked here after generation.
"""

from __future__ import annotations

import re
import unicodedata

# Deliberately small and mild: enough to keep a family game clean without a dependency.
_BLOCKED = [
    "fuck",
    "shit",
    "bitch",
    "cunt",
    "dick",
    "piss",
    "bastard",
    "slut",
    "whore",
    "wank",
    "bollocks",
    "nigger",
    "faggot",
    "retard",
    "porn",
    "nude",
    "naked",
    "sex",
]
# Whole words plus common endings, so "Dickens" or "Sussex" aren't caught but "shithead" is.
_BLOCKED_RE = re.compile(r"\b(?:" + "|".join(_BLOCKED) + r")(?:s|es|ed|er|ers|ing|y|head|heads)?\b", re.I)
_ADULT_TOPICS = re.compile(r"\b(alcohol|beer|wine|drunk|gambling|casino|drugs?|weed|murder|suicide|gore)\b", re.I)


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return "".join(ch for ch in text if ch.isprintable())


def mask_profanity(text: str) -> str:
    return _BLOCKED_RE.sub(lambda m: m.group(0)[0] + "*" * (len(m.group(0)) - 1), _normalise(text))


def has_profanity(text: str) -> bool:
    return bool(_BLOCKED_RE.search(_normalise(text)))


def clean_name(name: str) -> str:
    name = _normalise(name).strip()
    name = re.sub(r"\s+", " ", name)[:14]
    if not name:
        raise ValueError("empty name")
    return "Player" if has_profanity(name) else name


def generated_text_ok(text: str, audience: str) -> bool:
    """Final check on anything the model wrote before it reaches the TV."""
    if has_profanity(text):
        return False
    return audience == "adults" or not _ADULT_TOPICS.search(text)


_INJECTION = re.compile(
    r"ignore (all |any |the )?(previous|prior|above|earlier) (instructions|rules)|\bsystem\s*:|"
    r"\b(give|award|score) (me|this|this answer|answer [a-d])\b.*\b(10|ten|points|highest|most)|"
    r"\bjudge (must|should|will)\b|\b(10|ten)\s*/\s*10\b|most points",
    re.I,
)


def looks_like_injection(text: str) -> bool:
    """Answers that try to instruct the judge instead of answering the prompt."""
    return bool(_INJECTION.search(_normalise(text)))
