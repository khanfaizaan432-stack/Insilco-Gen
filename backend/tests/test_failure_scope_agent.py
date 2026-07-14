from app.insilicopop.agent.actions import make_action
from app.insilicopop.agent.failure_scope import FailureScope


def test_failure_scope_detects_unsafe_selection_and_ld_pruning_and_admixture():
    failures = FailureScope().evaluate(
        risk_flags=[
            {"code": "selection_overclaim_proven", "provenance": {"rule_id": "selection"}},
            {"code": "pca_ld_pruning_not_documented", "provenance": {"rule_id": "pca"}},
            {"code": "admixture_k_sweep_too_narrow", "provenance": {"rule_id": "admix"}},
        ],
        actions=[],
        carried_memory={"dependency_capsules": [{"capsule_id": "x"}]},
    )
    types = {failure["failure_type"] for failure in failures}

    assert "unsupported_selection_claim" in types
    assert "missing_ld_pruning" in types
    assert "missing_admixture_stability_check" in types


def test_failure_scope_detects_missing_provenance_for_key_warning():
    failures = FailureScope().evaluate(
        risk_flags=[{"code": "selection_multiple_testing_missing", "provenance": None}],
        actions=[make_action(1, "dry_run_selection_scan", "Selection", "Plan")],
        carried_memory={"dependency_capsules": [{"capsule_id": "x"}]},
    )

    assert any(failure["failure_type"] == "provenance_missing_for_key_warning" for failure in failures)

