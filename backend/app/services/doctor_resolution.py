"""Which listed doctor a person means by a name (D133).

"Dr. Emily Carter", "dr emily carter", "Doctor Emily Carter", "Emily Carter"
and "Dr Emily" are the same request. Only the public directory is used
(doctor_service.list_doctors with public=True: active, approved, listed
doctors), so the assistant can never name or book someone who is not there.

Outcomes, strictest first:
- exact: the normalized name is exactly one doctor's name;
- confident: every word the person gave starts a word of exactly one
  doctor's name ("Dr Emily" -> Emily Carter, when she is the only Emily);
- ambiguous: several doctors fit equally: the person must choose;
- close: no doctor fits, but some names are similar (typos): suggestions,
  never chosen automatically;
- none: nobody by that name.
"""

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.pagination import PageParams
from app.services import doctor_service
from app.services.doctor_service import DoctorFilters
from app.services.search_text import normalize

# Courtesy titles the person may put in front of a name (in any case, with or without a dot).
TITLES = {"dr", "doctor", "prof", "professor", "mr", "mrs", "ms", "miss", "sir", "madam"}
MAX_CANDIDATES = 5
# How similar a name must be to be suggested ("Emily Karter" for "Emily Carter"), never chosen.
CLOSE_RATIO = 0.75


@dataclass
class NameResolution:
    status: str  # exact | confident | ambiguous | close | none
    said: str
    doctors: list = field(default_factory=list)  # DoctorRow, best first

    @property
    def chosen(self):
        return self.doctors[0] if self.status in ("exact", "confident") else None


def name_words(text: str | None) -> list[str]:
    """'Dr. Emily  CARTER' -> ['emily', 'carter']; titles anywhere at the start are dropped."""
    words = normalize(text).split()
    while words and words[0].rstrip(".") in TITLES:
        words = words[1:]
    return words


def _fits(said: list[str], name: list[str]) -> bool:
    """Every word given starts a different word of the name, in any order."""
    left = list(name)
    for word in said:
        hit = next((w for w in left if w.startswith(word)), None)
        if hit is None:
            return False
        left.remove(hit)
    return True


async def resolve(db: AsyncSession, said: str | None) -> NameResolution:
    words = name_words(said)
    if not words:
        return NameResolution("none", said or "")
    query = " ".join(words)
    rows, _ = await doctor_service.list_doctors(
        db, PageParams(page=1, page_size=20), DoctorFilters(q=query), public=True
    )
    by_name = [(r, name_words(r.name)) for r in rows]
    exact = [r for r, name in by_name if name == words]
    if exact:
        return NameResolution("exact" if len(exact) == 1 else "ambiguous", said, exact[:MAX_CANDIDATES])
    fitting = [r for r, name in by_name if _fits(words, name)]
    if len(fitting) == 1:
        return NameResolution("confident", said, fitting)
    if fitting:
        return NameResolution("ambiguous", said, fitting[:MAX_CANDIDATES])
    # Not this name. Rows found through a specialty or department word, or the
    # directory's typo search, are suggested only when the NAME itself is similar.
    close = [r for r, name in by_name if SequenceMatcher(None, query, " ".join(name)).ratio() >= CLOSE_RATIO]
    return NameResolution("close" if close else "none", said, close[:MAX_CANDIDATES])
