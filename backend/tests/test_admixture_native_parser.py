from app.insilicopop.auditors.admixture_auditor import ADMIXTUREAuditor
from app.insilicopop.parsers.admixture_parser import parse_admixture_cv_log, parse_admixture_q


def test_parse_admixture_cv_log_and_best_k():
    table = parse_admixture_cv_log("CV error (K=2): 0.421\nCV error (K=3): 0.398\n", "demo.cv")
    result = ADMIXTUREAuditor().run(table)

    assert result["summary"]["k_values_tested"] == [2, 3]
    assert result["summary"]["best_k_by_cv"] == 3
    assert result["summary"]["cv_curve"] == [{"K": 2, "cv_error": 0.421}, {"K": 3, "cv_error": 0.398}]


def test_parse_admixture_q_matrix_and_missing_sample_warning():
    table = parse_admixture_q("0.90 0.10\n0.45 0.55\n", "demo.2.Q")
    result = ADMIXTUREAuditor().run(table)

    assert result["summary"]["q_matrix_shape"] == [2, 2]
    assert result["summary"]["missing_sample_order_warning"]
    assert "admixture_q_sample_order_missing" in {finding.code for finding in result["findings"]}

