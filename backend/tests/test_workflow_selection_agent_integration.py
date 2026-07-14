import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.insilicopop.agent.loop import AgentLoop
from app.main import app


client = TestClient(app)


def test_agent_response_includes_workflow_selection_and_generated_artifact():
    result = AgentLoop().run(
        query="audit these PCA outputs",
        uploads={"smartpca_evec": {"filename": "demo.evec", "content": b"S1 0.1 0.2 Pop\n"}},
        memory_mode="compact",
    )

    assert result["workflow_selection"]["workflow_family"] == "results_only_audit"
    assert result["selected_recipe"]["recipe_id"] == "results_only_audit_basic"
    artifact = result["generated_files"]["workflow_selection"]
    assert artifact["created"] is True
    saved = json.loads(Path(artifact["absolute_path"]).read_text(encoding="utf-8"))
    assert saved["workflow_family"] == "results_only_audit"


def test_agent_endpoint_vcf_upload_selects_vcf_population_structure_and_preserves_mock_metadata():
    response = client.post(
        "/insilicopop/agent/run",
        data={"query": "plan PCA and ADMIXTURE", "memory_mode": "compact"},
        files={
            "metadata_file": ("metadata.csv", b"sample_id,population\nS1,A\n", "text/csv"),
            "vcf_file": ("cohort.vcf.gz", b"##fileformat=VCFv4.2\n", "application/gzip"),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["workflow_selection"]["workflow_family"] == "vcf_population_structure"
    assert body["selected_recipe"]["recipe_id"] == "vcf_population_structure_basic"
    assert body["llm_provider"] == "mock"
    assert body["external_llm_called"] is False
    assert body["external_tools_executed"] is False
