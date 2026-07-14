from app.insilicopop.llm.mock_provider import MockLLMProvider
from app.insilicopop.llm.prompt_builder import build_orchestration_prompt


def test_mock_llm_provider_returns_structured_proposal_without_external_call():
    provider = MockLLMProvider()
    proposals = provider.propose_actions(
        compact_memory={"facts": ["narrow K"], "dependency_capsules": []},
        audit_summary={"risk_flags": [{"code": "admixture_k_sweep_too_narrow"}]},
        query=None,
    )

    assert proposals[0].action_type == "run_admixture"
    assert proposals[0].confidence > 0
    assert provider.external_call_made is False


def test_prompt_is_built_from_compact_memory_not_raw_files():
    prompt = build_orchestration_prompt(
        compact_memory={"facts": ["LD pruning unknown"]},
        audit_summary={"reliability_score": 80, "risk_flags": []},
        query="pca",
    )

    assert prompt["raw_files_included"] is False
    assert "compact_memory" in prompt
    assert "raw_files" not in prompt

