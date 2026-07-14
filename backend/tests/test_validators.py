from app.bio.fasta_parser import parse_fasta
from app.bio.label_parser import parse_labels
from app.bio.validators import validate_dataset


def finding_codes(report):
    return {finding.code for finding in report.findings}


def test_missing_labels():
    records = parse_fasta(">s1\nATGC\n>s2\nTTAA\n")
    labels = parse_labels("sample_id,label\ns1,resistant\n")

    report = validate_dataset(records, labels)

    assert "missing_labels" in finding_codes(report)
    assert not report.passed


def test_duplicate_sequences():
    records = parse_fasta(">s1\nATGC\n>s2\nATGC\n")
    labels = parse_labels("sample_id,label\ns1,resistant\ns2,resistant\n")

    report = validate_dataset(records, labels)

    assert "duplicate_biological_sequences" in finding_codes(report)
    assert report.passed


def test_conflicting_labels_for_identical_sequences():
    records = parse_fasta(">s1\nATGC\n>s2\nATGC\n")
    labels = parse_labels("sample_id,label\ns1,resistant\ns2,susceptible\n")

    report = validate_dataset(records, labels)

    assert "conflicting_labels_for_identical_sequences" in finding_codes(report)
    assert not report.passed

