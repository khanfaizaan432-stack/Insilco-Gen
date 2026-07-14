from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_workbench_route_returns_static_ui():
    response = client.get("/insilicopop/workbench")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "InSilicoPop Local Workbench" in response.text


def test_workbench_page_includes_required_safety_copy_and_dry_run_warning():
    response = client.get("/insilicopop/workbench")

    assert response.status_code == 200
    assert (
        "InSilicoPop is a research workflow assistant. It does not diagnose, "
        "recommend treatment, infer caste/community/religion, or make consumer ancestry claims. "
        "All outputs require human expert review."
    ) in response.text
    assert "DRY-RUN ONLY — external genomics tools are not executed." in response.text
    assert "Mock LLM provider by default" in response.text
    assert "Human review required" in response.text
    assert "Research use only" in response.text
    assert "Human Review Required" in response.text
    assert (
        "The system proposes workflow steps and audits outputs, but a qualified researcher must approve "
        "interpretations and decide whether any commands should ever be executed outside the dry-run demo."
    ) in response.text


def test_workbench_page_includes_required_sections_and_local_api_usage():
    response = client.get("/insilicopop/workbench")

    assert response.status_code == 200
    expected_sections = [
        "1. Research Goal Form",
        "2. Input Inventory Form",
        "3. Run Result Summary",
        "4. Workflow Selection Panel",
        "5. Planned Actions / Dry-Run Command Preview Panel",
        "6. Blocked Actions / Safety Notes Panel",
        "7. Final Report Viewer",
        "8. Reproducibility Bundle Viewer/List",
        "9. Run History List",
        "Recipe Preview",
        "Recipe-aware claim audit",
        "Data governance audit",
        "Metadata registry audit",
        "Evidence retrieval preview",
        "Results-only audit preview",
    ]
    for section in expected_sections:
        assert section in response.text
    assert 'formData.append("query"' in response.text
    assert "appendGovernanceScope(formData)" in response.text
    assert "appendMetadataRegistry(formData)" in response.text
    assert 'formData.append("llm_provider", "mock")' in response.text
    assert 'requestJson("/insilicopop/agent/run"' in response.text
    assert "/insilicopop/agent/runs" in response.text


def test_workbench_page_includes_v017_error_handling_and_status_fields():
    response = client.get("/insilicopop/workbench")

    assert response.status_code == 200
    expected_terms = [
        "Agent run returned a malformed response.",
        "Agent run completed but did not return a run_id.",
        "Workflow selection could not be loaded.",
        "Final report could not be loaded.",
        "Reproducibility bundle could not be loaded.",
        "Artifact list could not be loaded.",
        "Run history returned a malformed response.",
        "Artifact could not be loaded.",
        "external_llm_called",
        "external_tools_executed",
        "human_review_required",
        "artifact_count",
        "confidence",
        "selected_recipe",
        "recipe_maturity_tier",
        "Dry-run recipe preview only",
        "renderClaimAudit",
        "renderDataGovernanceAudit",
        "renderMetadataRegistryAudit",
        "renderEvidenceRetrieval",
        "renderOrchestrationTrace",
        "renderResultsAudit",
        "blocked_interpretations",
        "No data governance audit loaded.",
        "No metadata registry audit loaded.",
        "No evidence retrieval preview loaded.",
        "No controlled orchestration trace loaded.",
        "Controlled orchestration preview",
        "must be valid JSON object text.",
        "No results-only audit loaded.",
    ]
    for term in expected_terms:
        assert term in response.text


def test_workbench_page_has_no_external_script_or_cdn_urls():
    response = client.get("/insilicopop/workbench")

    assert response.status_code == 200
    assert "https://cdn" not in response.text.lower()
    assert "http://cdn" not in response.text.lower()
    assert 'src="http://' not in response.text.lower()
    assert 'src="https://' not in response.text.lower()
    assert "node_modules" not in response.text
    assert "package-lock" not in response.text
    assert "document.getElementById(\"artifact-content\").textContent" in response.text


def test_workbench_artifact_path_traversal_protection_remains_intact():
    run_response = client.post(
        "/insilicopop/agent/run",
        data={"query": "Plan a dry-run VCF population structure workflow", "memory_mode": "compact"},
        files={
            "metadata_file": ("metadata.csv", b"sample_id,population\nS1,A\n", "text/csv"),
            "vcf_file": ("cohort.vcf.gz", b"inventory placeholder only\n", "text/plain"),
        },
    )
    assert run_response.status_code == 200
    run_id = run_response.json()["run_id"]

    traversal = client.get(f"/insilicopop/agent/runs/{run_id}/artifacts/reproducibility/%2E%2E/agent_state.json")

    assert traversal.status_code == 403
