"""The clinic's reference catalog (D118), loaded by catalog_service.seed.

Plain data, reviewed as a whole. Slugs are stable keys: never rename one,
add a new entry instead. Names are shown to people; aliases are other words
for the same thing, lower case, unique within their kind.

These are broad catalog categories for finding the right clinic, not a
universal medical taxonomy. Topic links say which specializations commonly
see a condition ("primary"), or may also help ("secondary"); they are routing
guidance, never a diagnosis, and start with review status "curated" until a
clinician reviews them.
"""

# slug, name, aliases, icon, color, description
DEPARTMENTS: list[tuple[str, str, tuple[str, ...], str, str, str]] = [
    ("general-family-medicine", "General & Family Medicine", ("general medicine", "family medicine", "general practice", "primary care", "gp"), "stethoscope", "blue", "First-contact care for adults and families: everyday illness, check-ups and referrals."),
    ("internal-medicine", "Internal Medicine", ("medicine", "general internal medicine"), "stethoscope", "teal", "Diagnosis and long-term care of adult illness affecting several body systems."),
    ("cardiology", "Cardiology", ("heart", "cardiac", "heart care"), "heart-pulse", "red", "Heart and blood vessel conditions."),
    ("neurology", "Neurology", ("brain and nerves", "nervous system"), "brain", "purple", "Brain, spinal cord, nerve and muscle conditions."),
    ("pulmonology", "Pulmonology", ("chest medicine", "respiratory medicine", "lungs", "pulmonary medicine"), "activity", "teal", "Lung and breathing conditions."),
    ("gastroenterology", "Gastroenterology", ("digestive health", "gastro", "stomach and liver"), "pill", "orange", "Stomach, bowel, liver and pancreas conditions."),
    ("nephrology", "Nephrology", ("kidney care", "renal medicine"), "activity", "violet", "Kidney conditions, dialysis and transplant care."),
    ("endocrinology", "Endocrinology", ("hormones", "diabetes and endocrinology", "endocrine"), "syringe", "green", "Hormone and metabolic conditions, including diabetes and thyroid disease."),
    ("dermatology", "Dermatology", ("skin", "skin care", "skin hair and nails"), "scan-face", "pink", "Skin, hair and nail conditions."),
    ("rheumatology", "Rheumatology", ("joints and autoimmune", "rheumatism"), "bone", "yellow", "Arthritis and autoimmune conditions of joints, muscles and connective tissue."),
    ("hematology-oncology", "Hematology & Oncology", ("haematology", "hematology", "oncology", "cancer care", "blood and cancer"), "microscope", "violet", "Blood disorders and cancer care."),
    ("general-surgery", "General Surgery", ("surgery",), "hospital", "slate", "Operations of the abdomen, skin, breast and soft tissues."),
    ("orthopedics", "Orthopedics", ("orthopaedics", "orthopedic", "orthopaedic", "bone and joint", "ortho"), "bone", "orange", "Bones, joints, ligaments and spine."),
    ("neurosurgery", "Neurosurgery", ("brain and spine surgery",), "brain", "slate", "Surgery of the brain, spine and nerves."),
    ("urology", "Urology", ("urinary tract", "mens health"), "pill", "blue", "Kidney, bladder, prostate and male reproductive conditions."),
    ("obstetrics-gynecology", "Obstetrics & Gynecology", ("obgyn", "ob gyn", "obstetrics and gynaecology", "gynecology", "gynaecology", "obstetrics", "womens health"), "baby", "pink", "Pregnancy, childbirth and women's health."),
    ("pediatrics", "Pediatrics", ("paediatrics", "child health", "children", "child", "kids", "childrens health"), "baby", "yellow", "Health care for babies, children and teenagers."),
    ("ophthalmology", "Ophthalmology", ("eye care", "eyes", "eye"), "eye", "blue", "Eye and vision conditions."),
    ("ent", "ENT / Otolaryngology", ("ent", "otolaryngology", "ear nose and throat", "ear nose throat"), "ear", "teal", "Ear, nose, throat, head and neck conditions."),
    ("psychiatry-mental-health", "Psychiatry & Mental Health", ("psychiatry", "mental health", "behavioral health", "behavioural health"), "brain", "violet", "Mental health conditions, therapy and medication."),
    ("emergency-critical-care", "Emergency & Critical Care", ("emergency", "emergency medicine", "er", "a and e", "critical care", "icu"), "activity", "red", "Urgent and emergency care, and intensive care."),
    ("radiology-imaging", "Radiology & Imaging", ("radiology", "imaging", "x ray", "scans"), "scan-face", "slate", "X-ray, ultrasound, CT, MRI and image-guided procedures."),
    ("pathology-laboratory", "Pathology & Laboratory Medicine", ("pathology", "laboratory", "lab", "lab tests"), "microscope", "green", "Laboratory tests and tissue diagnosis."),
    ("physical-medicine-rehabilitation", "Physical Medicine & Rehabilitation", ("rehabilitation", "rehab", "physical medicine", "pmr", "physiatry"), "activity", "green", "Recovery of movement and function after illness or injury."),
]

