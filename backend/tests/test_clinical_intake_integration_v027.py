from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.insilicopop.agent.loop import AgentLoop
from app.insilicopop.workflows.workflow_selector import WorkflowFamilySelector
from app.main import app


client = TestClient(app)


def clinical_payload():
    return {
        "schema_version": "0.27",
        "pseudonymous_case_id": "CASE-INTEGRATION",
        "intended_use": "clinical_genetics_research_curation",
        "redaction_declared": True,
        "reviewer_status": "in_review",
        "human_review_required": True,
        "genome_build": "GRCh38",
        "provenance": [{"source_id": "SRC-1", "source_type": "redacted_fixture"}],
        "phenotypes": [{"observation_id": "PH-1", "supplied_term": "synthetic finding", "state": "unknown"}],
        "candidate_variants": [{"candidate_id": "VAR-1", "submitted_representation": "synthetic variant", "gene": "GENE1"}],
        "pedigree": [{"family_member_id": "FAM-1", "relationship_to_proband": "proband", "affected_status": "unknown"}],
        "hypotheses": [{"hypothesis_id": "HYP-1", "hypothesis_type": "gene", "value": "GENE1"}],
    }


def test_clinical_run_creates_report_artifact_checksum_and_safe_trace(tmp_path):
    result = AgentLoop(generated_root=tmp_path).run(query="Structure this research intake", uploads={}, clinical_case_intake=clinical_payload())
    intake = result["clinical_case_intake"]
    repro = Path(result["reproducibility_bundle"]["path"])
    artifact = repro / "clinical_case_intake.json"
    report = Path(result["generated_files"]["final_report"]["absolute_path"]).read_text(encoding="utf-8")
    trace_text = json.dumps(result["agent_trace"]).lower()

    assert result["workflow_selection"]["workflow_family"] == "clinical_case_intake"
    assert result["selected_recipe"] is None
    assert artifact.is_file()
    assert "reproducibility/clinical_case_intake.json" in result["reproducibility_bundle"]["files"]
    assert "reproducibility/clinical_case_intake.json" in (repro / "checksums.sha256").read_text(encoding="utf-8")
    assert "## Clinical Case Intake Preview" in report
    assert intake["human_review_required"] is True
    assert "synthetic finding" not in trace_text
    assert result["external_llm_called"] is False
    assert result["external_tools_executed"] is False


def test_clinical_artifact_is_stable_for_equivalent_runs(tmp_path):
    first = AgentLoop(generated_root=tmp_path).run(query="Structure this research intake", uploads={}, clinical_case_intake=clinical_payload())
    second = AgentLoop(generated_root=tmp_path).run(query="Structure this research intake", uploads={}, clinical_case_intake=clinical_payload())
    first_bytes = (Path(first["reproducibility_bundle"]["path"]) / "clinical_case_intake.json").read_bytes()
    second_bytes = (Path(second["reproducibility_bundle"]["path"]) / "clinical_case_intake.json").read_bytes()
    assert hashlib.sha256(first_bytes).hexdigest() == hashlib.sha256(second_bytes).hexdigest()


def test_api_and_ui_expose_bounded_clinical_intake():
    response = client.post(
        "/insilicopop/agent/run",
        data={"query": "Structure this research intake", "clinical_case_intake": json.dumps(clinical_payload()), "llm_provider": "mock"},
    )
    assert response.status_code == 200
    body = response.json()
    run_id = body["run_id"]
    assert body["clinical_case_intake"]["pseudonymous_case_id"] == "CASE-INTEGRATION"
    detail = client.get(f"/insilicopop/agent/runs/{run_id}").json()
    assert detail["clinical_case_intake"]["intake_completeness"] == "complete"
    artifact = client.get(f"/insilicopop/agent/runs/{run_id}/artifacts/reproducibility/clinical_case_intake.json")
    assert artifact.status_code == 200
    ui = client.get("/insilicopop/workbench")
    assert "Structured clinical case intake JSON" in ui.text
    assert "renderClinicalCaseIntake" in ui.text


def test_population_workflow_selection_is_backward_compatible():
    selector = WorkflowFamilySelector()
    population = selector.select(query="Plan PCA", uploaded_files={"vcf": "cohort.vcf.gz"})
    clinical = selector.select(query="irrelevant", uploaded_files={}, clinical_intake_declared=True)
    assert population.workflow_family == "vcf_population_structure"
    assert clinical.workflow_family == "clinical_case_intake"
