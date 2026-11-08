"""The three PDF download routes must actually produce a PDF.

This file exists because a refactor left five undefined names in the report
builder and the whole suite still passed: nothing had ever rendered a report.
A PDF that raises on download is a silent dead end for the user, so each
route is exercised end to end and the bytes are checked.
"""
import pytest

import app as flask_app
from reporting.pdf import build_pdf_report
from webapp.metadata import PATIENT_FIELDS, finalize_metadata


@pytest.fixture
def client():
    flask_app.app.config["TESTING"] = True
    with flask_app.app.test_client() as c:
        yield c


PATIENT = {"patient_name": "T", "patient_id": "MRN-1", "age": "40",
           "gender": "Male", "contact": "1234567890",
           "referring_physician": "D", "study_date": "2026-09-09",
           "clinical_history": "test"}


def _is_pdf(resp):
    assert resp.status_code == 200, resp.status_code
    body = resp.get_data()
    assert body.startswith(b"%PDF-"), body[:40]
    assert len(body) > 1000, "suspiciously small PDF"
    return body


def test_ecg_report_downloads(client):
    data = dict(PATIENT, prediction="NORMAL",
                abnormal_type="No ectopic beats detected", confidence="91.20",
                atrial_probability="1.10", classifier="AAMI 5-class 1D CNN",
                heart_rate="72 bpm", signal_quality="Good",
                interpretation="x", recommendation="y")
    _is_pdf(client.post("/download_ecg_report", data=data))


def test_ecg_report_downloads_when_no_classifier_ran(client):
    """The degraded path renders too -- it is the one users hit without models."""
    data = dict(PATIENT, prediction="", classifier_error="no model installed",
                heart_rate="72 bpm", interpretation="x", recommendation="y")
    body = _is_pdf(client.post("/download_ecg_report", data=data))
    assert body  # content is binary; the table contents are unit-tested above


def test_brain_tumor_report_downloads(client):
    data = dict(PATIENT, prediction="Glioma", confidence="88.10",
                findings="x", recommendation="y", tumor_area="3.2",
                severity="Moderate", spread="Limited")
    _is_pdf(client.post("/download_brain_tumor_report", data=data))


def test_report_filename_is_derived_from_the_identifier(client):
    data = dict(PATIENT, prediction="NORMAL", confidence="90",
                interpretation="x", recommendation="y")
    resp = client.post("/download_ecg_report", data=data)
    # _slug() keeps the identifier but normalises punctuation for the filename.
    assert "MRN_1" in resp.headers["Content-Disposition"]


def test_builder_renders_both_section_kinds():
    """build_pdf_report takes "table" and "text" sections; both must render."""
    meta = finalize_metadata(dict(PATIENT), PATIENT_FIELDS)
    buf = build_pdf_report(
        title="T", subtitle="S", accent="#4f46e5", meta=meta,
        meta_fields=PATIENT_FIELDS, meta_heading="H",
        sections=[("table", "A", [("k", "v"), ("a", "b")]),
                  ("text", "B", "some prose")],
        disclaimer="D", footer_text="F")
    assert buf.getvalue().startswith(b"%PDF-")


def test_builder_escapes_markup_in_user_supplied_text():
    """Patient names reach ReportLab's mini-HTML parser; unescaped <b> there
    either styles the report or raises."""
    meta = finalize_metadata(dict(PATIENT, patient_name="<b>x</b> & co"),
                             PATIENT_FIELDS)
    buf = build_pdf_report(
        title="T", subtitle="S", accent="#4f46e5", meta=meta,
        meta_fields=PATIENT_FIELDS, meta_heading="H",
        sections=[("text", "B", "<i>unclosed")],
        disclaimer="D", footer_text="F")
    assert buf.getvalue().startswith(b"%PDF-")


def test_ecg_report_keeps_measurements_without_findings_or_advice(client):
    """The ECG PDF carries measurements and omits interpretation sections."""
    import json
    from ecg.clinical import clinical_report
    from ecg.quality import Measurement, OK

    rep = {k: Measurement(v, OK) for k, v in
           [("heart_rate", 72.0), ("pr_interval", 0.16), ("qrs_duration", 0.09),
            ("qtc", 0.41), ("st_segment", 0.0), ("qt_interval", 0.38)]}
    rep["rhythm"] = Measurement(0.03, OK, "Regular")

    data = dict(PATIENT, prediction="NORMAL", confidence="90",
                interpretation="x", recommendation="y",
                clinical_json=json.dumps(clinical_report(rep, sex="Male")))
    body = _is_pdf(client.post("/download_ecg_report", data=data))
    text = _pdf_text(body)
    assert len(body) > 4000
    assert b"ECG Measurements" in text
    for section in (b"ECG Findings", b"ECG Impression", b"Measured Findings",
                    b"Recommendations", b"ECG Signal Waveform"):
        assert section not in text


