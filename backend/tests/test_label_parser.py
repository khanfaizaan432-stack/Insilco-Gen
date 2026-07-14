import pytest

from app.bio.label_parser import parse_labels


def test_parse_labels_required_columns():
    labels = parse_labels("sample_id,label\ns1,resistant\ns2,susceptible\n")

    assert [label.sample_id for label in labels] == ["s1", "s2"]
    assert labels[0].label == "resistant"


def test_parse_labels_rejects_missing_required_column():
    with pytest.raises(ValueError, match="label"):
        parse_labels("sample_id\ns1\n")

