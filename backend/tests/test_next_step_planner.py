from app.insilicopop.planner.next_step_planner import NextStepPlanner
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


def test_broad_label_warning_creates_metadata_refinement_recommendation():
    plan = NextStepPlanner().plan([finding("broad_indian_population_labels")])

    assert "finer-grained" in plan["recommended_steps"][0]["title"]
    assert plan["recommended_steps"][0]["step_id"]


def test_admixture_narrow_k_creates_k_range_recommendation():
    plan = NextStepPlanner().plan([finding("admixture_k_sweep_too_narrow")])

    assert "K=2-10" in plan["recommended_steps"][0]["title"]


def test_selection_overclaim_creates_blocked_step():
    plan = NextStepPlanner().plan([finding("selection_overclaim_proven")])

    assert plan["blocked_steps"]
    assert plan["blocked_steps"][0]["required_fix"]

