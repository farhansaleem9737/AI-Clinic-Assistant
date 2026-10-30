"""Local, deterministic reading of patient medical documents (D101).

Runs entirely on this server: no AI provider sees the content unless
AI_PHI_ALLOWED says the provider is approved for it. From each document it
extracts text page by page (PDF text layer; local OCR with the Tesseract
command when it is installed), then finds laboratory rows of the form
"name  value  unit  reference-range  flag". Nothing is invented: a value
without a printed reference range is never judged in or out of range, and
dates are kept exactly as printed.

Uploaded files are data only: they are parsed, never executed, and their
text is never treated as instructions.
"""

import io
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

logger = logging.getLogger(__name__)

MAX_PAGES = 50
MAX_TEXT_CHARS = 60_000
MAX_OCR_PAGES = 5
OCR_TIMEOUT_SECONDS = 20


@dataclass
class Page:
    number: int
    text: str
    ocr: bool = False


@dataclass
class Measurement:
    test: str
    value: str
    unit: str | None
    reference_range: str | None
    report_flag: str | None
    # "high" / "low" against the printed range; None when there is no usable range.
    out_of_range: str | None
    page: int

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class Reading:
    pages: list[Page] = field(default_factory=list)
    # Pages with no text layer that could not be OCR'd.
    unreadable_pages: list[int] = field(default_factory=list)
    problem: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(f"[Page {p.number}]\n{p.text}" for p in self.pages)[:MAX_TEXT_CHARS]


def ocr_available() -> bool:
    return shutil.which("tesseract") is not None


