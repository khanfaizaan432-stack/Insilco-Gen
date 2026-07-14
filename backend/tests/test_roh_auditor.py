from app.insilicopop.auditors.roh_auditor import ROHAuditor
from app.insilicopop.parsers.roh_parser import parse_roh


def codes(result):
    return {finding.code for finding in result["findings"]}


def test_roh_auditor_flags_high_roh_burden():
    result = ROHAuditor().run(parse_roh("sample_id,population,total_roh_mb\nS1,Iyer,80\n"))

    assert "high_roh_burden" in codes(result)
    assert result["summary"]["high_roh_populations"] == ["Iyer"]


def test_roh_auditor_recommends_roh_ibd_analysis_if_missing():
    result = ROHAuditor().run(None)

    assert "roh_ibd_analysis_recommended" in codes(result)

