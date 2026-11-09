"""Doctor-style wording for the brain MRI report.

Mirrors eeg.interpretation: a verdict, a clinical impression, recommendations
and precautions, shared by the web page and the PDF. The precautions are
standard patient-safety guidance for the suspected lesion type, framed for
the reviewing radiologist or neurosurgeon to confirm -- the underlying call
is a four-class image classifier's, not a histological diagnosis.
"""

TUMOUR_DESCRIPTIONS = {
    "Glioma": "an intra-axial lesion with imaging features suggestive of glioma",
    "Meningioma": "an extra-axial, dural-based lesion with imaging features "
                  "suggestive of meningioma",
    "Pituitary": "a sellar / suprasellar lesion with imaging features "
                 "suggestive of pituitary adenoma",
}

GENERAL_PRECAUTION = (
    "This report is a screening aid and must be verified by a qualified "
    "radiologist before any clinical decision."
)

RED_FLAGS = (
    "Seek emergency care for sudden severe headache, repeated vomiting, a "
    "first seizure, new weakness, speech difficulty, confusion or loss of "
    "consciousness."
)


def mri_verdict(prediction):
    """Overall NORMAL / ABNORMAL call. No prediction means NOT ASSESSED."""
    prediction = (prediction or "").strip()
    if prediction != "No Tumor" and prediction not in TUMOUR_DESCRIPTIONS:
        return {"label": "NOT ASSESSED", "tone": "warn",
                "detail": "No classification was produced for this study."}
    if prediction == "No Tumor":
        return {"label": "NORMAL", "tone": "good",
                "detail": "No tumour detected by the classifier."}
    return {"label": "ABNORMAL", "tone": "bad",
            "detail": f"{prediction} suspected."}


def _given(values, key):
    value = str(values.get(key) or "").strip()
    return value if value and value != "Not provided" else None


def _impression(prediction, v):
    confidence = _given(v, "confidence")
    conf_text = f" (classifier confidence {confidence}%)" if confidence else ""

    if prediction == "No Tumor":
        return ("The classifier assigned the highest score to its no-tumour "
                f"category{conf_text}. This is a screening output, not a "
                "radiological interpretation. It does not exclude lesions or "
                "other intracranial pathology; correlate with symptoms and "
                "the complete study reviewed by a radiologist.")

    if prediction not in TUMOUR_DESCRIPTIONS:
        return ("No automated classification is available for this study. "
                "The images require full review by a radiologist; this "
                "report offers no reassurance.")

    location = _given(v, "location")
    detail = []
    if location and location != "Not applicable":
        where = location if location.lower().endswith(("region", "area")) \
            else f"{location} region"
        detail.append(f"the highest model activation lies in the {where}")
    detail_text = (", " + ", ".join(detail)) if detail else ""
    return (f"The classifier assigned the highest score to the {prediction} "
            f"category{conf_text}{detail_text}. This is a screening output, "
            "not a radiological finding or confirmed diagnosis. Attention "
            "localisation is derived from model activation maps; lesion size "
            "is not measured. Radiologist review of the complete study is "
            "required.")


def _recommendations(prediction):
    if prediction in TUMOUR_DESCRIPTIONS:
        return [
            "Radiologist review of the complete MRI and clinical history to "
            "confirm or refute this classifier output.",
            "Further imaging or specialist referral should be determined by "
            "the reviewing clinician.",
        ]
    if prediction == "No Tumor":
        return [
            "Correlate with the clinical presentation; this classifier output "
            "does not exclude intracranial disease.",
            "Obtain radiologist review if symptoms persist or progress.",
        ]
    return ["Full review of the images by a qualified radiologist."]

def _precautions(prediction):
    if prediction == "Glioma":
        return [
            "Do not drive until cleared by the treating specialist, "
            "especially if any seizure has occurred.",
            "Avoid swimming or bathing alone, and working at heights, until "
            "seizure risk is assessed.",
            "Take any prescribed steroids or anti-seizure medication exactly "
            "as directed; do not stop abruptly.",
            RED_FLAGS,
            GENERAL_PRECAUTION,
        ]
    if prediction == "Meningioma":
        return [
            "Report any new headache pattern, vision change, weakness, "
            "personality change or seizure promptly.",
            "Keep scheduled follow-up imaging even if symptom-free.",
            RED_FLAGS,
            GENERAL_PRECAUTION,
        ]
    if prediction == "Pituitary":
        return [
            "Report any change in vision (blurring, loss of side vision, "
            "double vision) immediately.",
            "Seek urgent care for a sudden severe headache with vomiting or "
            "vision loss, which can indicate pituitary apoplexy.",
            "Watch for symptoms of hormone imbalance: fatigue, dizziness, "
            "weight change, menstrual or sexual changes, nipple discharge.",
            "If prescribed hormone replacement, do not miss doses; ask about "
            "sick-day steroid rules.",
            GENERAL_PRECAUTION,
        ]
    if prediction == "No Tumor":
        return [
            "Seek medical review if headaches worsen, or new neurological "
            "symptoms appear.",
            RED_FLAGS,
            GENERAL_PRECAUTION,
        ]
    return [
        "Do not treat this study as reassurance; no classification was "
        "performed.",
        GENERAL_PRECAUTION,
    ]


def clinical_notes(prediction, values):
    """Return {"impression", "recommendations", "precautions"}.

    prediction: "Glioma", "Meningioma", "Pituitary", "No Tumor" or empty
    values:     mapping with optional confidence / location / area / severity
    """
    prediction = (prediction or "").strip()
    values = values or {}
    return {
        "impression": _impression(prediction, values),
        "recommendations": _recommendations(prediction),
        "precautions": _precautions(prediction),
    }
