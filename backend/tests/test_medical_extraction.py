"""Golden fixtures for medical document extraction (D102): the four synthetic
PDFs in tests/fixtures/medical, read entirely on the server (no AI)."""

from pathlib import Path

import pytest

from app.services.ai.medical_reports import analyse, canonical, read, same_unit

FIXTURES = Path(__file__).parent / "fixtures" / "medical"


def extract(name):
    return analyse(read((FIXTURES / name).read_bytes(), "application/pdf"))


def values(x):
    return {m.test: (m.value, m.unit) for m in x.measurements}


def test_diabetes_clinical_case():
    x = extract("clinical_case_type2_diabetes_sample.pdf")
    assert x.status == "ok" and x.synthetic and x.printed_date == "30 Oct 2026"
    assert len(x.measurements) == 10
    assert values(x) == {
        "Fasting plasma glucose": ("168", "mg/dL"),
        "HbA1c": ("8.2", "%"),
        "Random plasma glucose": ("224", "mg/dL"),
        "Serum creatinine": ("1.02", "mg/dL"),
        "eGFR (CKD-EPI 2021)": ("88", "mL/min/1.73 m2"),
        "Urine albumin/creatinine ratio": ("42", "mg/g"),
        "Total cholesterol": ("218", "mg/dL"),
        "LDL cholesterol": ("142", "mg/dL"),
        "HDL cholesterol": ("38", "mg/dL"),
        "Triglycerides": ("190", "mg/dL"),
    }
    by = {m.test: m for m in x.measurements}
    # Thresholds stay reference text: never test names.
    assert by["Total cholesterol"].reference_range == "Desirable <200 mg/dL"
    assert by["LDL cholesterol"].reference_range == "Optimal <100 mg/dL"
    assert not any(m.test.split()[0].lower() in ("desirable", "optimal", "normal") for m in x.measurements)
    assert by["HDL cholesterol"].out_of_range == "low" and by["Serum creatinine"].out_of_range is None  # the report's flags
    assert [(c.name, c.role) for c in x.conditions] == [
        ("Type 2 diabetes mellitus", "primary"), ("Moderately increased albuminuria", "associated"), ("Dyslipidemia", "associated")]
    assert "Chronic kidney disease" not in [c.name for c in x.conditions]  # "does not establish chronic kidney disease"
    assert [s.name for s in x.symptoms] == ["Increased thirst", "Frequent urination", "Fatigue", "Blurred vision"]
    assert {s.kind for s in x.sections} >= {"interpretation", "follow_up"}


def test_iron_deficiency_anemia_report():
    x = extract("sample_iron_deficiency_anemia_report.pdf")
    assert len(x.measurements) == 9 and x.printed_date == "30 October 2026"
    assert values(x) == {
        "Hemoglobin (Hb)": ("10.2", "g/dL"), "Hematocrit (Hct)": ("33", "%"), "MCV": ("72", "fL"), "MCH": ("22", "pg"),
        "White blood cells": ("6.5", "x10^3/uL"), "Platelets": ("380", "x10^3/uL"), "Ferritin": ("9", "ng/mL"),
        "Serum iron": ("32", "ug/dL"), "Transferrin saturation": ("8", "%"),
    }
    assert [m.test for m in x.measurements if m.out_of_range] == [
        "Hemoglobin (Hb)", "Hematocrit (Hct)", "MCV", "MCH", "Ferritin", "Serum iron", "Transferrin saturation"]
    assert [c.name for c in x.conditions] == ["Iron-deficiency anemia"]
    assert [s.name for s in x.symptoms] == ["Fatigue", "Pallor", "Dizziness", "Shortness of breath on exertion"]


def test_type2_diabetes_medical_report():
    x = extract("sample_type2_diabetes_medical_report.pdf")
    assert len(x.measurements) == 9 and x.printed_date == "29 October 2026"
    assert values(x) == {
        "Fasting plasma glucose": ("168", "mg/dL"), "HbA1c": ("8.2", "%"), "Random plasma glucose": ("224", "mg/dL"),
        "Creatinine": ("0.94", "mg/dL"), "eGFR": ("96", "mL/min/1.73 m2"), "Total cholesterol": ("218", "mg/dL"),
        "LDL cholesterol": ("139", "mg/dL"), "HDL cholesterol": ("39", "mg/dL"), "Triglycerides": ("186", "mg/dL"),
    }
    by = {m.test: m for m in x.measurements}
    assert by["HbA1c"].out_of_range == "high"  # at/above the printed diabetes threshold
    assert by["HDL cholesterol"].out_of_range is None  # vague reference text: not judged
    assert by["Random plasma glucose"].out_of_range is None  # conditional threshold: not judged
    assert [c.name for c in x.conditions] == ["Type 2 diabetes mellitus"]
    assert [s.name for s in x.symptoms] == ["Increased thirst", "Frequent urination", "Fatigue", "Blurred vision"]


def test_mock_cbc():
    x = extract("mock_cbc_test_report.pdf")
    assert x.document_kind == "Complete blood count (CBC)" and x.printed_date == "2026-01-15"
    # The PDF has 14 result rows; the page-2 "Expected extracted value" table is not counted again.
    assert len(x.measurements) == 14
    v = values(x)
    assert v["White blood cell count (WBC)"][0] == "6.4" and v["Red blood cell count (RBC)"] == ("4.75", "×10¹²/L")
    assert v["Hemoglobin (HGB)"] == ("14.2", "g/dL") and v["Hematocrit (HCT)"] == ("42.1", "%")
    assert v["Mean corpuscular volume (MCV)"] == ("88.6", "fL") and v["Mean corpuscular hemoglobin (MCH)"] == ("29.9", "pg")
    assert v["Mean corpuscular Hgb concentration (MCHC)"] == ("33.7", "g/dL") and v["Red cell distribution width (RDW-CV)"] == ("13.1", "%")
    assert v["Platelet count (PLT)"][0] == "254"
    assert [v[t][0] for t in ("Neutrophils", "Lymphocytes", "Monocytes", "Eosinophils", "Basophils")] == ["58", "32", "6", "3", "1"]
    # The PDF's font lost the superscript in ×10⁹/L: shown as "?" with a warning, never guessed.
    assert v["White blood cell count (WBC)"][1] == "×10?/L" and any("superscript" in w for w in x.warnings)
    assert x.conditions == [] and x.symptoms == []
    assert not any(m.out_of_range for m in x.measurements)


@pytest.mark.parametrize(("a", "b"), [("Serum creatinine", "Creatinine"), ("Hemoglobin (Hb)", "Hemoglobin (HGB)"),
                                      ("eGFR (CKD-EPI 2021)", "eGFR"), ("Platelets", "Platelet count (PLT)")])
def test_the_same_test_under_different_names(a, b):
    assert canonical(a) == canonical(b)


def test_different_tests_and_units_are_not_mixed():
    assert canonical("Fasting plasma glucose") != canonical("Random plasma glucose")
    assert canonical("HDL cholesterol") != canonical("LDL cholesterol") != canonical("Total cholesterol")
    assert same_unit("mg/dL", "mg/dL") and not same_unit("x10^3/uL", "×10?/L") and not same_unit("mg/dL", "mmol/L")


def test_bad_files_are_reported_not_guessed():
    assert analyse(read(b"not a pdf", "application/pdf")).problem
    assert analyse(read(b"", "application/zip")).problem == "This file type cannot be read here."
