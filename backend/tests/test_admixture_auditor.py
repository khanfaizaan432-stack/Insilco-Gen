from app.insilicopop.auditors.admixture_auditor import ADMIXTUREAuditor
from app.insilicopop.parsers.admixture_parser import parse_admixture


def codes(result):
    return {finding.code for finding in result["findings"]}


def test_admixture_auditor_flags_narrow_k_sweep_and_recommends_range():
    result = ADMIXTUREAuditor().run(parse_admixture("K,cv_error\n2,0.6\n3,0.5\n"))

    assert "admixture_k_sweep_too_narrow" in codes(result)
    finding = next(f for f in result["findings"] if f.code == "admixture_k_sweep_too_narrow")
    assert finding.details["recommended"] == "K=2-10"


def test_admixture_auditor_preserves_cv_error_information():
    result = ADMIXTUREAuditor().run(parse_admixture("K,cv_error,seed\n2,0.6,1\n3,0.5,1\n"))

    assert result["summary"]["cv_errors"] == {2: 0.6, 3: 0.5}
    assert result["summary"]["best_k"] == 3

