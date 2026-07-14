from app.insilicopop.auditors.metadata_auditor import MetadataAuditor
from app.insilicopop.parsers.metadata_parser import parse_metadata


def codes(audit):
    return {finding.code for finding in audit.findings}


def test_metadata_auditor_flags_tiny_groups():
    table = parse_metadata("sample_id,population\nS1,Iyer\nS2,Gujarati Patel\n")

    audit = MetadataAuditor().run(table)

    assert "tiny_population_groups" in codes(audit)


def test_metadata_auditor_flags_severe_imbalance():
    csv = "\n".join(
        ["sample_id,population", "S1,A"]
        + [f"S{i},B" for i in range(2, 12)]
    )

    audit = MetadataAuditor().run(parse_metadata(csv))

    assert "severe_population_imbalance" in codes(audit)


def test_metadata_auditor_flags_broad_indian_labels():
    table = parse_metadata("sample_id,population\nS1,North Indian\nS2,South Indian\n")

    audit = MetadataAuditor().run(table)

    assert "broad_indian_population_labels" in codes(audit)

