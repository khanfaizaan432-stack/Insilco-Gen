from __future__ import annotations

import json
from pathlib import Path

from app.insilicopop.agent.loop import AgentLoop


def _run_agent(tmp_path: Path):
    return AgentLoop(generated_root=tmp_path).run(
        query="Audit existing PCA outputs and keep conclusions caveated.",
        uploads={
            "pca": {"filename": "pca_results.csv", "content": b"sample,pc1,pc2\nS1,0.1,0.2\n"},
            "metadata_file": {"filename": "metadata.csv", "content": b"sample_id,population\nS1,A\n"},
        },
        memory_mode="compact",
    )


def test_orchestration_trace_json_report_and_checksums_are_generated(tmp_path):
    result = _run_agent(tmp_path)
    repro_dir = Path(result["reproducibility_bundle"]["path"])
    artifact = repro_dir / "orchestration_trace.json"

    assert artifact.is_file()
    assert "reproducibility/orchestration_trace.json" in result["reproducibility_bundle"]["files"]

    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["run_id"] == result["run_id"]
    assert payload["orchestration_enabled"] is True
    assert payload["graph_nodes_declared"]
    assert payload["graph_nodes_executed"]
    assert payload["graph_edges_declared"]
    assert payload["raw_content_recorded"] is False
    assert payload["final_decisions_recorded"] is False
    assert payload["safety_flags"]["external_api_call_made"] is False
    assert payload["safety_flags"]["biological_or_clinical_conclusion_made"] is False
    assert payload["safety_flags"]["human_review_required"] is True

    node = payload["node_statuses"][0]
    assert "input_summary" in node
    assert "output_summary" in node
    assert "content" not in json.dumps(node).lower()

    report = Path(result["generated_files"]["final_report"]["absolute_path"]).read_text(encoding="utf-8")
    assert "## Controlled Orchestration Preview" in report
    assert "orchestration is bounded" in report
    assert "no autonomous tool execution occurred" in report
    assert "no external LLM/API call was made by default" in report
    assert "deterministic audits remain authoritative" in report

    checksums = (repro_dir / "checksums.sha256").read_text(encoding="utf-8")
    assert "reproducibility/orchestration_trace.json" in checksums


def test_orchestration_trace_preserves_existing_audit_outputs(tmp_path):
    result = _run_agent(tmp_path)

    assert result["claim_audit"]["human_review_required"] is True
    assert result["data_governance_audit"]["human_review_required"] is True
    assert result["metadata_registry_audit"]["human_review_required"] is True
    assert result["evidence_retrieval"]["local_only"] is True
    assert result["external_llm_called"] is False
    assert result["external_tools_executed"] is False