# slug, name, department slugs, aliases
SPECIALIZATIONS: list[tuple[str, str, tuple[str, ...], tuple[str, ...]]] = [
    # General & Family Medicine
    ("general-practice", "General Practice", ("general-family-medicine",), ("general physician", "general practitioner", "gp doctor")),
    ("family-medicine", "Family Medicine", ("general-family-medicine",), ("family physician", "family doctor")),
    ("preventive-medicine", "Preventive Medicine", ("general-family-medicine",), ("preventive health",)),
    ("geriatric-medicine", "Geriatric Medicine", ("general-family-medicine", "internal-medicine"), ("geriatrician", "elderly care", "geriatrics")),
    # Internal Medicine
    ("general-internal-medicine", "General Internal Medicine", ("internal-medicine",), ("internist", "consultant physician")),
    ("infectious-diseases", "Infectious Diseases", ("internal-medicine",), ("infectious disease specialist", "infection specialist")),
    ("hospital-medicine", "Hospital Medicine", ("internal-medicine",), ("hospitalist",)),
    ("allergy-immunology", "Allergy & Immunology", ("internal-medicine",), ("allergist", "immunologist", "allergy specialist")),
    # Cardiology
    ("general-cardiology", "General Cardiology", ("cardiology",), ("cardiologist", "heart specialist", "heart doctor")),
    ("interventional-cardiology", "Interventional Cardiology", ("cardiology",), ("interventional cardiologist", "angioplasty", "cardiac catheterization")),
    ("electrophysiology", "Cardiac Electrophysiology", ("cardiology",), ("electrophysiologist", "heart rhythm specialist", "electrophysiology")),
    ("heart-failure", "Heart Failure", ("cardiology",), ("heart failure specialist",)),
    ("preventive-cardiology", "Preventive Cardiology", ("cardiology",), ("preventive cardiologist",)),
    ("cardiac-imaging", "Cardiac Imaging", ("cardiology", "radiology-imaging"), ("echocardiography", "echo", "cardiac mri")),
    ("pediatric-cardiology", "Pediatric Cardiology", ("pediatrics", "cardiology"), ("pediatric cardiologist", "paediatric cardiologist", "child cardiologist", "childrens heart doctor", "child heart doctor")),
    # Neurology
    ("general-neurology", "General Neurology", ("neurology",), ("neurologist", "nerve specialist", "brain doctor")),
    ("epilepsy", "Epilepsy", ("neurology",), ("epileptologist", "epilepsy specialist")),
    ("stroke-neurology", "Stroke Neurology", ("neurology",), ("vascular neurology", "stroke specialist")),
    ("movement-disorders", "Movement Disorders", ("neurology",), ("movement disorder specialist",)),
    ("headache-medicine", "Headache Medicine", ("neurology",), ("headache specialist", "migraine specialist")),
    ("neuromuscular-medicine", "Neuromuscular Medicine", ("neurology",), ("neuromuscular specialist",)),
    ("sleep-medicine", "Sleep Medicine", ("neurology", "pulmonology"), ("sleep specialist", "sleep doctor")),
    ("pediatric-neurology", "Pediatric Neurology", ("pediatrics", "neurology"), ("pediatric neurologist", "paediatric neurologist", "child neurologist", "childrens neurologist", "kids neurologist")),
    # Pulmonology
    ("general-pulmonology", "General Pulmonology", ("pulmonology",), ("pulmonologist", "chest physician", "chest specialist", "lung specialist", "lung doctor")),
    ("interventional-pulmonology", "Interventional Pulmonology", ("pulmonology",), ("bronchoscopy",)),
    ("interstitial-lung-disease", "Interstitial Lung Disease", ("pulmonology",), ("ild",)),
    ("critical-care-medicine", "Critical Care Medicine", ("pulmonology", "emergency-critical-care"), ("intensivist", "critical care specialist")),
    ("pediatric-pulmonology", "Pediatric Pulmonology", ("pediatrics", "pulmonology"), ("pediatric pulmonologist", "child lung specialist")),
    # Gastroenterology
    ("general-gastroenterology", "General Gastroenterology", ("gastroenterology",), ("gastroenterologist", "stomach specialist", "stomach doctor", "gi doctor")),
    ("hepatology", "Hepatology", ("gastroenterology",), ("hepatologist", "liver specialist", "liver doctor")),
    ("inflammatory-bowel-disease", "Inflammatory Bowel Disease", ("gastroenterology",), ("ibd specialist",)),
    ("therapeutic-endoscopy", "Endoscopy", ("gastroenterology",), ("endoscopist", "colonoscopy", "gastroscopy")),
    ("pediatric-gastroenterology", "Pediatric Gastroenterology", ("pediatrics", "gastroenterology"), ("pediatric gastroenterologist",)),
    # Nephrology
    ("general-nephrology", "General Nephrology", ("nephrology",), ("nephrologist", "kidney specialist", "kidney doctor")),
    ("dialysis", "Dialysis", ("nephrology",), ("hemodialysis", "haemodialysis", "peritoneal dialysis")),
    ("kidney-transplantation", "Kidney Transplantation", ("nephrology",), ("kidney transplant", "renal transplant")),
    ("pediatric-nephrology", "Pediatric Nephrology", ("pediatrics", "nephrology"), ("pediatric nephrologist",)),
    # Endocrinology
    ("general-endocrinology", "General Endocrinology", ("endocrinology",), ("endocrinologist", "hormone specialist", "hormone doctor")),
    ("diabetes", "Diabetes", ("endocrinology",), ("diabetologist", "diabetes specialist", "sugar specialist")),
    ("thyroid-disorders", "Thyroid Disorders", ("endocrinology",), ("thyroid specialist", "thyroid doctor")),
    ("pituitary-disorders", "Pituitary Disorders", ("endocrinology",), ("pituitary specialist",)),
    ("metabolic-bone-disease", "Metabolic Bone Disease", ("endocrinology", "rheumatology"), ("bone metabolism",)),
    ("pediatric-endocrinology", "Pediatric Endocrinology", ("pediatrics", "endocrinology"), ("pediatric endocrinologist", "child endocrinologist")),
    # Dermatology
    ("medical-dermatology", "Medical Dermatology", ("dermatology",), ("dermatologist", "skin specialist", "skin doctor")),
    ("cosmetic-dermatology", "Cosmetic Dermatology", ("dermatology",), ("cosmetic dermatologist", "aesthetic dermatology", "aesthetic dermatologist")),
    ("dermatologic-surgery", "Dermatologic Surgery", ("dermatology",), ("dermatologic surgeon", "skin surgery")),
    ("hair-nail-disorders", "Hair & Nail Disorders", ("dermatology",), ("trichologist", "trichology", "hair specialist")),
    ("pediatric-dermatology", "Pediatric Dermatology", ("pediatrics", "dermatology"), ("pediatric dermatologist", "child skin specialist")),
    # Rheumatology
    ("general-rheumatology", "General Rheumatology", ("rheumatology",), ("rheumatologist", "arthritis specialist")),
    ("inflammatory-arthritis", "Inflammatory Arthritis", ("rheumatology",), ()),
    ("lupus-connective-tissue", "Lupus & Connective Tissue Diseases", ("rheumatology",), ("connective tissue disease",)),
    # Hematology & Oncology
    ("hematology", "Hematology", ("hematology-oncology",), ("hematologist", "haematologist", "blood specialist")),
    ("medical-oncology", "Medical Oncology", ("hematology-oncology",), ("oncologist", "cancer specialist", "cancer doctor")),
    ("radiation-oncology", "Radiation Oncology", ("hematology-oncology",), ("radiation oncologist", "radiotherapy")),
    ("surgical-oncology", "Surgical Oncology", ("hematology-oncology", "general-surgery"), ("surgical oncologist", "cancer surgeon")),
    ("pediatric-hematology-oncology", "Pediatric Hematology & Oncology", ("pediatrics", "hematology-oncology"), ("pediatric oncologist", "child cancer specialist")),
    ("palliative-care", "Palliative Care", ("hematology-oncology", "internal-medicine"), ("palliative medicine",)),
    # General Surgery
    ("general-surgery-practice", "General Surgery", ("general-surgery",), ("general surgeon", "surgeon")),
    ("laparoscopic-surgery", "Laparoscopic & Minimally Invasive Surgery", ("general-surgery",), ("laparoscopic surgeon", "keyhole surgery")),
    ("colorectal-surgery", "Colorectal Surgery", ("general-surgery",), ("colorectal surgeon",)),
    ("breast-surgery", "Breast Surgery", ("general-surgery",), ("breast surgeon",)),
    ("hepatobiliary-surgery", "Hepatobiliary & Pancreatic Surgery", ("general-surgery",), ("hpb surgery", "hepatobiliary surgeon")),
    ("vascular-surgery", "Vascular Surgery", ("general-surgery",), ("vascular surgeon",)),
    ("bariatric-surgery", "Bariatric Surgery", ("general-surgery",), ("weight loss surgery", "bariatric surgeon")),
    ("trauma-surgery", "Trauma Surgery", ("general-surgery", "emergency-critical-care"), ("trauma surgeon",)),
    # Orthopedics
    ("general-orthopedics", "General Orthopedics", ("orthopedics",), ("orthopedic surgeon", "orthopaedic surgeon", "orthopedist", "bone specialist", "bone doctor")),
    ("sports-medicine", "Sports Medicine", ("orthopedics", "physical-medicine-rehabilitation"), ("sports medicine specialist", "sports doctor")),
    ("joint-replacement", "Joint Replacement", ("orthopedics",), ("knee replacement", "hip replacement", "arthroplasty")),
    ("spine-surgery", "Spine Surgery", ("orthopedics", "neurosurgery"), ("spine surgeon", "spine specialist")),
    ("orthopedic-trauma", "Orthopedic Trauma", ("orthopedics",), ("fracture specialist",)),
    ("pediatric-orthopedics", "Pediatric Orthopedics", ("pediatrics", "orthopedics"), ("pediatric orthopedic surgeon",)),
    # Neurosurgery
    ("general-neurosurgery", "General Neurosurgery", ("neurosurgery",), ("neurosurgeon", "brain surgeon")),
    ("neurosurgical-oncology", "Neurosurgical Oncology", ("neurosurgery",), ("brain tumor surgery", "brain tumour surgery")),
    ("functional-neurosurgery", "Functional Neurosurgery", ("neurosurgery",), ("deep brain stimulation",)),
    ("pediatric-neurosurgery", "Pediatric Neurosurgery", ("pediatrics", "neurosurgery"), ("pediatric neurosurgeon",)),
    # Urology
    ("general-urology", "General Urology", ("urology",), ("urologist",)),
    ("endourology", "Endourology & Kidney Stones", ("urology",), ("kidney stone specialist", "stone specialist", "endourologist")),
    ("urologic-oncology", "Urologic Oncology", ("urology",), ("urologic oncologist",)),
    ("andrology", "Andrology & Men's Health", ("urology",), ("andrologist",)),
    ("pediatric-urology", "Pediatric Urology", ("pediatrics", "urology"), ("pediatric urologist",)),
    # Obstetrics & Gynecology
    ("obstetrics", "Obstetrics", ("obstetrics-gynecology",), ("obstetrician",)),
    ("gynecology", "Gynecology", ("obstetrics-gynecology",), ("gynecologist", "gynaecologist", "lady doctor")),
    ("maternal-fetal-medicine", "Maternal-Fetal Medicine", ("obstetrics-gynecology",), ("high risk pregnancy specialist", "perinatologist")),
    ("reproductive-medicine", "Reproductive Medicine & Infertility", ("obstetrics-gynecology",), ("fertility specialist", "ivf specialist", "reproductive endocrinologist")),
    ("gynecologic-oncology", "Gynecologic Oncology", ("obstetrics-gynecology", "hematology-oncology"), ("gynecologic oncologist",)),
    ("urogynecology", "Urogynecology", ("obstetrics-gynecology", "urology"), ("urogynecologist",)),
    # Pediatrics
    ("general-pediatrics", "General Pediatrics", ("pediatrics",), ("pediatrician", "paediatrician", "child specialist", "childrens doctor", "kids doctor", "child doctor")),
    ("neonatology", "Neonatology", ("pediatrics",), ("neonatologist", "newborn specialist")),
    ("developmental-pediatrics", "Developmental Pediatrics", ("pediatrics",), ("developmental pediatrician",)),
    ("child-adolescent-psychiatry", "Child & Adolescent Psychiatry", ("pediatrics", "psychiatry-mental-health"), ("child psychiatrist", "adolescent psychiatrist")),
    ("pediatric-ophthalmology", "Pediatric Ophthalmology", ("pediatrics", "ophthalmology"), ("pediatric ophthalmologist", "child eye specialist", "child eye doctor")),
    ("pediatric-ent", "Pediatric ENT", ("pediatrics", "ent"), ("pediatric ent specialist", "child ent specialist")),
    # Ophthalmology
    ("general-ophthalmology", "General Ophthalmology", ("ophthalmology",), ("ophthalmologist", "eye specialist", "eye doctor", "eye surgeon")),
    ("cataract-refractive-surgery", "Cataract & Refractive Surgery", ("ophthalmology",), ("cataract surgeon", "lasik", "refractive surgery")),
    ("retina", "Retina", ("ophthalmology",), ("retina specialist", "vitreoretinal surgery")),
    ("glaucoma-care", "Glaucoma", ("ophthalmology",), ("glaucoma specialist",)),
    ("cornea", "Cornea & External Eye Disease", ("ophthalmology",), ("cornea specialist",)),
    # ENT
    ("general-ent", "General ENT", ("ent",), ("ent specialist", "ent doctor", "otolaryngologist", "ear nose throat specialist")),
    ("otology", "Otology & Hearing", ("ent",), ("otologist", "hearing specialist", "ear specialist", "audiology")),
    ("rhinology", "Rhinology & Sinus", ("ent",), ("sinus specialist", "rhinologist", "nose specialist")),
    ("laryngology", "Laryngology & Voice", ("ent",), ("voice specialist", "laryngologist", "throat specialist")),
    ("head-neck-surgery", "Head & Neck Surgery", ("ent",), ("head and neck surgeon",)),
    # Psychiatry & Mental Health
    ("general-psychiatry", "General Psychiatry", ("psychiatry-mental-health",), ("psychiatrist", "mental health doctor")),
    ("addiction-psychiatry", "Addiction Psychiatry", ("psychiatry-mental-health",), ("addiction specialist", "de addiction")),
    ("geriatric-psychiatry", "Geriatric Psychiatry", ("psychiatry-mental-health",), ("old age psychiatry",)),
    ("clinical-psychology", "Clinical Psychology", ("psychiatry-mental-health",), ("psychologist", "clinical psychologist", "therapist", "counsellor", "counselor")),
    # Emergency & Critical Care
    ("emergency-medicine", "Emergency Medicine", ("emergency-critical-care",), ("emergency physician", "er doctor")),
    # Radiology & Imaging
    ("diagnostic-radiology", "Diagnostic Radiology", ("radiology-imaging",), ("radiologist",)),
    ("interventional-radiology", "Interventional Radiology", ("radiology-imaging",), ("interventional radiologist",)),
    ("neuroradiology", "Neuroradiology", ("radiology-imaging",), ("neuroradiologist",)),
    ("breast-imaging", "Breast Imaging", ("radiology-imaging",), ("mammography",)),
    ("ultrasound", "Ultrasound", ("radiology-imaging",), ("sonography", "sonologist", "ultrasound scan")),
    ("nuclear-medicine", "Nuclear Medicine", ("radiology-imaging",), ("pet scan",)),
    # Pathology & Laboratory Medicine
    ("histopathology", "Histopathology", ("pathology-laboratory",), ("histopathologist", "anatomic pathology", "biopsy report")),
    ("clinical-pathology", "Clinical Pathology", ("pathology-laboratory",), ("clinical pathologist", "laboratory medicine")),
    ("hematopathology", "Hematopathology", ("pathology-laboratory",), ("hematopathologist",)),
    ("clinical-microbiology", "Clinical Microbiology", ("pathology-laboratory",), ("microbiologist",)),
    ("chemical-pathology", "Chemical Pathology", ("pathology-laboratory",), ("chemical pathologist", "clinical biochemistry")),
    # Physical Medicine & Rehabilitation
    ("general-rehabilitation", "General Rehabilitation Medicine", ("physical-medicine-rehabilitation",), ("physiatrist", "rehabilitation physician", "rehab doctor")),
    ("pain-medicine", "Pain Medicine", ("physical-medicine-rehabilitation",), ("pain specialist", "pain management")),
    ("neurorehabilitation", "Neurological Rehabilitation", ("physical-medicine-rehabilitation",), ("neurorehabilitation", "stroke rehabilitation")),
    ("physiotherapy", "Physiotherapy", ("physical-medicine-rehabilitation",), ("physiotherapist", "physical therapy", "physical therapist")),
]

