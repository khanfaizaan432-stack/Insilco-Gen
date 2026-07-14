from __future__ import annotations

from pathlib import Path

import pytest

from app.insilicopop.agent.loop import AgentLoop
from app.insilicopop.orchestration import ALLOWED_GRAPH_NODES, ControlledOrchestrationGraph, validate_graph_nodes


def _run_agent(tmp_path: Path):
    return AgentLoop(generated_root=tmp_path).run(
        query="Plan a VCF population structure workflow without ancestry or clinical conclusions.",
        uploads={
            "metadata_file": {"filename": "metadata.csv", "content": b"sample_id,population\nS1,A\n"},
            "vcf_file": {"filename": "cohort.vcf.gz", "content": b"##fileformat=VCFv4.2\n"},
        },
        memory_mode="compact",
    )


def test_controlled_orchestration_node_allowlist_blocks_free_form_nodes():
    assert validate_graph_nodes(ALLOWED_GRAPH_NODES) == list(ALLOWED_GRAPH_NODES)

    with pytest.raises(ValueError, match="free_form_node"):
        validate_graph_nodes(["intake_interpretation", "free_form_node"])

    with pytest.raises(ValueError, match="external_execution"):
        ControlledOrchestrationGraph(declared_nodes=["workflow_selection", "external_execution"])


def test_agent_run_records_only_allowlisted_orchestration_nodes(tmp_path):
    result = _run_agent(tmp_path)
    trace = result["orchestration_trace"]

    assert trace["orchestration_enabled"] is True
    assert set(trace["graph_nodes_declared"]) == set(ALLOWED_GRAPH_NODES)
    assert set(trace["graph_nodes_executed"]).issubset(set(ALLOWED_GRAPH_NODES))
    assert set(trace["blocked_nodes"]).issubset(set(ALLOWED_GRAPH_NODES))
    assert "workflow_selection" in trace["graph_nodes_executed"]
    assert "claim_audit" in trace["graph_nodes_executed"]
    assert "evidence_retrieval" in trace["graph_nodes_executed"]
    assert trace["safety_flags"]["autonomous_tool_execution"] is False
    assert trace["safety_flags"]["external_tools_executed"] is False
    assert trace["safety_flags"]["external_llm_called"] is False
    assert trace["safety_flags"]["raw_genomic_files_parsed"] is False
    assert trace["safety_flags"]["human_review_required"] is True


def test_orchestration_does_not_create_unsafe_clinical_or_population_claims(tmp_path):
    result = _run_agent(tmp_path)
    report = Path(result["generated_files"]["final_report"]["absolute_path"]).read_text(encoding="utf-8").lower()

    unsafe_positive_claims = [
        "treatment recommended",
        "diagnosis confirmed",
        "final acmg classification is",
        "this variant is pathogenic",
        "caste inferred",
        "genetic purity confirmed",
        "consumer ancestry assigned",
    ]
    assert all(claim not in report for claim in unsafe_positive_claims)
    assert "controlled orchestration preview" in report
    assert "human review required" in report
