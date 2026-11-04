"""Local, deterministic reading of patient medical documents (D101, v2 D102).

Runs entirely on this server. Pipeline:

1. read(): text page by page. PDFs use pypdf's layout mode, which keeps the
   column positions of tables; scanned pages and images use local OCR
   (the Tesseract command) when it is installed.
2. analyse(): a typed extraction (MedicalExtraction):
   - measurements from results tables, found by their header row ("Test ...
     Result ... Reference ... Flag") and read cell by cell using the header's
     column positions, so a test name, its value, unit, reference text and
     flag stay together. Reference text such as "Desirable <200 mg/dL" is
     kept as the reference, never read as a test. Without a recognisable
     table, a conservative one-line fallback is used (lower confidence);
   - conditions from the report's own interpretation sentences, with the
     evidence type and the source sentence; negated mentions ("does not
     establish...") and family history are left out;
   - symptoms from the report's symptom / overview text (negated ones out);
   - the narrative sections (interpretation, follow-up) with page numbers.

Nothing is invented: a value is "high"/"low" only from the report's own
flag, or from a plain printed range; dates are kept exactly as printed.
Uploaded files are data only: parsed, never executed, never instructions.
"""

import io
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

logger = logging.getLogger(__name__)

# Bump when the extraction changes: cached results of older versions are never reused.
EXTRACTION_VERSION = "2"
MAX_PAGES = 50
MAX_TEXT_CHARS = 60_000
MAX_OCR_PAGES = 5
OCR_TIMEOUT_SECONDS = 20


# ---- 1. reading ------------------------------------------------------------------------------


@dataclass
class Page:
    number: int
    text: str
    ocr: bool = False


@dataclass
class Reading:
    pages: list[Page] = field(default_factory=list)
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
            done = subprocess.run([binary, str(source), "stdout", "--psm", "6"], capture_output=True,
                                  timeout=OCR_TIMEOUT_SECONDS, check=False)
        except (subprocess.TimeoutExpired, OSError):
            return None
    return done.stdout.decode("utf-8", "replace").strip() if done.returncode == 0 else None


def _page_text(page) -> str:
    """Layout mode keeps table columns; plain mode is the fallback."""
    for mode in ("layout", "plain"):
        try:
            text = page.extract_text(extraction_mode=mode) if mode == "layout" else page.extract_text()
        except Exception:  # pypdf can fail on odd pages; try the other mode
            continue
        text = "\n".join(line.rstrip() for line in (text or "").splitlines())
        if text.strip():
            return text
    return ""


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
            text = _page_text(page)
            if text.strip():
                reading.pages.append(Page(number, text))
                continue
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


# ---- 2. typed extraction ----------------------------------------------------------------------


@dataclass
class Measurement:
    test: str
    value: str
    unit: str | None
    reference_range: str | None
    report_flag: str | None
    # "high" / "low": from the report's flag, or a plain printed range. None otherwise.
    out_of_range: str | None
    page: int
    source_text: str = ""
    confidence: str = "high"

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Condition:
    name: str
    # reported_assessment: stated by the report (e.g. "Primary condition: ...", "consistent with ...").
    evidence_type: str
    role: str  # primary | associated
    source_text: str
    page: int


@dataclass
class Symptom:
    name: str
    source_text: str
    page: int


@dataclass
class Section:
    heading: str
    kind: str  # interpretation | follow_up | symptoms | other
    text: str
    page: int


@dataclass
class MedicalExtraction:
    version: str
    status: str  # ok | partial | no_measurements | failed
    document_kind: str
    heading: str | None
    printed_date: str | None
    laboratory: str | None
    synthetic: bool
    measurements: list[Measurement] = field(default_factory=list)
    conditions: list[Condition] = field(default_factory=list)
    symptoms: list[Symptom] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    problem: str | None = None
    pages: list[int] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


_NUM = r"\d+(?:[.,]\d+)?"
_CELL_SPLIT = re.compile(r"\S+(?: \S+)*")
_RESULT_HEADER = re.compile(r"\bresult", re.I)
# Words that qualify a reference value; never a test name.
QUALIFIERS = {
    "desirable", "optimal", "normal", "typical", "approx", "approx.", "reference", "target", "threshold", "borderline",
    "diabetes", "low", "high", "within", "generally", "illustrative", "range", "interpret", "goal",
}


