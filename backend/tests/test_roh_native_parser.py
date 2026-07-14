from app.insilicopop.auditors.roh_auditor import ROHAuditor
from app.insilicopop.parsers.roh_parser import parse_plink_hom


def test_parse_plink_hom_and_high_roh_sample_provenance():
    table = parse_plink_hom(
        "FID IID PHE CHR SNP1 SNP2 POS1 POS2 KB NSNP DENSITY PHOM PHET\n"
        "F1 S1 1 1 rs1 rs20 1 70000 70000 20 1.2 0.98 0.01\n",
        "demo.hom",
    )
    result = ROHAuditor().run(table)

    assert result["summary"]["roh_summary_by_sample"]["S1"] == 70.0
    assert result["summary"]["roh_segment_count_by_sample"]["S1"] == 1
    assert result["summary"]["high_roh_samples"][0]["row_index"] == 0
    assert "high_roh_sample_burden" in {finding.code for finding in result["findings"]}

