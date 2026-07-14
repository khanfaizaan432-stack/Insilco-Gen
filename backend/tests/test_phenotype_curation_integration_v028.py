import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.insilicopop.agent.loop import AgentLoop


client = TestClient(app)
FULL_SNIPPET = "No seizures; progressive short stature in this fictional redacted research summary."


def clinical_payload():
    return {
        "schema_version": "0.27",
        "pseudonymous_case_id": "CASE-V028-INTEGRATION",
        "intended_use": "clinical_genetics_research_curation",
        "redaction_declared": True,
        "reviewer_status": "pending",
        "human_review_required": True,
        "genome_build": "GRCh38",
        "provenance": [{"source_id": "SRC-1", "source_type": "synthetic_fixture"}],
        "phenotypes": [{"observation_id": "PH-1", "supplied_term": "fictional finding", "state": "unknown"}],
        "candidate_variants": [{"candidate_id": "VAR-1", "submitted_representation": "synthetic variant", "gene": "GENE1"}],
        "phenotype_curation": {"snippets": [{
            "snippet_id": "SNIP-1",
            "redaction_declared": True,
            "redacted_text": FULL_SNIPPET,
            "source_label": "synthetic fixture",
            "provenance": [{"source_id": "SNIP-SRC", "source_type": "synthetic_redacted_fixture"}],
        }]},
    }


def test_clinical_run_writes_safe_deterministic_artifact_report_trace_and_lock(tmp_path):
    first = AgentLoop(generated_root=tmp_path).run(query="Structure this research intake", uploads={}, clinical_case_intake=clinical_payload())
    second = AgentLoop(generated_root=tmp_path).run(query="Structure this research intake", uploads={}, clinical_case_intake=clinical_payload())
    first_repro = Path(first["reproducibility_bundle"]["path"])
    second_repro = Path(second["reproducibility_bundle"]["path"])
    artifact = first_repro / "phenotype_hpo_curation.json"
    report = Path(first["generated_files"]["final_report"]["absolute_path"]).read_text(encoding="utf-8")
    state_text = Path(first["generated_files"]["agent_state"]["absolute_path"]).read_text(encoding="utf-8")
    trace_text = json.dumps(first["agent_trace"])
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert artifact.is_file()
    assert "reproducibility/phenotype_hpo_curation.json" in first["reproducibility_bundle"]["files"]
    assert "reproducibility/phenotype_hpo_curation.json" in (first_repro / "checksums.sha256").read_text(encoding="utf-8")
    assert "## Phenotype and HPO Curation Preview" in report
    assert FULL_SNIPPET not in report and FULL_SNIPPET not in state_text and FULL_SNIPPET not in trace_text
    assert FULL_SNIPPET not in artifact.read_text(encoding="utf-8")
    assert payload["source_snippets"][0]["text_sha256"] == hashlib.sha256(FULL_SNIPPET.encode()).hexdigest()
    assert payload["hpo_suggestions"][0]["matched_substring"] == "seizures"
    lock = json.loads((first_repro / "runtime_lock.json").read_text(encoding="utf-8"))
    assert lock["hpo_registry_version"] == payload["registry_version"]
    first_bytes = artifact.read_bytes()
    second_bytes = (second_repro / "phenotype_hpo_curation.json").read_bytes()
    assert hashlib.sha256(first_bytes).hexdigest() == hashlib.sha256(second_bytes).hexdigest()


def test_clinical_branch_does_not_call_population_retrieval_llm_parser_or_tools(tmp_path, monkeypatch):
    import app.insilicopop.agent.loop as loop_module

    def forbidden(*args, **kwargs):
        raise AssertionError("forbidden subsystem called")

    monkeypatch.setattr(loop_module, "retrieve_evidence", forbidden)
    monkeypatch.setattr(loop_module, "build_llm_provider", forbidden)
    monkeypatch.setattr(loop_module.InSilicoPopAuditService, "run", forbidden)
    monkeypatch.setattr(loop_module.ToolRouter, "run", forbidden, raising=False)
    result = AgentLoop(generated_root=tmp_path).run(query="Structure this research intake", uploads={}, clinical_case_intake=clinical_payload())
    assert result["workflow_selection"]["workflow_family"] == "clinical_case_intake"
    assert result["selected_recipe"] is None
    assert result["external_llm_called"] is False
    assert result["external_tools_executed"] is False


def test_api_workbench_and_stored_runs_expose_bounded_optional_curation():
    response = client.post(
        "/insilicopop/agent/run",
        data={"query": "Structure this research intake", "clinical_case_intake": json.dumps(clinical_payload()), "llm_provider": "mock"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["phenotype_hpo_curation"]["hpo_suggestions"][0]["hpo_id"] == "HP:0001250"
    assert FULL_SNIPPET not in json.dumps(body)
    detail = client.get(f"/insilicopop/agent/runs/{body['run_id']}").json()
    assert detail["hpo_suggestion_count"] == 2
    assert detail["hpo_curation_artifact_available"] is True
    assert detail["phenotype_hpo_curation"]["hpo_suggestions"][0]["matched_substring"] == "seizures"
    ui = client.get("/insilicopop/workbench").text
    assert "Phenotype and HPO curation preview" in ui
    assert "renderPhenotypeHpoCuration" in ui


def test_v027_payload_without_curation_remains_compatible(tmp_path):
    data = clinical_payload()
    data.pop("phenotype_curation")
    result = AgentLoop(generated_root=tmp_path).run(query="Structure this research intake", uploads={}, clinical_case_intake=data)
    assert result["clinical_case_intake"]["schema_version"] == "0.27"
    assert result["phenotype_hpo_curation"] is None
    assert "reproducibility/phenotype_hpo_curation.json" not in result["reproducibility_bundle"]["files"]
