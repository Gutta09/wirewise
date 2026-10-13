"""Normalisation and matching primitives (assessment Section 6).

These are pure functions with no database access, which is what makes the
matching rules cheap to unit-test.
"""

import re

# Entity suffixes dropped from the *end* of an investor name. "TRUST" is kept,
# because it carries meaning ("Patel Family Trust" vs "Patel Family").
ENTITY_SUFFIXES = {"LLC", "LP", "LTD", "INC"}

_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")


def normalise_reference(value: str | None) -> str:
    """Uppercase, dropping everything except letters and digits (``cc-1003`` -> ``CC1003``)."""
    if not value:
        return ""
    return _NON_ALNUM.sub("", value).upper()


def normalise_words(value: str | None) -> str:
    """Uppercase, with every run of non-alphanumerics collapsed to one space."""
    if not value:
        return ""
    return _NON_ALNUM.sub(" ", value).upper().strip()


def normalise_name(value: str | None) -> str:
    """``normalise_words`` plus a single trailing entity suffix removed."""
    words = normalise_words(value).split()
    if len(words) > 1 and words[-1] in ENTITY_SUFFIXES:
        words.pop()
    return " ".join(words)


def contains_reference(haystack: str | None, normalised_reference: str) -> bool:
    """True if the reference appears anywhere in ``haystack`` once both are normalised.

    Substring rather than whole-word, so ``REFCC1003`` still counts as a hit.
    """
    if not normalised_reference:
        return False
    return normalised_reference in normalise_reference(haystack)


def contains_name(description: str | None, normalised_name: str) -> bool:
    """True if ``normalised_name`` appears as whole words in the description.

    Both sides are word-normalised to single spaces, so padding with spaces is a
    complete word-boundary test and ``"PATEL FAMILY TRUSTEES"`` is not a hit for
    ``"PATEL FAMILY TRUST"``.
    """
    if not normalised_name:
        return False
    haystack = f" {normalise_words(description)} "
    return f" {normalised_name} " in haystack