def _cells(line: str) -> list[tuple[int, str]]:
    """Cells of a layout line: runs of text separated by 2+ spaces, with their start column."""
    cells, pos = [], 0
    for chunk in re.split(r"(\s{2,})", line):
        if chunk and not chunk.isspace():
            cells.append((pos, chunk.strip()))
        pos += len(chunk)
    return cells


def _column_kind(label: str) -> str | None:
    label = label.lower()
    if "test" in label or label in ("parameter", "investigation", "analyte"):
        return "test"
    if "result" in label or label == "value":
        return "result"
    if "unit" in label:
        return "unit"
    if "reference" in label or "range" in label or "interval" in label or "interpretation" in label:
        return "reference"
    if "flag" in label or "status" in label:
        return "flag"
    return None


def _header(line: str) -> list[tuple[int, str]] | None:
    """Column starts of a results-table header row, or None."""
    cells = _cells(line)
    kinds = [(start, _column_kind(label)) for start, label in cells]
    found = {k for _, k in kinds if k}
    if {"test", "result"} <= found and len(cells) >= 2 and _RESULT_HEADER.search(line):
        return [(start, kind) for start, kind in kinds if kind]
    return None


def _assign(cells: list[tuple[int, str]], columns: list[tuple[int, str]]) -> dict[str, str]:
    """Each cell goes to the nearest header column (layout positions drift a few characters)."""
    row: dict[str, str] = {}
    for start, text in cells:
        kind = min(columns, key=lambda c: abs(c[0] - start))[1]
        row[kind] = f"{row[kind]} {text}" if kind in row else text
    return row


def _split_value(result: str) -> tuple[str, str | None] | None:
    m = re.match(rf"^([<>≤≥]?=?\s?{_NUM})\s*(.*)$", result.strip())
    if not m:
        return None
    unit = m.group(2).strip() or None
    return m.group(1).replace(" ", ""), unit


def _clean_unit(unit: str | None, warnings: list[str]) -> str | None:
    if unit and "■" in unit:
        # A superscript the PDF's font could not encode (e.g. ×10⁹/L): shown as "?" rather than guessed.
        warnings.append("A superscript in a unit could not be read from the PDF and is shown as '?'.")
        unit = unit.replace("■", "?")
    return unit


def _flag(raw: str | None) -> str | None:
    if not raw:
        return None
    low = raw.lower()
    if "high" in low or low in ("h", "hi", "↑"):
        return "high"
    if "low" in low or low in ("l", "lo", "↓"):
        return "low"
    return None


def _plain_range(reference: str | None) -> tuple[float, float] | None:
    """A plain "a-b" range (optionally "Normal:"/"Typical ..." and units); never a threshold."""
    if not reference:
        return None
    text = re.sub(r"^(normal|typical(?: adult)?(?: male| female)?(?: range)?|reference|approx\.?)\s*:?\s*", "", reference.strip(), flags=re.I)
    m = re.fullmatch(rf"~?\s*({_NUM})\s*[-–]\s*({_NUM})\s*[^\d<>=;]*", text)
    if not m:
        return None
    low, high = float(m.group(1).replace(",", ".")), float(m.group(2).replace(",", "."))
    return (low, high) if low <= high else None


# A single printed target or threshold and nothing else: "Desirable: <200 mg/dL",
# "Normal <150 mg/dL", "Diabetes threshold: >=6.5%". Conditional text ("with
# classic symptoms ...") or vague wording ("Low in many frameworks") is never judged.
_THRESHOLD = re.compile(
    rf"^(?P<label>normal|desirable|optimal|reference|target|typical|(?:diabetes )?threshold|diabetes)?\s*:?\s*"
    rf"(?P<op><=|>=|<|>|≤|≥)\s*(?P<limit>{_NUM})\s*[a-zA-Z%/µ0-9.^ ]{{0,20}}$",
    re.I,
)


