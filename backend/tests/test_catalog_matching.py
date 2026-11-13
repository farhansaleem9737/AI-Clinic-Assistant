"""Catalog phrase matching (D132): the fix for the production freeze.

On 2026-11-13 the server froze for over a minute on "Book me with a
cardiologist": the watchdog's stack showed catalog_service._find compiling
regular expressions. It built one pattern per catalog phrase (three with the
plurals) on every doctor search, more than re's cache holds, so every search
recompiled them all. On a 0.1-CPU instance that took minutes.

These tests need no database:

    python -m pytest tests/test_catalog_matching.py --noconftest -q
"""

import random
import re
import time

from app.catalog import data
from app.services import catalog_service
from app.services.catalog_service import _find, simplify


_OLD_PATTERNS: dict[str, list] = {}


def old_patterns(phrase):
    return [re.compile(rf"(?<![a-z0-9\u0080-￿]){re.escape(c)}(?![a-z0-9\u0080-￿])") for c in (phrase, phrase + "s", phrase + "es")]


def old_find(text, phrase):
    """The previous implementation's patterns (compiled once here, so the
    comparison itself is not slow), kept only to prove the new one equivalent."""
    patterns = _OLD_PATTERNS.get(phrase) or _OLD_PATTERNS.setdefault(phrase, old_patterns(phrase))
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return match.span()
    return None


def catalog_phrases() -> list[str]:
    phrases = set()
    for slug, name, aliases, *_ in data.DEPARTMENTS:
        phrases |= {simplify(name), *aliases}
    for slug, name, departments, aliases, *_ in data.SPECIALIZATIONS:
        phrases |= {simplify(name), *aliases}
    for slug, name, kind, aliases, *_ in data.TOPICS:
        phrases |= {simplify(name), *aliases}
    return sorted(p for p in phrases if p)


TEXTS = [
    "book me with a cardiologist", "cardiology", "cardiologists please", "i need a heart doctor",
    "my child has diabetes", "type 2 diabetes and high blood sugar", "thyroid problem", "migraines for 3 days",
    "kidney stones", "ent", "dentist", "skin rash on my arm", "eyes", "general physician", "gp doctor near me",
    "pediatric endocrinology", "a neurologist for my mother", "cancer screening", "back pain", "chest pain",
    "dr ali cardiology", "ent-specialist", "cardiology2", "xcardiology", "cardiology", "قلب cardiology", "héart",
    "stoness", "stones", "diabetes", "", "   ",
]


def test_the_matcher_gives_exactly_the_old_results_for_every_catalog_phrase():
    phrases = catalog_phrases()
    assert len(phrases) > 300  # the real catalog: why re's cache could not hold the patterns
    texts = [simplify(t) for t in TEXTS] + [f"i want {p} please" for p in phrases[:200]] + phrases[:200]
    rng = random.Random(7)
    texts += [" ".join(rng.sample(phrases, 3)) for _ in range(100)]
    differences = [(t, p) for t in texts for p in phrases if _find(t, p) != old_find(t, p)]
    assert differences == []


def test_word_boundaries_and_plurals():
    assert _find("book me with a cardiologist", "cardiologist") == (15, 27)
    assert _find("two cardiologists", "cardiologist") == (4, 17)        # plural with s
    assert _find("kidney stones", "kidney stone") == (0, 13)
    assert _find("xcardiology", "cardiology") is None                    # part of a word
    assert _find("cardiology2", "cardiology") is None
    assert _find("ent-specialist", "ent") == (0, 3)                      # punctuation is a boundary
    assert _find("hearté", "heart") is None                              # non-ASCII letters continue a word
    assert _find("ent ent", "ent") == (0, 3)                             # the first occurrence


def test_matching_the_whole_catalog_is_fast_even_with_no_regex_cache():
    phrases = catalog_phrases()
    text = simplify("Book me with a cardiologist")
    re.purge()  # what every search used to face once the catalog outgrew the cache
    started = time.perf_counter()
    for _ in range(20):
        for phrase in phrases:
            _find(text, phrase)
    per_search = (time.perf_counter() - started) / 20
    # Locally the old code needed seconds per search after purge; the platform ~10x more.
    assert per_search < 0.05, per_search


def test_resolve_does_not_compile_regular_expressions(monkeypatch):
    """The event loop must never compile patterns per catalog phrase again."""
    compiled = []
    original = re._compile

    def counting(pattern, flags):
        compiled.append(pattern)
        return original(pattern, flags)

    monkeypatch.setattr(re, "_compile", counting)
    for phrase in catalog_phrases():
        _find("book me with a cardiologist", phrase)
    assert compiled == []
    assert catalog_service._word_char("a") and not catalog_service._word_char("-")
