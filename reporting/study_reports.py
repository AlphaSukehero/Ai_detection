"""Per-study PDF content for ECG, EEG and MRI.

Each `*_report_spec(data)` takes the flat report dict a result page carries
(patient metadata + result fields) and returns everything build_pdf_report
needs. The same dict is what a saved study stores as its `report`, so the
download button, the stored per-study PDF and the complete history PDF are
built by one function per modality and cannot disagree.
"""
import json
import uuid
from datetime import datetime

from eeg.interpretation import clinical_notes as eeg_clinical_notes
from reporting.pdf import build_pdf_report, doctor_sections
from vision.interpretation import clinical_notes as mri_clinical_notes, mri_verdict
from webapp.metadata import NOT_PROVIDED, PATIENT_FIELDS, _clean_text

EEG_TASKS = {"seizure": "Epileptiform / seizure activity",
             "alzheimer": "Cortical slowing (dementia screen)"}
CLINICAL_REPORT_FIELDS = [
    ("patient_name", "Patient Name"), ("patient_id", "Patient ID"),
    ("age", "Age"), ("gender", "Gender"),
    ("study_date", "Examination Date"),
    ("referring_physician", "Referring Physician"),
]


def form_meta(form, fields=PATIENT_FIELDS):
    """Rebuild a metadata dict from the fields posted by a result page."""
    meta = {key: (_clean_text(form.get(key), 1000) or NOT_PROVIDED) for key, _ in fields}
    meta["report_id"] = _clean_text(form.get("report_id")) or ("RPT-" + uuid.uuid4().hex[:10].upper())
    meta["generated_at"] = _clean_text(form.get("generated_at")) or datetime.now().strftime("%d %b %Y, %H:%M:%S")
    return meta


def slug(value, fallback):
    """Filename-safe token derived from a metadata value."""
    if not value or value == NOT_PROVIDED:
        return fallback
    cleaned = "".join(c if c.isalnum() else "_" for c in value).strip("_")
    return cleaned[:40] or fallback


def pdf_value(raw):
    """Render an unmeasured parameter explicitly in the PDF.

    A dash in a clinical report is ambiguous - it could mean zero, or missing.
    "Not measurable" says which.
    """
    if raw is None or str(raw).strip() in {"", "—", "-"}:
        return "Not measurable"
    return raw


def _percent(raw):
    """'12.5%' for a value; 'Not measurable' for a blank, never a bare '%'."""
    value = pdf_value(raw)
    return value if value == "Not measurable" else f"{value}%"


def _with_unit(raw, unit):
    value = pdf_value(raw)
    return value if value == "Not measurable" else f"{value} {unit}"


def clinical_from_form(form):
    """Rebuild the structured reading from the measurements posted back.

    Returns None when the page posted no measurement payload -- an older
    result page, or a direct post -- so the report simply omits the section
    rather than inventing one.
    """
    raw = form.get("clinical_json")
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or "parameters" not in data:
        return None
    return data


def ecg_classification_rows(form):
    """Rows for the classification table, or an explicit statement of absence.

    A report must never imply a classification happened when it did not, so
    when no classifier ran the table carries the reason instead of a row of
    em-dashes that reads like a missing measurement.
    """
    prediction = (form.get("prediction") or "").strip()
    if not prediction:
        return [
            ("Parameter", "Result"),
            ("Overall Rhythm Classification", "Not performed"),
            ("Reason", form.get("classifier_error")
                       or "No validated ECG classifier was installed."),
            ("Signal Quality", form.get("signal_quality", NOT_PROVIDED)),
            ("Input Source", form.get("input_source", NOT_PROVIDED)),
        ]
    return [
        ("Parameter", "Result"),
        ("Overall Rhythm Classification", prediction),
        ("Abnormality Class", form.get("abnormal_type", NOT_PROVIDED)),
        ("Classifier", form.get("classifier", NOT_PROVIDED)),
        ("Classifier Confidence", _percent(form.get("confidence"))),
        ("Supraventricular (S) Beat Probability", _percent(form.get("atrial_probability"))),
        ("Signal Quality", form.get("signal_quality", NOT_PROVIDED)),
        ("Input Source", form.get("input_source", NOT_PROVIDED)),
    ]


