"""Internal data never reaches the patient's chat (D133).

The model gets internal context (record ids, what the cards showed). It has
copied that context into its answers, e.g. "Shown to the user: doctors in
this order: 1. Dr. Emily Carter (doctor_id 01a0...)". The prompt says not to,
but that is not relied on. Every answer passes through internal_free() before
it is saved, and through StreamRedactor while it streams, so neither the live
text nor the stored message can carry:

- "[Shown to the user: ...]" notes, or lines starting "Shown to the user:";
- record ids: "doctor_id <uuid>", "(document_id: <uuid>)", or a bare uuid.

Cards keep their ids: those are routing data for the app's own links and
buttons, never prose.
"""

import re

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_NOTE = re.compile(r"\[\s*shown to the user\s*:[^\]]*\]?", re.I)
_NOTE_LINE = re.compile(r"(?im)^[ \t>*•-]*\(?\s*shown to the user\s*:[^\n]*(?:\n|$)")
_ID_MENTION = re.compile(rf"\b(?:doctor|document|appointment|patient|conversation|message)[ _]?id\b\s*[:=#]?\s*{_UUID}(?:,\s*)?", re.I)
_BARE_ID = re.compile(rf"\b{_UUID}\b(?:,\s*)?", re.I)
_EMPTY_BRACKETS = re.compile(r"\s*\(\s*[,;]?\s*\)|\s*\[\s*\]")


def internal_free(text: str | None) -> str:
    """The text without internal notes or record ids. Identity for ordinary text."""
    if not text:
        return text or ""
    if "hown to the user" not in text.lower() and not re.search(_UUID, text, re.I):
        return text  # the common case: nothing to remove, nothing changed
    text = _NOTE.sub("", text)
    text = _NOTE_LINE.sub("", text)
    text = _ID_MENTION.sub("", text)
    text = _BARE_ID.sub("", text)
    text = _EMPTY_BRACKETS.sub("", text)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"[ \t]+([,.;:)])", r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text)


class StreamRedactor:
    """internal_free() for text arriving in chunks.

    The last HOLD characters (and any unfinished "[..." note) wait for more
    text; everything before is cleaned and sent, but only when it is a prefix
    of what the cleaned whole will be, so nothing sent is ever contradicted.
    """

    HOLD = 64

    def __init__(self) -> None:
        self.raw = ""
        self.sent = ""

    def _safe_cut(self) -> int:
        cut = len(self.raw) - self.HOLD
        if cut <= 0:
            return 0
        space = max(self.raw.rfind(" ", 0, cut), self.raw.rfind("\n", 0, cut))
        cut = space if space > 0 else 0
        bracket = self.raw.rfind("[")
        if bracket != -1 and "]" not in self.raw[bracket:]:
            cut = min(cut, bracket)
        return cut

    def _advance(self, cleaned: str) -> str:
        if not cleaned.startswith(self.sent) or len(cleaned) <= len(self.sent):
            return ""
        out, self.sent = cleaned[len(self.sent):], cleaned
        return out

    def feed(self, chunk: str) -> str:
        self.raw += chunk
        part = internal_free(self.raw[: self._safe_cut()])
        if not internal_free(self.raw).startswith(part):
            return ""
        return self._advance(part)

    def flush(self) -> str:
        out = self._advance(internal_free(self.raw))
        self.raw, self.sent = "", ""
        return out
