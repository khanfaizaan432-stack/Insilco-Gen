from app.insilicopop.auditors.metadata_auditor import MetadataAuditor
from app.insilicopop.parsers.metadata_parser import (
    detect_population_column,
    detect_sample_id_column,
    parse_metadata,
)


def codes(audit):
    return {finding.code for finding in audit.findings}


def test_metadata_parser_detects_sample_and_population_columns():
    table = parse_metadata("sample_id,population\nS1,Iyer\nS2,Iyer\n")

    assert detect_sample_id_column(table) == "sample_id"
    assert detect_population_column(table) == "population"


def test_metadata_audit_detects_duplicate_sample_ids():
    table = parse_metadata("sample_id,population\nS1,Iyer\nS1,Iyer\n")

    audit = MetadataAuditor().run(table)

    assert "duplicate_sample_ids" in codes(audit)


def test_metadata_audit_detects_missing_population_labels():
    table = parse_metadata("sample_id,population\nS1,Iyer\nS2,\n")

    audit = MetadataAuditor().run(table)

    assert "missing_population_labels" in codes(audit)