def eeg_verdict(model_used, episodes, reason=None):
    """Overall NORMAL / ABNORMAL call for an EEG study.

    Without a model nothing was classified, so the answer is NOT ASSESSED:
    measurements alone never make a recording "normal".
    """
    if not model_used:
        return {"label": "NOT ASSESSED", "tone": "warn",
                "detail": reason or "No validated model installed; no window was classified."}
    if episodes:
        return {"label": "ABNORMAL", "tone": "bad",
                "detail": f"{episodes} anomalous episode(s) detected."}
    return {"label": "NORMAL", "tone": "good",
            "detail": "No episode crossed the detection threshold."}


# ------------------------------------------------------------------ ECG

def ecg_report_spec(form):
    sections = [
        ("table", "ECG Examination Details", [
            ("Item", "Value"),
            ("Recording Duration", _with_unit(form.get("recording_duration_s"), "s")),
            ("Sampling Frequency", _with_unit(form.get("sampling_frequency_hz"), "Hz")),
            ("Signal Quality", form.get("signal_quality", NOT_PROVIDED)),
            ("Input Source", form.get("input_source", NOT_PROVIDED)),
        ]),
        ("table", "ECG Measurements", [
            ("Measurement", "Value"),
            ("Heart Rate", pdf_value(form.get("heart_rate"))),
            ("RR Interval", pdf_value(form.get("rr_interval"))),
            ("QRS Duration", pdf_value(form.get("qrs_duration"))),
            ("PR Interval", pdf_value(form.get("pr_interval"))),
            ("QT Interval", pdf_value(form.get("qt_interval"))),
            ("QTc (Corrected)", pdf_value(form.get("qtc"))),
            ("HRV SDNN", pdf_value(form.get("sdnn"))),
            ("HRV RMSSD", pdf_value(form.get("rmssd"))),
            ("Rhythm", pdf_value(form.get("rhythm"))),
            ("ST Segment", pdf_value(form.get("st_segment"))),
            ("QRS Axis", pdf_value(form.get("axis"))),
        ]),
        ("table", "ECG Classification", ecg_classification_rows(form)),
    ]
    return {
        "title": "ELECTROCARDIOGRAM REPORT",
        "subtitle": "Electrocardiographic Investigation",
        "accent": "#777777",
        "sections": sections,
        "closing": [],
        "disclaimer": (
            "Research prototype; not a medical device. Clinical review is required."),
        "footer_text": "",
        "file_prefix": "ECG_Report",
    }


# ------------------------------------------------------------------ MRI

def mri_report_spec(form):
    prediction = (form.get("prediction") or "").strip()
    notes = mri_clinical_notes(prediction, form)
    verdict = mri_verdict(prediction)
    classified = verdict["label"] != "NOT ASSESSED"
    sections = [
        ("table", "MRI Examination Details", [
            ("Item", "Value"),
            ("Modality", "Brain MRI"),
            ("Input Source", form.get("input_source", NOT_PROVIDED)),
            ("Image Format", form.get("file_type", NOT_PROVIDED)),
            ("Classifier", form.get("model_name") or NOT_PROVIDED),
        ]),
        ("table", "MRI Findings", [
            ("Finding", "Result"),
            ("Screening Assessment", verdict["label"]),
            ("Model Classification", prediction if classified else "Not performed"),
            ("Classifier Confidence", _percent(form.get("confidence"))
             if classified else "Not available"),
            ("Peak Attention Location", form.get("location") or "Not available"),
            ("Segmentation / Lesion Measurement", "Not performed"),
        ]),
        ("text", "MRI Impression", notes["impression"]),
    ]
    return {
        "title": "BRAIN MRI REPORT",
        "subtitle": "Magnetic Resonance Imaging Investigation",
        "accent": "#777777",
        "sections": sections,
        "closing": doctor_sections(notes, concise=True),
        "verdict": verdict,
        "disclaimer": (
            "Research prototype; not a medical device. Classification and attention "
            "require review by a qualified radiologist."),
        "footer_text": "",
        "file_prefix": "MRI_Report",
    }


# ------------------------------------------------------------------ EEG

