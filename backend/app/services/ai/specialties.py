"""Everyday words for medical specialties, for the assistant's doctor search.

The model is asked to pass the user's own words; the directory, however,
stores specialties as written by the clinic ("Cardiologist", "Cardiology").
"Heart doctor" shares no text with either, so a plain substring search finds
nothing. `search_terms` turns lay words, adjectives and near-misspellings into
the stems a specialty name contains ("cardi" matches Cardiology and
Cardiologist alike). It only widens a search that already failed on the
user's words: every result still comes from the database.
"""

import difflib
import re

# Stem the directory text contains -> words people use for it.
SPECIALTIES: dict[str, tuple[str, ...]] = {
    "cardi": ("heart", "cardiac", "cardio", "cardiology", "cardiologist", "chest pain", "blood pressure", "hypertension", "palpitations"),
    "dermat": ("skin", "dermatology", "dermatologist", "acne", "rash", "eczema", "hair", "nail", "derm"),
    "pediatr": ("child", "children", "childrens", "kid", "kids", "baby", "babies", "infant", "paediatric", "paediatrician", "pediatric", "pediatrician", "peds"),
    "neuro": ("brain", "nerve", "nerves", "neurology", "neurologist", "migraine", "seizure", "epilepsy", "stroke", "headache"),
    "ortho": ("bone", "bones", "joint", "joints", "fracture", "spine", "back pain", "knee", "orthopedic", "orthopaedic", "orthopedics", "sports injury"),
    "ophthalm": ("eye", "eyes", "vision", "sight", "ophthalmology", "ophthalmologist", "eye doctor"),
    # Not "ent": as a substring it also matches Dentistry and Gastroenterology.
    "otolaryng": ("ear", "nose", "throat", "ent", "sinus", "otolaryngology", "ear nose throat"),
    "gyn": ("women", "womens", "woman", "pregnancy", "pregnant", "gynecology", "gynaecology", "gynecologist", "obgyn", "ob-gyn", "obstetrics", "period"),
    "obstet": ("pregnancy", "pregnant", "obstetrics", "obstetrician", "delivery"),
    "psych": ("mental", "mental health", "depression", "anxiety", "psychiatry", "psychiatrist", "psychology", "psychologist", "stress", "therapy"),
    "gastro": ("stomach", "digestion", "digestive", "gut", "liver", "bowel", "gastroenterology", "gastroenterologist", "acidity"),
    "urolog": ("urine", "urinary", "bladder", "kidney stone", "prostate", "urology", "urologist"),
    "nephro": ("kidney", "kidneys", "renal", "nephrology", "nephrologist", "dialysis"),
    "pulmo": ("lung", "lungs", "breathing", "asthma", "chest", "pulmonology", "pulmonologist", "respiratory", "cough"),
    "endocrin": ("diabetes", "thyroid", "hormone", "hormones", "sugar", "endocrinology", "endocrinologist"),
    "oncolog": ("cancer", "tumor", "tumour", "oncology", "oncologist", "chemotherapy"),
    "dent": ("tooth", "teeth", "dental", "dentist", "gum", "gums"),
    "general": ("general", "family", "family doctor", "gp", "physician", "checkup", "check-up", "fever", "flu", "cold"),
    "internal": ("internal medicine", "internist"),
    "rheumat": ("arthritis", "rheumatology", "rheumatologist", "lupus"),
    "allerg": ("allergy", "allergies", "allergist", "immunology"),
    "surg": ("surgery", "surgeon", "operation"),
}

# Words that say "doctor" but no specialty; dropped before matching.
FILLER = {
    "a", "an", "the", "me", "my", "i", "need", "want", "give", "show", "find", "list", "get", "any", "some", "please",
    "doctor", "doctors", "dr", "specialist", "specialists", "physician", "physicians", "consultant", "who", "treats",
    "treat", "for", "with", "of", "in", "and", "to", "see", "book", "available", "good", "best", "problem", "problems",
    "disease", "diseases", "issue", "issues", "care", "clinic", "expert", "experts", "can", "you", "is", "are", "there",
}

_VOCABULARY = {word: stem for stem, words in SPECIALTIES.items() for word in words}


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]+(?:-[a-z]+)?", text.lower().replace("'", "")) if w not in FILLER]


def search_terms(text: str | None) -> list[str]:
    """Specialty stems for a user's words, best match first; [] if none is recognised.

    Phrases ("ear nose throat") are matched first, then single words, then
    close misspellings ("cardiolgist", "dermatolgy").
    """
    if not text:
        return []
    lowered = " ".join(text.lower().replace("'", "").split())
    stems: list[str] = []

    def add(stem: str) -> None:
        if stem not in stems:
            stems.append(stem)

    for phrase, stem in _VOCABULARY.items():
        if " " in phrase and phrase in lowered:
            add(stem)
    for word in _words(lowered):
        if word in _VOCABULARY:
            add(_VOCABULARY[word])
        elif any(word.startswith(stem) for stem in SPECIALTIES) and len(word) >= 4:
            add(next(stem for stem in SPECIALTIES if word.startswith(stem)))
        else:
            close = difflib.get_close_matches(word, _VOCABULARY.keys(), n=1, cutoff=0.82) if len(word) >= 5 else []
            if close:
                add(_VOCABULARY[close[0]])
    return stems
