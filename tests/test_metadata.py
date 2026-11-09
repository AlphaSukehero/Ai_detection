from webapp.metadata import PATIENT_FIELDS, collect_metadata


def test_fractional_age_is_rejected_instead_of_truncated():
    values, errors = collect_metadata({"age": "40.5"}, PATIENT_FIELDS)
    assert values["age"] == ""
    assert "Age must be a whole number" in errors[0]
