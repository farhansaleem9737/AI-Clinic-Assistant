"""The assistant's safety boundary (D100), applied before anything reaches the
AI provider. Deterministic: no model is asked.

- Urgent symptoms get fixed emergency guidance at once, without a model call
  or tool calls that would only delay it.
- Unless the provider is approved for patient information (AI_PHI_ALLOWED),
  identifiers typed into a message (email addresses, phone numbers, MRNs,
  national ID numbers) are replaced with placeholders in what the provider
  receives. The stored conversation keeps the user's own words. Redaction
  reduces exposure; it does not make clinical text anonymous, which is why
  documents and patient-record tools stay off without AI_PHI_ALLOWED.
"""

import re

_REDACTIONS = (
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[email]"),
    (re.compile(r"\bMRN\s*\d{4,}\b", re.IGNORECASE), "[MRN]"),
    # Pakistani CNIC and similar dashed national ID numbers.
    (re.compile(r"\b\d{5}-\d{7}-\d\b"), "[ID number]"),
    # Phone numbers: 7+ digits, optionally with +, spaces, dashes, dots or brackets.
    (re.compile(r"(?<![\w/])\+?\(?\d[\d\s().-]{5,}\d(?![\w/])"), "[phone]"),
)
# Dates and times stay: they are what booking requests are made of.
_DATE_LIKE = re.compile(r"^\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}$|^\d{1,2}:\d{2}$")


def redact(text: str) -> str:
    for pattern, placeholder in _REDACTIONS:
        if placeholder == "[phone]":
            text = pattern.sub(lambda m: m.group(0) if _DATE_LIKE.match(m.group(0).strip()) else placeholder, text)
        else:
            text = pattern.sub(placeholder, text)
    return text


_URGENT = re.compile(
    r"\b("
    r"chest pain|crushing chest|heart attack|can'?t breathe|cannot breathe|can not breathe|difficulty breathing|"
    r"struggling to breathe|stopped breathing|choking|stroke|face (?:is )?drooping|slurred speech|"
    r"unconscious|passed out|not responding|unresponsive|seizure|fitting|severe bleeding|bleeding heavily|"
    r"won'?t stop bleeding|overdose|poisoned|swallowed poison|suicid\w*|kill myself|end my life|"
    r"want to die|self[- ]harm|anaphyla\w*|throat (?:is )?closing|severe allergic"
    r")\b",
    re.IGNORECASE,
)

EMERGENCY_REPLY = (
    "**This may be an emergency.** If you or someone with you has these symptoms now, "
    "call your local emergency number or go to the nearest emergency department immediately. "
    "Do not wait for an appointment.\n\n"
    "If you are thinking about harming yourself, please contact emergency services or a crisis line "
    "right away; you do not have to face this alone.\n\n"
    "I'm an assistant, not a doctor, and can't assess symptoms. When you are safe, I can help you "
    "find a doctor or book a follow-up visit."
)


def is_urgent(text: str) -> bool:
    return bool(_URGENT.search(text))
