import app as flask_app
from app import load_ecg_file


def _post(client, path, extra):
    data = {"patient_name": "T", "patient_id": "1", "age": "40",
            "gender": "Male", "contact": "1234567890",
            "referring_physician": "D", "study_date": "2026-09-09",
            "clinical_history": "test"}
    data.update(extra)
    return client.post(path, data=data, content_type="multipart/form-data")


def test_ecg_csv_refuses_non_finite_samples(tmp_path):
    path = tmp_path / "invalid.csv"
    path.write_text("1.0\ninf\n2.0\n")
    try:
        load_ecg_file(str(path))
    except ValueError as exc:
        assert "non-finite" in str(exc)
    else:
        raise AssertionError("non-finite ECG samples should be refused")


def test_ecg_route_still_renders_successfully():
    """Task 13 replaces the parameter source; the template labels for Rhythm,
    ST Segment and QRS Axis arrive in Task 14, so they are asserted there."""
    flask_app.app.config["TESTING"] = True
    with flask_app.app.test_client() as client:
        resp = _post(client, "/analyze_ecg", {"sample_type": "normal"})
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "ECG Waveform Parameters" in html


def test_pr_is_no_longer_the_hardcoded_constant():
    flask_app.app.config["TESTING"] = True
    with flask_app.app.test_client() as client:
        resp = _post(client, "/analyze_ecg", {"sample_type": "normal"})
        html = resp.get_data(as_text=True)
        assert "145.0 ms" not in html


def test_ecg_page_reports_new_parameters():
    """The three parameters the app never computed before must now appear."""
    flask_app.app.config["TESTING"] = True
    with flask_app.app.test_client() as client:
        resp = _post(client, "/analyze_ecg", {"sample_type": "normal"})
        html = resp.get_data(as_text=True)
        assert resp.status_code == 200
        for label in ["Rhythm", "ST Segment", "QRS Axis"]:
            assert label in html, label


from app import _signal_quality
from ecg.quality import Measurement, OK, LOW, UNAVAILABLE


def _report(**flags):
    keys = ["heart_rate", "rhythm", "pr_interval", "qrs_duration",
            "qt_interval", "qtc", "st_segment", "axis"]
    return {k: Measurement(None if flags.get(k, UNAVAILABLE) == UNAVAILABLE
                           else 1.0, flags.get(k, UNAVAILABLE))
            for k in keys}


def test_signal_quality_good_needs_most_parameters_measured():
    assert _signal_quality(_report(**{k: OK for k in [
        "heart_rate", "rhythm", "pr_interval", "qrs_duration",
        "qt_interval", "qtc"]})) == "Good"


def test_signal_quality_not_good_when_only_the_rate_is_known():
    """A heart rate alone used to report "Good" while everything else was —."""
    assert _signal_quality(_report(heart_rate=OK)) != "Good"
    assert _signal_quality(_report(heart_rate=OK)) == "Insufficient data"


def test_signal_quality_partial_for_a_middling_report():
    assert _signal_quality(_report(heart_rate=OK, rhythm=OK,
                                   qrs_duration=LOW)) == "Partial"


def test_signal_quality_insufficient_when_nothing_measured():
    assert _signal_quality(_report()) == "Insufficient data"
