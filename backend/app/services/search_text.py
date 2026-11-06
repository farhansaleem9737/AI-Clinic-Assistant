"""Name search that ignores case, punctuation, spacing and the "Dr." title (D114).

Doctor names are stored as entered ("Sarah Khan", sometimes "Dr. Sarah
Khan"); the title usually lives in `Doctor.title`. A plain ILIKE '%dr sarah
khan%' therefore found nothing. Both sides are now normalized the same way:
the query here in Python, the stored name in SQL (`normalized_sql`), and
neither is ever written back: display names stay exactly as stored.

Normalization: lower case; apostrophes dropped ("O'Brien" = "obrien");
ASCII punctuation and any whitespace run become one space; trimmed; then a
leading "dr" / "doctor" *followed by another word* is removed. Only the first
word is ever treated as a title, so "doctor" elsewhere in a name, or a search
for just "doctor", is kept. Letters of every script are left untouched (only
an explicit ASCII punctuation set is replaced), so non-Latin names compare
correctly and nothing outside that set is altered.

The Python and SQL versions must stay identical; tests check them against
each other on PostgreSQL.
"""

from __future__ import annotations

import re

from sqlalchemy import ColumnElement, and_, case, func, literal, or_

# Kept in step with _SQL_SEPARATORS below.
_APOSTROPHES = re.compile(r"['’ʼ`]")
_SEPARATORS = re.compile(r"[\s.,;:!?\"()\[\]{}/\\_+*&@#%^=<>|~$-]+")
_TITLE = re.compile(r"^(?:dr|doctor) ")

_SQL_APOSTROPHES = "['’ʼ`]"
_SQL_SEPARATORS = r'[[:space:].,;:!?"()\[\]{}/\\_+*&@#%^=<>|~$-]+'
_SQL_TITLE = "^(dr|doctor) "

# Fuzzy (typo) matching: pg_trgm word similarity, only when nothing matched
# otherwise, and only for queries long enough for trigrams to mean something.
FUZZY_MIN_LENGTH = 4
FUZZY_THRESHOLD = 0.5


def _plain(text: str | None) -> str:
    """Lower case, no apostrophes, punctuation and whitespace runs as one space."""
    value = _APOSTROPHES.sub("", (text or "").lower())
    return " ".join(_SEPARATORS.sub(" ", value).split())


def simplify(text: str | None) -> str:
    """The comparison form without title handling: lower case, no apostrophes,
    punctuation and whitespace runs as single spaces ("Children's  ENT" ->
    "childrens ent"). Used for catalog names and aliases (D118)."""
    return _plain(text)


def normalize(text: str | None) -> str:
    """'  Dr.Sarah   KHAN ' -> 'sarah khan'; 'Doctor' -> 'doctor'."""
    return _TITLE.sub("", _plain(text))


def titled_name(title: str | None, name: str) -> str:
    """'Dr.' + 'Sarah Khan' -> 'Dr. Sarah Khan', without doubling a title the
    stored name already starts with ('Dr. Sarah Khan' stays as stored)."""
    return f"{title} {name}" if title and not _TITLE.match(_plain(name)) else name


def contains_pattern(text: str) -> str:
    """'%text%' for ILIKE ... ESCAPE '\\', with the user's own % _ \\ taken
    literally (a search for "%" no longer matches everything)."""
    escaped = " ".join(text.split()).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def normalized_sql(column) -> ColumnElement[str]:
    """The same normalization as `normalize`, as a SQL expression."""
    value = func.regexp_replace(func.lower(column), _SQL_APOSTROPHES, "", "g")
    value = func.btrim(func.regexp_replace(value, _SQL_SEPARATORS, " ", "g"))
    return func.regexp_replace(value, _SQL_TITLE, "")


class NameMatch:
    """Conditions and a rank for matching one normalized query against a
    name column. Lower rank = better: 0 exact, 1 starts with the query,
    2 a word starts with the query, 3 every query word starts a word of the
    name (any order: "khan sarah", "sarah kh"), 4 contains the query."""

    def __init__(self, column, query: str):
        self.query = normalize(query)
        self.tokens = self.query.split()
        self.name = normalized_sql(column)
        # A leading space lets "% word" find a word start anywhere.
        spaced = literal(" ") + self.name
        q = self.query  # normalized: no LIKE wildcards (% and _ are separators)
        self._tiers = [
            self.name == q,
            self.name.like(f"{q}%"),
            spaced.like(f"% {q}%"),
            and_(*(spaced.like(f"% {t}%") for t in self.tokens)) if self.tokens else literal(False),
            self.name.like(f"%{q}%"),
        ]

    @property
    def usable(self) -> bool:
        return bool(self.query)

    def condition(self) -> ColumnElement[bool]:
        return or_(*self._tiers[2:])  # tiers 0-1 are implied by 2 and 4

    def rank(self, fallback: int = 5) -> ColumnElement[int]:
        return case(*((tier, i) for i, tier in enumerate(self._tiers)), else_=fallback)

    # ---- typo tolerance (needs the pg_trgm extension, migration a9c4e2f7b310) ----

    @property
    def fuzzy_usable(self) -> bool:
        return len(self.query) >= FUZZY_MIN_LENGTH

    def similarity(self) -> ColumnElement[float]:
        return func.word_similarity(self.query, self.name)

    def fuzzy_condition(self) -> ColumnElement[bool]:
        return self.similarity() >= FUZZY_THRESHOLD