def _judge(value: str, reference: str | None) -> str | None:
    if value[:1] in "<>≤≥" or not reference:
        return None
    number = float(value.replace(",", "."))
    bounds = _plain_range(reference)
    if bounds is not None:
        return "low" if number < bounds[0] else "high" if number > bounds[1] else None
    m = _THRESHOLD.match(reference.strip())
    if not m:
        return None
    limit = float(m.group("limit").replace(",", "."))
    label = (m.group("label") or "").lower()
    if "threshold" in label or label == "diabetes":
        # At or above a printed diagnostic threshold.
        return "high" if (number >= limit if m.group("op") in (">=", "≥") else number > limit) else None
    if m.group("op") in ("<", "<=", "≤"):
        return "high" if number > limit or (m.group("op") == "<" and number == limit) else None
    return "low" if number < limit else None


def _table_measurements(pages: list[Page], warnings: list[str]) -> tuple[list[Measurement], bool]:
    found: list[Measurement] = []
    any_header = False
    for page in pages:
        columns = None
        for line in page.text.splitlines():
            if not line.strip():
                continue
            header = _header(line)
            if header:
                columns, any_header = header, True
                continue
            if columns is None:
                continue
            row = _assign(_cells(line), columns)
            test, result = row.get("test"), row.get("result")
            parsed = _split_value(result) if result else None
            if not test or parsed is None or test.split()[0].lower().strip(":") in QUALIFIERS:
                stripped = line.strip()
                # Watermarks ("MOCK DATA - NOT REAL") inside a table are skipped; other text ends it.
                if len(stripped) <= 50 and stripped.upper() == stripped:
                    continue
                columns = None
                continue
            value, unit = parsed
            unit = _clean_unit(row.get("unit") or unit, warnings)
            reference = row.get("reference")
            raw_flag = row.get("flag")
            found.append(Measurement(
                test=test, value=value, unit=unit, reference_range=reference, report_flag=raw_flag,
                out_of_range=_flag(raw_flag) if raw_flag else _judge(value, reference),
                page=page.number, source_text=re.sub(r"\s{2,}", " | ", line.strip()), confidence="high",
            ))
    return found, any_header


# One-line fallback for documents without a recognisable table: "Hemoglobin 13.6 g/dL 13.0-17.0 L".
_ROW = re.compile(
    rf"""^\s*
    (?P<test>[A-Za-z][A-Za-z0-9 ().,/%+'-]{{1,60}}?)\s*[:\s]\s*
    (?P<value>[<>]?\s?{_NUM})
    \s*(?P<unit>(?:[a-zA-Zµμ%/^0-9.*]+(?:/[a-zA-Zµμ0-9.^]+)?)(?<![.,]))?
    (?:\s*[\(\[]?\s*(?P<range>{_NUM}\s*[-–]\s*{_NUM}|[<>≤≥]=?\s*{_NUM})\s*[\)\]]?)?
    \s*(?P<flag>\bH\b|\bL\b|\bHigh\b|\bLow\b|\bHIGH\b|\bLOW\b|\bAbnormal\b|\*)?
    \s*$""",
    re.VERBOSE,
)
_SKIP_LINE = re.compile(r"^(page|date|age|dob|mrn|id|phone|tel|fax|patient|name|sex|gender|ref|report|lab|collected|received|printed)\b", re.I)


def _fallback_measurements(pages: list[Page]) -> list[Measurement]:
    found, seen = [], set()
    for page in pages:
        for line in page.text.splitlines():
            line = re.sub(r"\s+", " ", line).strip()
            if len(line) < 4 or _SKIP_LINE.match(line):
                continue
            m = _ROW.match(line)
            if not m:
                continue
            test = m.group("test").strip(" :-")
            if len(test) < 2 or test.split()[0].lower() in QUALIFIERS or test.lower() in ("total", "result", "value"):
                continue
            value = m.group("value").replace(" ", "")
            key = (test.lower(), value, page.number)
            if key in seen:
                continue
            seen.add(key)
            ref = (m.group("range") or "").replace(" ", "") or None
            flag = m.group("flag")
            found.append(Measurement(test, value, m.group("unit") or None, ref, flag,
                                     _flag(flag) if flag else _judge(value, ref), page.number, line, "medium"))
    return found


# ---- narrative, conditions, symptoms ------------------------------------------------------------

