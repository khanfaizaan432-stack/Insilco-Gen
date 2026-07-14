from app.insilicopop.llm.action_validator import ActionValidator
from app.insilicopop.llm.schemas import LLMActionProposal


def _validate(proposal, flags, uploaded=None):
    return ActionValidator().validate(
        proposal,
        risk_flags=[{"code": code, "provenance": {"rule_id": code, "provenance_id": code}} for code in flags],
        carried_memory={"downstream_dependencies": ["LD pruning status"]},
        uploaded_files=uploaded or {},
    )


def test_selection_overclaim_is_blocked():
    result = _validate(
        LLMActionProposal(action_type="interpret_selection", rationale="Interpret", claim_intent="selection is proven"),
        ["selection_multiple_testing_missing"],
    )

    assert result.status == "blocked"
    assert result.blocking_reasons


def test_admixture_narrow_k_is_modified_to_k_2_10():
    result = _validate(LLMActionProposal(action_type="run_admixture", rationale="Run ADMIXTURE"), ["admixture_k_sweep_too_narrow"])

    assert result.status == "modified"
    assert result.final_action["action_type"] == "dry_run_admixture"
    assert result.final_action["k_range"] == "2-10"


def test_pca_unknown_ld_pruning_is_modified_to_ld_pruning_first():
    result = _validate(LLMActionProposal(action_type="interpret_pca", rationale="Interpret PCA"), ["pca_ld_pruning_not_documented"])

    assert result.status == "modified"
    assert result.final_action["action_type"] == "dry_run_ld_pruning"


def test_fst_strong_claim_with_tiny_populations_is_blocked():
    result = _validate(
        LLMActionProposal(action_type="interpret_fst", rationale="Strong differentiation", claim_intent="strong differentiation claim"),
        ["fst_tiny_sample_size_caveat"],
    )

    assert result.status == "blocked"


def test_missing_genotype_allows_dry_run_but_not_execution():
    result = _validate(LLMActionProposal(action_type="run_admixture", rationale="Run ADMIXTURE"), [], uploaded={})

    assert result.status == "modified"
    assert result.final_action["execution_enabled"] is False
    assert "dry_run_only_reason" in result.final_action