P, S = "primary", "secondary"

# slug, canonical name, type, aliases, [(specialization slug, relevance)], urgent
TOPICS: list[tuple[str, str, str, tuple[str, ...], tuple[tuple[str, str], ...], bool]] = [
    # Hormones and metabolism
    ("diabetes", "Diabetes", "disease", ("diabetes", "diabetic", "sugar", "high blood sugar", "blood sugar", "type 1 diabetes", "type 2 diabetes", "sugar problem"), (("diabetes", P), ("general-endocrinology", P), ("general-internal-medicine", S), ("pediatric-endocrinology", S)), False),
    ("thyroid-disease", "Thyroid disease", "disease", ("thyroid", "thyroid disease", "thyroid problem", "hypothyroidism", "hyperthyroidism", "goiter", "goitre"), (("thyroid-disorders", P), ("general-endocrinology", P)), False),
    ("high-cholesterol", "High cholesterol", "condition", ("cholesterol", "high cholesterol", "lipids"), (("preventive-cardiology", P), ("general-internal-medicine", S), ("general-endocrinology", S)), False),
    ("obesity", "Obesity and weight management", "condition", ("obesity", "overweight", "weight loss", "weight gain"), (("general-endocrinology", P), ("preventive-medicine", S), ("bariatric-surgery", S)), False),
    ("osteoporosis", "Osteoporosis", "disease", ("osteoporosis", "weak bones", "bone density"), (("metabolic-bone-disease", P), ("general-rheumatology", S)), False),
    ("pcos", "Polycystic ovary syndrome (PCOS)", "condition", ("pcos", "pcod", "polycystic ovary", "polycystic ovaries"), (("gynecology", P), ("reproductive-medicine", S), ("general-endocrinology", S)), False),
    # Heart and circulation
    ("hypertension", "High blood pressure", "condition", ("hypertension", "high blood pressure", "high bp"), (("general-cardiology", P), ("general-internal-medicine", P), ("preventive-cardiology", S), ("general-nephrology", S)), False),
    ("heart-rhythm-disorder", "Heart rhythm disorder", "condition", ("arrhythmia", "irregular heartbeat", "irregular heart beat", "palpitations", "atrial fibrillation", "afib", "heart racing", "heart rhythm"), (("electrophysiology", P), ("general-cardiology", P)), False),
    ("heart-failure-topic", "Heart failure", "disease", ("heart failure", "weak heart", "congestive heart failure"), (("heart-failure", P), ("general-cardiology", P)), False),
    ("coronary-artery-disease", "Coronary artery disease", "disease", ("coronary artery disease", "blocked arteries", "angina", "heart blockage", "blocked heart"), (("general-cardiology", P), ("interventional-cardiology", P), ("preventive-cardiology", S)), False),
    ("heart-attack", "Heart attack", "condition", ("heart attack", "cardiac arrest"), (("emergency-medicine", P), ("interventional-cardiology", P)), True),
    ("chest-pain", "Chest pain", "symptom", ("chest pain", "chest tightness", "pain in chest", "chest pressure"), (("emergency-medicine", P), ("general-cardiology", P), ("general-pulmonology", S)), True),
    ("varicose-veins", "Varicose veins", "condition", ("varicose veins", "swollen veins"), (("vascular-surgery", P),), False),
    ("congenital-heart-disease", "Heart problems in children", "condition", ("hole in the heart", "congenital heart disease", "heart murmur"), (("pediatric-cardiology", P),), False),
    # Brain and nerves
    ("migraine", "Migraine", "disease", ("migraine", "migraines"), (("headache-medicine", P), ("general-neurology", P)), False),
    ("headache", "Headache", "symptom", ("headache", "headaches", "head pain", "head ache"), (("general-neurology", P), ("headache-medicine", S), ("general-practice", S)), False),
    ("epilepsy-seizures", "Epilepsy and seizures", "disease", ("epilepsy", "seizure", "seizures", "fits", "convulsions"), (("epilepsy", P), ("general-neurology", P), ("pediatric-neurology", S)), False),
    ("stroke", "Stroke", "condition", ("stroke", "brain attack", "face drooping", "sudden weakness", "sudden numbness", "paralysis"), (("emergency-medicine", P), ("stroke-neurology", P)), True),
    ("parkinsons", "Parkinson's disease and tremor", "disease", ("parkinson", "parkinsons", "parkinsons disease", "tremor", "tremors", "shaking hands"), (("movement-disorders", P), ("general-neurology", S)), False),
    ("dementia", "Memory loss and dementia", "condition", ("dementia", "alzheimer", "alzheimers", "memory loss", "forgetfulness"), (("general-neurology", P), ("geriatric-medicine", P), ("geriatric-psychiatry", S)), False),
    ("neuropathy", "Nerve pain and numbness", "symptom", ("numbness", "tingling", "nerve pain", "neuropathy", "pins and needles"), (("neuromuscular-medicine", P), ("general-neurology", P)), False),
    ("dizziness", "Dizziness and vertigo", "symptom", ("dizziness", "dizzy", "vertigo", "spinning"), (("general-neurology", P), ("otology", P), ("general-practice", S)), False),
    # Lungs and sleep
    ("asthma", "Asthma", "disease", ("asthma", "wheezing", "wheeze"), (("general-pulmonology", P), ("allergy-immunology", S), ("pediatric-pulmonology", S)), False),
    ("copd", "COPD", "disease", ("copd", "emphysema", "chronic bronchitis"), (("general-pulmonology", P),), False),
    ("chronic-cough", "Persistent cough", "symptom", ("cough", "persistent cough", "chronic cough", "coughing"), (("general-pulmonology", P), ("general-practice", P)), False),
    ("shortness-of-breath", "Shortness of breath", "symptom", ("shortness of breath", "breathlessness", "difficulty breathing", "cant breathe", "short of breath"), (("emergency-medicine", P), ("general-pulmonology", P), ("general-cardiology", S)), True),
    ("tuberculosis", "Tuberculosis (TB)", "disease", ("tuberculosis", "tb"), (("general-pulmonology", P), ("infectious-diseases", P)), False),
    ("sleep-apnea", "Snoring and sleep apnea", "condition", ("sleep apnea", "sleep apnoea", "snoring"), (("sleep-medicine", P), ("general-ent", S)), False),
    ("insomnia", "Sleep problems", "condition", ("insomnia", "cant sleep", "trouble sleeping", "sleep problems"), (("sleep-medicine", P), ("general-psychiatry", S)), False),
    # Digestive system
    ("acid-reflux", "Acid reflux and heartburn", "condition", ("acid reflux", "gerd", "heartburn", "acidity", "indigestion"), (("general-gastroenterology", P), ("general-practice", S)), False),
    ("liver-disease", "Liver disease", "disease", ("liver disease", "fatty liver", "hepatitis", "jaundice", "cirrhosis", "liver problem"), (("hepatology", P), ("general-gastroenterology", P), ("infectious-diseases", S)), False),
    ("ibd", "Crohn's disease and ulcerative colitis", "disease", ("crohns", "crohns disease", "ulcerative colitis", "colitis", "inflammatory bowel disease", "ibd"), (("inflammatory-bowel-disease", P), ("general-gastroenterology", P)), False),
    ("abdominal-pain", "Stomach pain", "symptom", ("stomach pain", "abdominal pain", "stomach ache", "tummy pain", "belly pain"), (("general-gastroenterology", P), ("general-practice", P), ("general-surgery-practice", S)), False),
    ("ibs-constipation", "Bowel problems", "symptom", ("constipation", "diarrhea", "diarrhoea", "ibs", "irritable bowel", "bloating"), (("general-gastroenterology", P), ("general-practice", S)), False),
    ("gallstones", "Gallstones", "disease", ("gallstones", "gallstone", "gallbladder stones", "gallbladder"), (("general-surgery-practice", P), ("laparoscopic-surgery", P), ("general-gastroenterology", S)), False),
    ("hernia", "Hernia", "condition", ("hernia", "inguinal hernia", "umbilical hernia"), (("general-surgery-practice", P), ("laparoscopic-surgery", P)), False),
    ("appendicitis", "Appendicitis", "disease", ("appendicitis", "appendix pain"), (("emergency-medicine", P), ("general-surgery-practice", P)), True),
    ("piles", "Piles and anal problems", "condition", ("piles", "hemorrhoids", "haemorrhoids", "fissure", "fistula"), (("colorectal-surgery", P), ("general-surgery-practice", P)), False),
    # Kidneys and urinary tract
    ("kidney-stones", "Kidney stones", "disease", ("kidney stones", "kidney stone", "renal stones", "stone in kidney"), (("endourology", P), ("general-urology", P), ("general-nephrology", S)), False),
    ("chronic-kidney-disease", "Kidney disease", "disease", ("kidney disease", "chronic kidney disease", "ckd", "kidney failure", "renal failure", "weak kidneys"), (("general-nephrology", P), ("dialysis", S)), False),
    ("uti", "Urinary tract infection", "condition", ("uti", "urine infection", "urinary infection", "burning urination", "painful urination"), (("general-urology", P), ("general-practice", P), ("infectious-diseases", S)), False),
    ("prostate", "Prostate problems", "condition", ("prostate", "enlarged prostate", "prostate problem", "frequent urination"), (("general-urology", P), ("urologic-oncology", S)), False),
    ("erectile-dysfunction", "Erectile dysfunction", "condition", ("erectile dysfunction", "impotence"), (("andrology", P),), False),
    # Skin, hair and nails
    ("eczema", "Eczema", "disease", ("eczema", "atopic dermatitis"), (("medical-dermatology", P), ("allergy-immunology", S), ("pediatric-dermatology", S)), False),
    ("acne", "Acne", "condition", ("acne", "pimples", "breakouts"), (("medical-dermatology", P), ("cosmetic-dermatology", S)), False),
    ("psoriasis", "Psoriasis", "disease", ("psoriasis",), (("medical-dermatology", P), ("general-rheumatology", S)), False),
    ("skin-rash", "Skin rash and itching", "symptom", ("rash", "skin rash", "itching", "itchy skin", "hives"), (("medical-dermatology", P), ("allergy-immunology", S)), False),
    ("hair-loss", "Hair loss", "condition", ("hair loss", "hair fall", "baldness", "alopecia"), (("hair-nail-disorders", P), ("medical-dermatology", P)), False),
    # Bones, joints and muscles
    ("arthritis", "Arthritis and joint pain", "condition", ("arthritis", "joint pain", "joint pains", "swollen joints"), (("general-rheumatology", P), ("general-orthopedics", P), ("inflammatory-arthritis", S)), False),
    ("rheumatoid-arthritis", "Rheumatoid arthritis", "disease", ("rheumatoid arthritis",), (("inflammatory-arthritis", P), ("general-rheumatology", P)), False),
    ("lupus", "Lupus", "disease", ("lupus", "sle"), (("lupus-connective-tissue", P), ("general-rheumatology", P)), False),
    ("gout", "Gout", "disease", ("gout", "uric acid"), (("general-rheumatology", P), ("general-internal-medicine", S)), False),
    ("fracture", "Broken bone", "condition", ("fracture", "broken bone", "broken arm", "broken leg", "bone fracture"), (("orthopedic-trauma", P), ("general-orthopedics", P), ("emergency-medicine", S)), False),
    ("back-pain", "Back and neck pain", "symptom", ("back pain", "lower back pain", "neck pain", "slipped disc", "sciatica", "disc problem"), (("general-orthopedics", P), ("spine-surgery", S), ("general-rehabilitation", S), ("pain-medicine", S)), False),
    ("knee-pain", "Knee pain", "symptom", ("knee pain", "knee injury", "acl", "acl tear", "meniscus"), (("general-orthopedics", P), ("sports-medicine", P), ("joint-replacement", S)), False),
    ("sports-injury", "Sports injury", "condition", ("sports injury", "sprain", "ligament injury"), (("sports-medicine", P), ("general-orthopedics", S), ("physiotherapy", S)), False),
    ("chronic-pain", "Long-term pain", "condition", ("chronic pain", "long term pain"), (("pain-medicine", P), ("general-rehabilitation", S)), False),
    ("rehabilitation-needs", "Recovery after illness or injury", "condition", ("rehabilitation after stroke", "recovery after stroke", "physiotherapy", "physical therapy", "rehab after surgery"), (("physiotherapy", P), ("neurorehabilitation", P), ("general-rehabilitation", P)), False),
    # Blood and cancer
    ("anemia", "Anemia", "condition", ("anemia", "anaemia", "low hemoglobin", "low haemoglobin", "low blood"), (("hematology", P), ("general-internal-medicine", S)), False),
    ("cancer", "Cancer", "disease", ("cancer", "tumor", "tumour", "malignancy", "chemotherapy"), (("medical-oncology", P), ("surgical-oncology", S), ("radiation-oncology", S)), False),
    ("breast-lump", "Breast lump", "symptom", ("breast lump", "lump in breast", "breast pain"), (("breast-surgery", P), ("breast-imaging", S), ("medical-oncology", S)), False),
    # Women's health and pregnancy
    ("pregnancy", "Pregnancy care", "condition", ("pregnancy", "pregnant", "prenatal", "antenatal", "expecting a baby"), (("obstetrics", P), ("maternal-fetal-medicine", S)), False),
    ("infertility", "Infertility", "condition", ("infertility", "ivf", "trying to conceive", "cant conceive", "fertility"), (("reproductive-medicine", P), ("andrology", S)), False),
    ("menstrual-problems", "Period problems", "condition", ("irregular periods", "period problems", "heavy periods", "painful periods", "menstrual problems", "menopause"), (("gynecology", P),), False),
    # Children
    ("child-illness", "Illness in children", "condition", ("child fever", "fever in child", "sick child", "baby fever", "child vaccination", "baby vaccination"), (("general-pediatrics", P),), False),
    ("developmental-delay", "Developmental and behaviour concerns in children", "condition", ("autism", "adhd", "speech delay", "developmental delay", "late walking"), (("developmental-pediatrics", P), ("child-adolescent-psychiatry", S), ("pediatric-neurology", S)), False),
    ("newborn-care", "Newborn care", "condition", ("newborn", "premature baby", "neonatal jaundice", "preterm baby"), (("neonatology", P), ("general-pediatrics", S)), False),
    # Eyes
    ("cataract", "Cataract", "disease", ("cataract", "cataracts", "cloudy vision"), (("cataract-refractive-surgery", P), ("general-ophthalmology", S)), False),
    ("glaucoma", "Glaucoma", "disease", ("glaucoma", "eye pressure"), (("glaucoma-care", P), ("general-ophthalmology", S)), False),
    ("vision-problems", "Vision problems", "symptom", ("blurred vision", "blurry vision", "vision problem", "poor eyesight", "eye pain", "red eye", "eye infection"), (("general-ophthalmology", P),), False),
    ("diabetic-retinopathy", "Diabetic eye disease", "disease", ("diabetic retinopathy", "retinopathy", "retina problem"), (("retina", P), ("general-ophthalmology", S)), False),
    # Ear, nose and throat
    ("ear-problems", "Ear pain and infection", "condition", ("ear pain", "ear infection", "earache", "ear discharge"), (("general-ent", P), ("pediatric-ent", S)), False),
    ("hearing-loss", "Hearing loss and tinnitus", "condition", ("hearing loss", "deafness", "tinnitus", "ringing in ears", "hard of hearing"), (("otology", P), ("general-ent", S)), False),
    ("sinusitis", "Sinus problems", "condition", ("sinus", "sinusitis", "blocked nose", "nasal congestion", "nose bleed", "nosebleed"), (("rhinology", P), ("general-ent", P), ("allergy-immunology", S)), False),
    ("sore-throat", "Sore throat and tonsils", "symptom", ("sore throat", "throat pain", "tonsils", "tonsillitis"), (("general-ent", P), ("general-practice", P)), False),
    ("voice-problems", "Voice problems", "symptom", ("hoarseness", "hoarse voice", "voice loss", "lost voice"), (("laryngology", P),), False),
    # Mental health
    ("depression", "Depression", "condition", ("depression", "depressed", "low mood", "feeling sad"), (("general-psychiatry", P), ("clinical-psychology", P)), False),
    ("anxiety", "Anxiety and stress", "condition", ("anxiety", "anxious", "panic attack", "panic attacks", "stress", "worry"), (("general-psychiatry", P), ("clinical-psychology", P)), False),
    ("addiction", "Addiction", "condition", ("addiction", "substance use", "alcohol problem", "drug addiction", "quit smoking", "smoking cessation"), (("addiction-psychiatry", P), ("clinical-psychology", S)), False),
    ("self-harm", "Thoughts of self-harm", "symptom", ("suicidal", "suicide", "self harm", "want to die", "kill myself"), (("emergency-medicine", P), ("general-psychiatry", P)), True),
    # Everyday and general care
    ("fever", "Fever, cold and flu", "symptom", ("fever", "flu", "cold", "viral fever", "common cold", "body aches"), (("general-practice", P), ("family-medicine", P), ("infectious-diseases", S)), False),
    ("checkup", "Health check-up", "condition", ("checkup", "check up", "health checkup", "medical checkup", "health screening", "routine checkup"), (("preventive-medicine", P), ("general-practice", P), ("family-medicine", P)), False),
    ("allergies", "Allergies", "condition", ("allergy", "allergies", "hay fever", "allergic reaction"), (("allergy-immunology", P), ("rhinology", S), ("medical-dermatology", S)), False),
    ("infection", "Infections", "condition", ("infection", "typhoid", "dengue", "malaria"), (("infectious-diseases", P), ("general-practice", P)), False),
    ("fatigue", "Tiredness and weakness", "symptom", ("tiredness", "fatigue", "always tired", "weakness", "low energy"), (("general-practice", P), ("general-internal-medicine", P)), False),
    ("elderly-care", "Care for older adults", "condition", ("elderly", "old age problems", "elderly parent"), (("geriatric-medicine", P),), False),
    ("severe-bleeding", "Severe bleeding or injury", "symptom", ("severe bleeding", "heavy bleeding", "accident", "serious injury", "unconscious", "fainted"), (("emergency-medicine", P), ("trauma-surgery", P)), True),
]

SOURCE = "catalog v1 (curated, pending clinical review)"