_SECTION_KINDS = (
    ("symptoms", ("symptom", "overview", "presenting", "history of present", "reason for")),
    ("interpretation", ("interpretation", "explanation", "assessment", "what the results mean", "impression", "conclusion", "diagnosis")),
    ("follow_up", ("follow-up", "follow up", "management", "recommend", "plan", "next steps")),
    ("skip", ("reference concept", "validation", "testing note", "source", "disclaimer", "extraction test", "case information",
              "patient", "laboratory findings", "results", "cbc results", "field")),
)


def _section_kind(heading: str) -> str:
    low = heading.lower()
    for kind, words in _SECTION_KINDS:
        if any(w in low for w in words):
            return kind
    return "other"


def _is_heading(line: str, next_line: str | None) -> bool:
    text = line.strip()
    # All-capital lines are titles or watermarks ("MOCK DATA - NOT REAL"), not section headings.
    if not text or len(text) > 70 or len(text.split()) > 9 or text.endswith((".", ",", ";")) or text.upper() == text:
        return False
    if not text[0].isalpha() or not text[0].isupper() or _header(line) or ":" in text[:-1]:
        return False
    return next_line is not None and len(next_line.strip()) > len(text) * 0.8


def _sections(pages: list[Page], table_lines: set[str]) -> list[Section]:
    sections: list[Section] = []
    for page in pages:
        lines = [l for l in page.text.splitlines() if l.strip()]
        current: Section | None = None
        for i, line in enumerate(lines):
            stripped = re.sub(r"\s+", " ", line).strip()
            if stripped in table_lines or _header(line) or re.fullmatch(r"(?i).*\bpage \d+\s*", stripped) and "|" in stripped:
                current = None
                continue
            nxt = lines[i + 1] if i + 1 < len(lines) else None
            if _is_heading(line, nxt):
                current = Section(stripped, _section_kind(stripped), "", page.number)
                sections.append(current)
                continue
            if current is not None and len(_cells(line)) <= 1:
                current.text = f"{current.text} {stripped}".strip()
    return [s for s in sections if s.text and s.kind != "skip"]


CONDITIONS = (
    ("Type 2 diabetes mellitus", r"type\s*(?:2|ii)\s+diabetes(?:\s+mellitus)?"),
    ("Type 1 diabetes mellitus", r"type\s*(?:1|i)\s+diabetes(?:\s+mellitus)?"),
    ("Prediabetes", r"pre-?diabetes"),
    ("Iron-deficiency anemia", r"iron[- ]deficiency an(?:a)?emia"),
    ("Anemia", r"\ban(?:a)?emia\b"),
    ("Dyslipidemia", r"dyslipid(?:a)?emia"),
    ("Moderately increased albuminuria", r"moderately increased albuminuria"),
    ("Albuminuria", r"\balbuminuria\b"),
    ("Chronic kidney disease", r"chronic kidney disease"),
    ("Hypertension", r"\bhypertension\b"),
    ("Hypothyroidism", r"\bhypothyroidism\b"),
    ("Hyperthyroidism", r"\bhyperthyroidism\b"),
)
# A specific name makes the general one redundant.
_GENERAL_OF = {"Anemia": "Iron-deficiency anemia", "Albuminuria": "Moderately increased albuminuria"}
_PRIMARY = re.compile(r"(?i)primary condition|likely condition|diagnosis\s*:|diagnosed with|consistent with|findings consistent")
_NEGATED = re.compile(r"(?i)does not establish|not establish|no evidence|rule[sd]? out|\bwithout\b|family history|not diagnos")
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def _sentences(sections: list[Section], kinds: tuple[str, ...]):
    for s in sections:
        if s.kind in kinds:
            for sentence in _SENTENCE.split(s.text):
                yield sentence.strip(), s.page