def eeg_report_spec(form):
    try:
        r = json.loads(form.get("eeg_json") or "")
        if not isinstance(r, dict):
            raise ValueError
    except ValueError:
        r = {}

    def v(key, fmt="{}"):
        return fmt.format(r[key]) if r.get(key) is not None else NOT_PROVIDED

    assessed = bool(r.get("model_used"))
    verdict = eeg_verdict(assessed, r.get("episodes_n") or 0, r.get("not_assessed_reason"))
    task_key = r.get("task_key") if r.get("task_key") in EEG_TASKS else "seizure"
    notes = eeg_clinical_notes(task_key, verdict["label"], r)
    sections = [
        ("table", "EEG Examination Details", [
            ("Item", "Value"),
            ("Recording Duration", v("duration_s", "{} s")),
            ("File Type", v("file_type")),
            ("Sampling Frequency", v("sampling_frequency_hz", "{} Hz")),
            ("Channels", v("n_channels")),
            ("Input Source", v("source")),
            ("Clinical Question", v("task")),
            ("Analysis Representation", v("representation")),
            ("Windows Analysed", v("n_windows")),
            ("Artifact Windows", v("artifact_windows")),
        ]),
        ("table", "EEG Findings", [
            ("Measure", "Result"),
            ("Model Assessment", "Performed" if assessed else "Not assessed"),
            ("Classification", verdict["label"]),
            ("Detected Episodes", v("episodes_n") if assessed else "Not assessed"),
            ("Anomaly Burden", v("burden_pct", "{}%") if assessed else "Not assessed"),
            ("Mean Spike Rate", v("mean_spikes", "{} /s")),
            ("Highest Window Score",
             f"{r['peak_score']:.3f} at {r['peak_start_s']:.1f}-{r['peak_stop_s']:.1f} s"
             if assessed and r.get("peak_score") is not None else "Not available"),
        ]),
        ("text", "EEG Impression", notes["impression"]),
    ]
    if r.get("band_means"):
        sections.append(("table", "Mean Relative Spectral Power",
                         [("Band", "Share of 0.5–45 Hz power")]
                         + [(str(b), str(x)) for b, x in r["band_means"].items()]))
    if r.get("episodes"):
        sections.append(("table", "Detected Episodes",
                         [("Onset / Offset (s)", "Duration (s); peak score; spikes/s")]
                         + [(f"{e['onset_s']:.1f} – {e['offset_s']:.1f}",
                             f"{e['duration_s']:.1f}; {e['peak_score']:.3f}; "
                             f"{e['spike_rate_per_s']:.2f}")
                            for e in r["episodes"]]))
    summary = " ".join(x for x in (r.get("headline"), r.get("peak_note")) if x)
    if summary:
        sections.append(("text", "Summary", summary))
    return {
        "title": "ELECTROENCEPHALOGRAM REPORT",
        "subtitle": "Electroencephalographic Investigation",
        "accent": "#777777",
        "sections": sections,
        "closing": doctor_sections(notes, concise=True),
        "verdict": verdict,
        "disclaimer": (
            "Research prototype; not a medical device. Clinical review is required. "
            "Channels are averaged; findings are not spatially localized."),
        "footer_text": "",
        "file_prefix": "EEG_Report",
    }


REPORT_SPECS = {"ecg": ecg_report_spec, "eeg": eeg_report_spec, "mri": mri_report_spec}


def render_study_pdf(modality, data, images=(), extra_sections=()):
    """(BytesIO, filename) for one study. images: [(caption, path)].

    extra_sections follow the study's own images: a follow-up report puts
    the previous report there (reporting.followup).
    """
    spec = REPORT_SPECS[modality](data)
    meta_fields = CLINICAL_REPORT_FIELDS
    meta = form_meta(data, fields=meta_fields)
    image_sections = [("image", caption, path) for caption, path in images]
    buffer = build_pdf_report(
        title=spec["title"], subtitle=spec["subtitle"], accent=spec["accent"],
        meta=meta, meta_fields=meta_fields,
        meta_heading="Patient Information",
        sections=(spec["sections"] + image_sections + list(extra_sections)
                  + spec["closing"]),
        disclaimer=spec["disclaimer"], footer_text=spec["footer_text"])
    name = slug(meta.get("patient_id"), slug(meta.get("patient_name"), "unidentified"))
    return buffer, f"{spec['file_prefix']}_{name}.pdf"
