from app.insilicopop.auditors.reliability_auditor import ReliabilityAuditor
from app.insilicopop.provenance import make_provenance
from app.schemas.insilicopop import AuditFinding


def finding(code):
    return AuditFinding(
        code=code,
        severity="warning",
        message=code,
        provenance=make_provenance(
            source_file="test.csv",
            source_section="test",
            parser_name="test_parser",
            auditor_name="TestAuditor",
            field_or_column="field",
            evidence_value=code,
            rule_id=code.upper(),
            rule_description="test",
            severity="warning",
        ),
    )


def test_score_deductions_create_matching_penalties_with_provenance():
    result = ReliabilityAuditor().evaluate([finding("tiny_population_groups"), finding("pca_ld_pruning_not_documented")])

    assert result["score"] == 80
    assert len(result["penalties"]) == 2
    assert all(penalty["provenance"] for penalty in result["penalties"])


def test_score_cannot_be_zero_with_empty_penalties():
    result = ReliabilityAuditor().evaluate([finding("selection_overclaim_proven")] * 10)

    assert result["score"] == 0
    assert result["penalties"]