def _conditions(sections: list[Section]) -> list[Condition]:
    found: dict[str, Condition] = {}
    for sentence, page in _sentences(sections, ("interpretation", "symptoms", "other")):
        # Negation is judged per clause: "... falls within moderately increased albuminuria; ...
        # a single result does not establish chronic kidney disease" keeps the first, drops the second.
        clauses = re.split(r";|,\s*(?:but|although|because)\b", sentence)
        for name, pattern in CONDITIONS:
            if name in found:
                continue
            clause = next((c for c in clauses if re.search(pattern, c, re.I)), None)
            if clause is None or _NEGATED.search(clause):
                continue
            primary = bool(_PRIMARY.search(sentence)) and not any(c.role == "primary" for c in found.values())
            found[name] = Condition(name, "reported_assessment", "primary" if primary else "associated", sentence, page)
    for general, specific in _GENERAL_OF.items():
        if general in found and specific in found:
            del found[general]
    ordered = sorted(found.values(), key=lambda c: c.role != "primary")
    if ordered and ordered[0].role != "primary":
        ordered[0].role = "primary"
    return ordered


SYMPTOMS = (
    ("Increased thirst", r"increased thirst|excessive thirst|polydipsia"),
    ("Frequent urination", r"frequent urination|polyuria"),
    ("Fatigue", r"fatigue|tiredness|feeling tired|\btired\b"),
    ("Blurred vision", r"blurr(?:ed|y) vision"),
    ("Pallor", r"pallor|looking pale|\bpale\b"),
    ("Dizziness", r"dizziness|\bdizzy\b"),
    ("Shortness of breath", r"short(?:ness)? of breath|breathless"),
    ("Weight loss", r"weight loss"),
    ("Headache", r"headache"),
    ("Chest pain", r"chest pain"),
    ("Palpitations", r"palpitations"),
    ("Nausea", r"nausea"),
)


def _symptoms(sections: list[Section], pages: list[Page]) -> list[Symptom]:
    found: dict[str, Symptom] = {}
    sentences = list(_sentences(sections, ("symptoms",)))
    # "Reason for testing: Tiredness and dizziness" sits in the header block.
    for page in pages:
        for line in page.text.splitlines():
            m = re.search(r"(?i)reason for (?:testing|visit|referral)\s*:\s*(.+?)(?:\s{2,}|$)", line)
            if m:
                sentences.append((m.group(1).strip(), page.number))
    for sentence, page in sentences:
        if re.match(r"(?i)no\b", sentence) or re.search(r"(?i)\bdenies\b", sentence):
            continue
        for name, pattern in SYMPTOMS:
            if name not in found and re.search(pattern, sentence, re.I):
                label = name
                if name == "Shortness of breath" and re.search(r"(?i)exercis|exertion", sentence):
                    label = "Shortness of breath on exertion"
                found[name] = Symptom(label, sentence, page)
    return list(found.values())


_DATE = re.compile(
    r"(?i)\b(?:collect(?:ed|ion)(?: date)?|sample date|report date|reported|date of (?:test|report))\s*[:\-]?\s+"
    r"(\d{4}-\d{2}-\d{2}|\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})"
)
_LAB = re.compile(r"(?im)^\s*(?:laboratory|lab name|lab|performed at)\s*[:\-]\s*(.{3,80})$")
_SYNTHETIC = re.compile(
    r"(?i)\b(synthetic|fictional|fictitious|mock report|mock data|simulated|not a real (?:medical|lab)|"
    r"not valid for (?:clinical|medical) use|demo document|for software testing)\b"
)


def report_date(reading: Reading) -> str | None:
    """The collection/report date exactly as printed, if the report states one."""
    m = _DATE.search(reading.text)
    return m.group(1) if m else None


def laboratory(reading: Reading) -> str | None:
    m = _LAB.search(reading.text)
    return m.group(1).strip() if m else None


def measurements(reading: Reading) -> list[Measurement]:
    return analyse(reading).measurements


