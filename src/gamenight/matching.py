"""Forgiving answer matching for typed guesses: case, punctuation, "the", small typos."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

_LEADING = re.compile(r"^(the|a|an)\s+")


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return _LEADING.sub("", text)


def matches(guess: str, answer: str, aliases: list[str] | tuple[str, ...] = (), threshold: float = 0.85) -> bool:
    """True if the guess is the answer (or an alias), allowing for small typos in longer answers."""
    g = normalise(guess)
    if not g:
        return False
    for target in (answer, *aliases):
        t = normalise(target)
        if not t:
            continue
        if g == t or g.replace(" ", "") == t.replace(" ", ""):
            return True
        # Typos only count on answers long enough that a near miss is still clearly right.
        if len(t) >= 6 and SequenceMatcher(None, g, t).ratio() >= threshold:
            return True
    return False
