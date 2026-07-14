from app.insilicopop.auditors.selection_auditor import SelectionAuditor
from app.insilicopop.parsers.selection_parser import parse_selection


def test_selection_ihs_top_region_has_row_provenance():
    table = parse_selection("chr\tposition\tgene\tihs\tp_value\n1\t123\tLCT\t2.8\t0.001\n", "demo_selection_ihs.tsv")
    result = SelectionAuditor().run(table)

    top = result["summary"]["top_candidate_regions"][0]
    assert top["region"] == "chr1:123"
    assert top["row_index"] == 0
    assert result["summary"]["correction_status"] == "not_documented"
    finding = next(finding for finding in result["findings"] if finding.code == "selection_multiple_testing_missing")
    assert finding.provenance is not None
    assert finding.provenance.provenance_id == "prov_selection_correction_missing"


def test_selection_xpehh_with_q_value_documents_correction():
    table = parse_selection("chrom\tstart\tend\tgene\txpehh\tq_value\n1\t10\t20\tLCT\t3.1\t0.03\n", "demo_selection_xpehh.tsv")
    result = SelectionAuditor().run(table)

    assert result["summary"]["top_candidate_regions"][0]["region"] == "chr1:10-20"
    assert result["summary"]["correction_status"] == "documented"