def analyse(reading: Reading) -> MedicalExtraction:
    text = reading.text
    heading = next((re.sub(r"\s+", " ", l).strip() for p in reading.pages for l in p.text.splitlines() if l.strip()), None)
    kind = "Complete blood count (CBC)" if re.search(r"(?i)complete blood count|\(cbc\)", text) else (
        "Laboratory report" if re.search(r"(?i)laborator|test\s+.*result", text) else "Medical document")
    extraction = MedicalExtraction(
        version=EXTRACTION_VERSION, status="failed", document_kind=kind, heading=heading,
        printed_date=report_date(reading), laboratory=laboratory(reading), synthetic=bool(_SYNTHETIC.search(text)),
        warnings=list(reading.notes), problem=reading.problem, pages=[p.number for p in reading.pages],
    )
    if reading.problem or not reading.pages:
        return extraction
    warnings: list[str] = []
    rows, had_table = _table_measurements(reading.pages, warnings)
    if not rows:
        rows = _fallback_measurements(reading.pages)
        if had_table:
            warnings.append("A results table was found, but its rows could not be read reliably; values below were read line by line.")
    extraction.measurements = rows
    extraction.warnings += list(dict.fromkeys(warnings))
    table_lines = {re.sub(r"\s+", " ", m.source_text.replace(" | ", "  ")).strip() for m in rows}
    extraction.sections = _sections(reading.pages, table_lines)
    extraction.conditions = _conditions(extraction.sections)
    extraction.symptoms = _symptoms(extraction.sections, reading.pages)
    if rows:
        extraction.status = "ok" if all(m.confidence == "high" for m in rows) and not reading.unreadable_pages else "partial"
    else:
        extraction.status = "no_measurements"
    return extraction


# ---- comparing and explaining ---------------------------------------------------------------------

_ALIASES = {
    "hemoglobin": ("hemoglobin", "haemoglobin", "hgb", "hb"),
    "hematocrit": ("hematocrit", "haematocrit", "hct"),
    "wbc": ("white blood cell", "white blood cells", "wbc", "leukocyte"),
    "rbc": ("red blood cell count", "red blood cells", "rbc"),
    "platelets": ("platelet", "platelets", "plt", "platelet count"),
    "mcv": ("mcv", "mean corpuscular volume"),
    "mchc": ("mchc", "mean corpuscular hgb concentration", "mean corpuscular hemoglobin concentration"),
    "mch": ("mch", "mean corpuscular hemoglobin"),
    "rdw": ("rdw", "rdw-cv", "red cell distribution width"),
    "fasting glucose": ("fasting plasma glucose", "fasting glucose", "fasting blood glucose"),
    "random glucose": ("random plasma glucose", "random glucose", "random blood glucose"),
    "hba1c": ("hba1c", "glycated hemoglobin", "a1c"),
    "creatinine": ("creatinine", "serum creatinine"),
    "egfr": ("egfr",),
    "uacr": ("urine albumin/creatinine ratio", "albumin/creatinine ratio", "uacr", "acr"),
    "total cholesterol": ("total cholesterol", "cholesterol"),
    "ldl": ("ldl cholesterol", "ldl"),
    "hdl": ("hdl cholesterol", "hdl"),
    "triglycerides": ("triglycerides", "triglyceride"),
    "ferritin": ("ferritin",),
    "serum iron": ("serum iron", "iron"),
    "transferrin saturation": ("transferrin saturation", "tsat"),
}


def canonical(test: str) -> str:
    """The same test under different printed names ("Serum creatinine" = "Creatinine")."""
    plain = re.sub(r"\(.*?\)", " ", test.lower())
    plain = re.sub(r"\s+", " ", plain).strip()
    codes = re.findall(r"\(([^)]+)\)", test.lower())
    for key, names in _ALIASES.items():
        if plain in names or any(c.strip() in names for c in codes):
            return key
    return plain


def same_unit(a: str | None, b: str | None) -> bool:
    norm = lambda u: (u or "").lower().replace(" ", "").replace("µ", "u").replace("μ", "u").replace("×", "x")
    return "?" not in (a or "") + (b or "") and norm(a) == norm(b)