def _ocr(image: bytes, suffix: str) -> str | None:
    """Local OCR with the Tesseract command, bounded in time. None if unavailable or failed."""
    binary = shutil.which("tesseract")
    if binary is None:
        return None
    with tempfile.TemporaryDirectory() as tmp:  # removed afterwards, whatever happens
        source = Path(tmp) / f"page{suffix}"
        source.write_bytes(image)
        try:
            done = subprocess.run(
                [binary, str(source), "stdout"], capture_output=True, timeout=OCR_TIMEOUT_SECONDS, check=False
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
    return done.stdout.decode("utf-8", "replace").strip() if done.returncode == 0 else None


def read(data: bytes, content_type: str) -> Reading:
    """Text of a PDF or image, page by page. Never raises for bad files."""
    reading = Reading()
    if content_type == "application/pdf":
        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                reading.problem = "The PDF is password-protected, so it cannot be read here."
                return reading
            pages = list(reader.pages)
        except (PdfReadError, ValueError, OSError, KeyError, TypeError):
            reading.problem = "The PDF could not be opened (it may be damaged)."
            return reading
        if len(pages) > MAX_PAGES:
            reading.notes.append(f"Only the first {MAX_PAGES} of {len(pages)} pages were read.")
        ocr_left = MAX_OCR_PAGES
        for number, page in enumerate(pages[:MAX_PAGES], start=1):
            try:
                text = (page.extract_text() or "").strip()
            except Exception:  # pypdf can fail on odd pages; the rest still count
                text = ""
            if text:
                reading.pages.append(Page(number, text))
                continue
            # No text layer: a scanned page. Try local OCR on its images.
            ocr_text = None
            if ocr_left > 0 and ocr_available():
                ocr_left -= 1
                try:
                    images = list(page.images)
                except Exception:
                    images = []
                parts = [t for t in (_ocr(img.data, Path(img.name).suffix or ".png") for img in images[:3]) if t]
                ocr_text = "\n".join(parts) or None
            if ocr_text:
                reading.pages.append(Page(number, ocr_text, ocr=True))
            else:
                reading.unreadable_pages.append(number)
    elif content_type.startswith("image/"):
        suffix = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(content_type, ".png")
        text = _ocr(data, suffix) if ocr_available() else None
        if text:
            reading.pages.append(Page(1, text, ocr=True))
        else:
            reading.unreadable_pages.append(1)
    else:
        reading.problem = "This file type cannot be read here."
        return reading
    if reading.unreadable_pages:
        pages = ", ".join(map(str, reading.unreadable_pages))
        reading.notes.append(
            f"Page(s) {pages} are scanned images. "
            + ("Text recognition could not read them." if ocr_available() else "Text recognition (OCR) is not installed on this server, so they were not read.")
        )
    if any(p.ocr for p in reading.pages):
        reading.notes.append("Some text was read by OCR and may contain recognition errors: check values against the original.")
    if not reading.pages and not reading.problem:
        reading.problem = "No readable text was found in this document."
    return reading


# ---- laboratory rows ------------------------------------------------------------------------

_NUM = r"\d+(?:[.,]\d+)?"
_ROW = re.compile(
    rf"""^\s*
    (?P<test>[A-Za-z][A-Za-z0-9 ().,/%+'-]{{1,60}}?)          # test name
    \s*[:\s]\s*
    (?P<value>[<>]?\s?{_NUM})                                 # result
    \s*(?P<unit>(?:[a-zA-Zµμ%/^0-9.*]+(?:/[a-zA-Zµμ0-9.^]+)?)(?<![.,]))?  # unit (optional)
    (?:\s*[\(\[]?\s*(?P<range>{_NUM}\s*[-–]\s*{_NUM}|[<>≤≥]=?\s*{_NUM})\s*[\)\]]?)?  # reference range
    \s*(?P<flag>\bH\b|\bL\b|\bHigh\b|\bLow\b|\bHIGH\b|\bLOW\b|\bAbnormal\b|\*)?
    \s*$""",
    re.VERBOSE,
)
_SKIP = re.compile(r"^(page|date|age|dob|mrn|id|phone|tel|fax|patient|name|sex|gender|ref|report|lab|collected|received|printed)\b", re.I)
_DATE = re.compile(
    r"(?i)\b(collect(?:ed|ion)(?: date)?|sample date|report date|reported|date of (?:test|report))\s*[:\-]?\s*"
    r"([0-9]{1,4}[/.\-][0-9]{1,2}[/.\-][0-9]{1,4}|[0-9]{1,2}\s+[A-Za-z]{3,9}\s+[0-9]{4}|[A-Za-z]{3,9}\s+[0-9]{1,2},?\s+[0-9]{4})"
)
_LAB = re.compile(r"(?im)^\s*(?:laboratory|lab name|lab|performed at)\s*[:\-]\s*(.{3,80})$")


def _number(text: str) -> float | None:
    try:
        return float(text.replace(",", ".").lstrip("<>≤≥= ").strip())
    except ValueError:
        return None


def _judge(value: str, ref: str | None) -> str | None:
    """'high' / 'low' only against the range printed on the report."""
    if not ref or value.strip()[:1] in "<>":
        return None
    number = _number(value)
    if number is None:
        return None
    if m := re.fullmatch(rf"\s*({_NUM})\s*[-–]\s*({_NUM})\s*", ref):
        low, high = _number(m.group(1)), _number(m.group(2))
        if low is not None and high is not None and low <= high:
            return "low" if number < low else "high" if number > high else None
        return None
    if m := re.fullmatch(rf"\s*([<>≤≥])=?\s*({_NUM})\s*", ref):
        limit = _number(m.group(2))
        if limit is None:
            return None
        if m.group(1) in "<≤":
            return "high" if number > limit else None
        return "low" if number < limit else None
    return None


def measurements(reading: Reading) -> list[Measurement]:
    found: list[Measurement] = []
    seen: set[tuple[str, str, int]] = set()
    for page in reading.pages:
        for line in page.text.splitlines():
            line = line.strip()
            if len(line) < 4 or _SKIP.match(line):
                continue
            m = _ROW.match(line)
            if not m:
                continue
            test = re.sub(r"\s+", " ", m.group("test")).strip(" :-")
            if len(test) < 2 or test.lower() in ("total", "result", "value"):
                continue
            value = m.group("value").replace(" ", "")
            unit = m.group("unit") or None
            ref = (m.group("range") or "").replace(" ", "") or None
            key = (test.lower(), value, page.number)
            if key in seen:
                continue
            seen.add(key)
            flag = m.group("flag")
            found.append(Measurement(test, value, unit, ref, flag, _judge(value, ref), page.number))
    return found


def report_date(reading: Reading) -> str | None:
    """The collection/report date exactly as printed, if the report states one."""
    m = _DATE.search(reading.text)
    return m.group(2) if m else None


def laboratory(reading: Reading) -> str | None:
    m = _LAB.search(reading.text)
    return m.group(1).strip() if m else None


# ---- general education (fixed text, never about this patient) --------------------------------

GLOSSARY = {
    "hemoglobin": "Hemoglobin carries oxygen in red blood cells.",
    "haemoglobin": "Hemoglobin carries oxygen in red blood cells.",
    "hb": "Hemoglobin carries oxygen in red blood cells.",
    "hematocrit": "Hematocrit is the share of blood volume made up of red blood cells.",
    "rbc": "Red blood cell count: the number of cells that carry oxygen.",
    "wbc": "White blood cell count: cells that fight infection.",
    "white blood cell": "White blood cells fight infection.",
    "platelet": "Platelets help blood clot.",
    "mcv": "MCV is the average size of red blood cells.",
    "glucose": "Glucose is the sugar level in the blood.",
    "hba1c": "HbA1c reflects average blood sugar over about the last three months.",
    "cholesterol": "Total cholesterol is a blood fat measured to assess heart and vessel health.",
    "ldl": "LDL is often called 'bad' cholesterol.",
    "hdl": "HDL is often called 'good' cholesterol.",
    "triglyceride": "Triglycerides are a type of fat in the blood.",
    "creatinine": "Creatinine is a waste product used to check kidney function.",
    "urea": "Urea is a waste product used to check kidney function.",
    "egfr": "eGFR estimates how well the kidneys filter blood.",
    "alt": "ALT is a liver enzyme.",
    "ast": "AST is an enzyme found in the liver and muscles.",
    "bilirubin": "Bilirubin is a pigment processed by the liver.",
    "tsh": "TSH is a hormone that controls the thyroid gland.",
    "t4": "T4 is a thyroid hormone.",
    "vitamin d": "Vitamin D helps keep bones healthy.",
    "vitamin b12": "Vitamin B12 is needed for nerves and red blood cells.",
    "ferritin": "Ferritin reflects the body's iron stores.",
    "sodium": "Sodium is an electrolyte that helps control fluid balance.",
    "potassium": "Potassium is an electrolyte important for nerves and muscles.",
    "calcium": "Calcium is a mineral important for bones, muscles and nerves.",
    "crp": "CRP is a marker of inflammation.",
    "uric acid": "Uric acid is a waste product; high levels can be linked to gout.",
}


def explain(test: str) -> str | None:
    name = test.lower()
    for key, text in GLOSSARY.items():
        if re.search(rf"\b{re.escape(key)}s?\b", name):  # also plurals: "Platelets", "Triglycerides"
            return text
    return None
