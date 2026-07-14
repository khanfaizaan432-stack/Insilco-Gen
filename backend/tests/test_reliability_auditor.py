from app.insilicopop.auditors.reliability_auditor import ReliabilityAuditor
from app.schemas.insilicopop import AuditFinding


def test_trust_score_decreases_with_key_risks():
    findings = [
        AuditFinding(code="pca_ld_pruning_not_documented", severity="warning", message=""),
        AuditFinding(code="tiny_population_groups", severity="warning", message=""),
        AuditFinding(code="broad_indian_population_labels", severity="warning", message=""),
        AuditFinding(code="roh_ibd_analysis_recommended", severity="warning", message=""),
    ]

    score = ReliabilityAuditor().score(findings)

    assert score < 100
    assert score == 58