GLOSSARY = {
    "hemoglobin": "Hemoglobin carries oxygen in red blood cells.",
    "haemoglobin": "Hemoglobin carries oxygen in red blood cells.",
    "hematocrit": "Hematocrit is the share of blood volume made up of red blood cells.",
    "red blood cell": "Red blood cells carry oxygen around the body.",
    "rbc": "Red blood cell count: the number of cells that carry oxygen.",
    "wbc": "White blood cell count: cells that fight infection.",
    "white blood cell": "White blood cells fight infection.",
    "platelet": "Platelets help blood clot.",
    "mchc": "MCHC is the average concentration of hemoglobin in red blood cells.",
    "mcv": "MCV is the average size of red blood cells.",
    "mch": "MCH is the average amount of hemoglobin in each red blood cell.",
    "rdw": "RDW shows how much red blood cells vary in size.",
    "neutrophil": "Neutrophils are the most common white blood cells and fight bacterial infection.",
    "lymphocyte": "Lymphocytes are white blood cells of the immune system.",
    "monocyte": "Monocytes are white blood cells that clear germs and debris.",
    "eosinophil": "Eosinophils are white blood cells involved in allergy and parasite defence.",
    "basophil": "Basophils are white blood cells involved in allergic reactions.",
    "glucose": "Glucose is the sugar level in the blood.",
    "hba1c": "HbA1c reflects average blood sugar over about the last three months.",
    "cholesterol": "Cholesterol is a blood fat measured to assess heart and blood-vessel health.",
    "ldl": "LDL is often called 'bad' cholesterol.",
    "hdl": "HDL is often called 'good' cholesterol.",
    "triglyceride": "Triglycerides are a type of fat in the blood.",
    "albumin/creatinine": "The urine albumin/creatinine ratio checks for protein leaking through the kidneys.",
    "creatinine": "Creatinine is a waste product used to check kidney function.",
    "urea": "Urea is a waste product used to check kidney function.",
    "egfr": "eGFR estimates how well the kidneys filter blood.",
    "ferritin": "Ferritin reflects the body's iron stores.",
    "transferrin saturation": "Transferrin saturation shows how much iron is available in the blood.",
    "iron": "Serum iron is the amount of iron circulating in the blood.",
    "alt": "ALT is a liver enzyme.",
    "ast": "AST is an enzyme found in the liver and muscles.",
    "bilirubin": "Bilirubin is a pigment processed by the liver.",
    "tsh": "TSH is a hormone that controls the thyroid gland.",
    "vitamin d": "Vitamin D helps keep bones healthy.",
    "vitamin b12": "Vitamin B12 is needed for nerves and red blood cells.",
    "sodium": "Sodium is an electrolyte that helps control fluid balance.",
    "potassium": "Potassium is an electrolyte important for nerves and muscles.",
    "calcium": "Calcium is a mineral important for bones, muscles and nerves.",
    "crp": "CRP is a marker of inflammation.",
}

CONDITION_INFO = {
    "Type 2 diabetes mellitus": "A long-term condition in which the body does not use insulin properly, so blood sugar stays too high. "
    "It is managed with lifestyle changes and, when a clinician decides, medicines; regular HbA1c checks track control.",
    "Type 1 diabetes mellitus": "A condition in which the body makes little or no insulin, so insulin treatment is needed.",
    "Prediabetes": "Blood sugar higher than normal but below the diabetes range; lifestyle changes can lower the risk of diabetes.",
    "Iron-deficiency anemia": "Anemia caused by too little iron: the body cannot make enough hemoglobin, which can cause tiredness, "
    "pale skin and shortness of breath. Finding the cause of the low iron (diet, blood loss) is an important part of care.",
    "Anemia": "A lower than expected amount of hemoglobin or red blood cells, so less oxygen reaches the body.",
    "Dyslipidemia": "Abnormal blood fat levels (for example high LDL or triglycerides, or low HDL), which raise heart and blood-vessel risk.",
    "Moderately increased albuminuria": "A moderate amount of albumin (a protein) in the urine, an early sign the kidneys may be affected; "
    "it is usually re-tested to confirm it persists.",
    "Albuminuria": "Albumin (a protein) in the urine, a possible sign of kidney involvement.",
    "Chronic kidney disease": "Long-lasting reduced kidney function or kidney damage.",
    "Hypertension": "Blood pressure that is persistently higher than recommended.",
    "Hypothyroidism": "An underactive thyroid gland.",
    "Hyperthyroidism": "An overactive thyroid gland.",
}


def explain(test: str) -> str | None:
    name = test.lower()
    for key, text in GLOSSARY.items():
        if re.search(rf"\b{re.escape(key)}s?\b", name):  # also plurals: "Platelets", "Triglycerides"
            return text
    return None