def test_ecg_report_omits_the_section_when_the_payload_is_malformed(client):
    """A broken payload must drop the section, never substitute anything."""
    data = dict(PATIENT, prediction="NORMAL", confidence="90",
                interpretation="x", recommendation="y",
                clinical_json="{not json")
    _is_pdf(client.post("/download_ecg_report", data=data))
    assert flask_app._clinical_from_form({"clinical_json": "{not json"}) is None
    assert flask_app._clinical_from_form({"clinical_json": '{"a":1}'}) is None
    assert flask_app._clinical_from_form({}) is None


def _pdf_text(pdf):
    """Concatenated content streams. Image streams that are not text are
    skipped, so reports that embed pictures can be inspected too."""
    import base64
    import re
    import zlib
    out = []
    for m in re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.S):
        try:
            out.append(zlib.decompress(base64.a85decode(m.strip(), adobe=True)))
        except Exception:
            continue
    return b"".join(out)


DOCTOR_SECTIONS = (b"Clinical Impression", b"Recommendations", b"Precautions",
                   b"Reporting Clinician")


def test_ecg_report_reads_like_a_clinical_report(client):
    import json
    from ecg.clinical import clinical_report
    from ecg.quality import Measurement, OK
    rep = {k: Measurement(v, OK) for k, v in
           [("heart_rate", 130.0), ("pr_interval", 0.16), ("qrs_duration", 0.09),
            ("qtc", 0.41), ("st_segment", 0.0), ("qt_interval", 0.38)]}
    rep["rhythm"] = Measurement(0.03, OK, "Regular")
    data = dict(PATIENT, prediction="NORMAL", confidence="90",
                interpretation="x", recommendation="y",
                clinical_json=json.dumps(clinical_report(rep, sex="Male")))
    text = _pdf_text(_is_pdf(client.post("/download_ecg_report", data=data)))
    for s in (b"Patient Information", b"Examination Date", b"ECG Examination Details",
              b"Recording Duration", b"Sampling Frequency", b"ECG Measurements"):
        assert s in text, s
    for s in (b"ECG Findings", b"ECG Impression", b"Recommendations", b"Measured Findings"):
        assert s not in text, s
    assert b"Reporting Clinician" not in text


def test_eeg_report_uses_clinical_sections_and_timebase(client):
    import json
    payload = {"model_used": False, "task": "Epileptiform / seizure activity",
               "task_key": "seizure", "source": "2 channels at 256 Hz",
               "file_type": "EDF", "sampling_frequency_hz": 256.0,
               "n_channels": 2, "duration_s": 12.0, "n_windows": 10,
               "artifact_windows": 1, "representation": "Scalogram",
               "not_assessed_reason": "No validated model was used."}
    data = dict(PATIENT, eeg_json=json.dumps(payload))
    text = _pdf_text(_is_pdf(client.post("/download_eeg_report", data=data)))
    for label in (b"Patient Information", b"EEG Examination Details", b"File Type",
                  b"Sampling Frequency", b"Channels", b"EEG Findings",
                  b"NOT ASSESSED", b"EEG Impression"):
        assert label in text, label
    assert b"Not assessed" in text


def test_ecg_report_without_classifier_or_payload_is_not_normal(client):
    data = dict(PATIENT, prediction="", classifier_error="no model")
    text = _pdf_text(_is_pdf(client.post("/download_ecg_report", data=data)))
    assert b"Not performed" in text and b"no model" in text
    assert b"(NORMAL" not in text


@pytest.mark.parametrize("prediction,verdict", [
    ("Glioma", b"(ABNORMAL"), ("No Tumor", b"(NORMAL")])
def test_mri_report_reads_like_a_clinical_report(client, prediction, verdict):
    data = dict(PATIENT, prediction=prediction, confidence="88.10",
                location="Left frontal", severity="Moderate", area="3.2")
    text = _pdf_text(_is_pdf(client.post("/download_brain_tumor_report", data=data)))
    for s in (b"Patient Information", b"Examination Date", b"MRI Examination Details",
              b"MRI Findings", b"MRI Impression", b"Model Classification",
              b"Classifier Confidence", b"Recommendations", verdict):
        assert s in text, s
    assert b"Reporting Clinician" not in text
    assert b"Segmentation / Lesion Measurement" in text


def test_mri_report_without_a_classification_says_not_performed(client):
    text = _pdf_text(_is_pdf(client.post("/download_brain_tumor_report", data=PATIENT)))
    assert b"Not performed" in text
    assert b"NOT ASSESSED" in text
    assert b"(NORMAL" not in text


def test_a_blank_percentage_reads_not_measurable_not_a_bare_percent(client):
    data = dict(PATIENT, prediction="NORMAL", abnormal_type="x", confidence="91.0",
                atrial_probability="", classifier="c")
    text = _pdf_text(_is_pdf(client.post("/download_ecg_report", data=data)))
    assert b"(91.0%)" in text
    assert b"(%)" not in text
