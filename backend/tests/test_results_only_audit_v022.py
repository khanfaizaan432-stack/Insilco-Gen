from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.insilicopop.agent.loop import AgentLoop
from app.main import app


client = TestClient(app)


def run_agent(tmp_path: Path, query: str, uploads: dict[str, dict[str, bytes | str] | None]) -> dict[str, object]:
    return AgentLoop(generated_root=tmp_path).run(
        query=query,
        uploads=uploads,
        max_steps=8,
        memory_budget_chars=1500,
        memory_mode="compact",
        llm_provider="mock",
    )


def results_only_uploads() -> dict[str, dict[str, bytes | str]]:
    return {
        "result_pca_evec_file": {"content": b"placeholder\n", "filename": "demo.evec"},
        "result_pca_eval_file": {"content": b"placeholder\n", "filename": "demo.eval"},
        "result_admixture_q_file": {"content": b"placeholder\n", "filename": "demo.3.Q"},
        "result_admixture_cv_file": {"content": b"placeholder\n", "filename": "demo_admixture.cv"},
        "result_plink_hom_file": {"content": b"placeholder\n", "filename": "demo.hom"},
        "result_manuscript_claims_file": {"content": b"placeholder\n", "filename": "claims.md"},
    }


def test_results_audit_generated_for_results_only_runs(tmp_path):
    result = run_agent(tmp_path, "audit existing PCA ADMIXTURE PLINK outputs and manuscript claims", results_only_uploads())
    results_audit = result["results_audit"]

    assert result["workflow_selection"]["workflow_family"] == "results_only_audit"
    assert results_audit["workflow_family"] == "results_only_audit"
    assert results_audit["selected_recipe_id"] == "results_only_audit_basic"
    assert results_audit["dry_run_only"] is True
    assert results_audit["human_review_required"] is True
    assert results_audit["external_tools_executed"] is False
    assert results_audit["raw_genomic_files_parsed"] is False
    assert results_audit["deep_result_files_parsed"] is False
    assert "reproducibility/results_audit.json" in result["reproducibility_bundle"]["files"]


def test_declared_result_artifacts_are_schema_only_and_not_read(tmp_path):
    result = run_agent(tmp_path, "audit PCA ADMIXTURE PLINK claims", results_only_uploads())
    artifacts = result["results_audit"]["declared_result_artifacts"]
    artifact_types = {artifact["artifact_type"] for artifact in artifacts}

    assert {"pca_eigenvec", "pca_eigenval", "admixture_q", "admixture_cv_log", "plink_summary", "manuscript_claims"} <= artifact_types
    for artifact in artifacts:
        assert artifact["parsed"] is False
        assert artifact["raw_file_read"] is False
        assert artifact["parse_status"] == "not_parsed_schema_only"
        assert artifact["human_review_required"] is True


def test_results_audit_context_requirements_are_explicit(tmp_path):
    result = run_agent(tmp_path, "audit PCA ADMIXTURE PLINK output context", results_only_uploads())
    missing = " ".join(result["results_audit"]["missing_result_context"]).lower()

    for required in [
        "sample metadata availability",
        "population labels provenance",
        "qc method summary",
        "ld pruning method",
        "reference panel used",
        "pca method/tool",
        "explained variance/eigenvalue context",
        "k values tested",
        "cv/error reporting",
        "random seed/replicate information if available",
        "tool version",
        "filters/qc thresholds",
        "sample and variant counts if available",
        "method provenance",
        "ethics/consent context if human data is discussed",
        "blocked interpretation categories",
    ]:
        assert required in missing


def test_results_audit_preserves_unsafe_claim_blocks(tmp_path):
    result = run_agent(
        tmp_path,
        "manuscript claims PCA proves caste identity, ADMIXTURE proves literal ancestry, selection is proven, endogamy is proven",
        results_only_uploads(),
    )
    unsafe = " ".join(result["results_audit"]["unsafe_claim_checks"]).lower()
    flags = " ".join(result["results_audit"]["human_review_flags"]).lower()

    for required in [
        "clinical diagnosis",
        "treatment recommendation",
        "consumer ancestry claim",
        "caste/community/religion inference",
        "genetic purity/superiority language",
        "literal ancestry from admixture components",
        "pca cluster identity claims",
        "unsupported selection claims",
        "unsupported endogamy claims",
    ]:
        assert required in unsafe
    assert "not completed analyses" in flags


def test_results_audit_json_is_absent_for_non_results_workflows(tmp_path):
    result = run_agent(
        tmp_path,
        "plan VCF PCA",
        {"vcf": {"content": b"placeholder\n", "filename": "cohort.vcf.gz"}},
    )
    repro_dir = Path(result["reproducibility_bundle"]["path"])

    assert result["workflow_selection"]["workflow_family"] == "vcf_population_structure"
    assert result["results_audit"] is None
    assert "reproducibility/results_audit.json" not in result["reproducibility_bundle"]["files"]
    assert not (repro_dir / "results_audit.json").exists()


def test_results_audit_json_and_report_are_generated_for_results_only(tmp_path):
    result = run_agent(tmp_path, "audit report claims from existing PCA and ADMIXTURE outputs", results_only_uploads())
    repro_dir = Path(result["reproducibility_bundle"]["path"])
    results_audit_path = repro_dir / "results_audit.json"
    report_path = Path(result["generated_files"]["final_report"]["absolute_path"])

    assert results_audit_path.is_file()
    payload = json.loads(results_audit_path.read_text(encoding="utf-8"))
    assert payload["selected_recipe_id"] == "results_only_audit_basic"
    assert payload["declared_result_artifacts"]
    assert all(artifact["parsed"] is False for artifact in payload["declared_result_artifacts"])
    assert all(artifact["raw_file_read"] is False for artifact in payload["declared_result_artifacts"])

    report = report_path.read_text(encoding="utf-8")
    assert "## Results-Only Audit Preview" in report
    assert "declared result files were inventoried by name only; result contents were not parsed." in report
    assert "no biological, clinical, ancestry, caste/community/religion, purity, superiority, or identity conclusions were made." in report
    assert "parsed=false, raw_file_read=false" in report


def test_results_audit_is_in_checksum_scope_without_raw_inputs(tmp_path):
    result = run_agent(tmp_path, "audit existing result outputs", results_only_uploads())
    repro_dir = Path(result["reproducibility_bundle"]["path"])
    checksums = (repro_dir / "checksums.sha256").read_text(encoding="utf-8")

    assert "reproducibility/results_audit.json" in checksums
    assert "demo.evec" not in checksums
    assert "demo.3.Q" not in checksums


def test_workbench_api_can_surface_results_audit_safely():
    response = client.post(
        "/insilicopop/agent/run",
        data={"query": "audit existing PCA and ADMIXTURE output claims", "memory_mode": "compact"},
        files={"smartpca_evec_file": ("demo.evec", b"S1 0.1 0.2 Pop\nS2 -0.1 0.3 Pop\n", "text/plain")},
    )
    assert response.status_code == 200
    body = response.json()
    run_id = body["run_id"]

    detail = client.get(f"/insilicopop/agent/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["results_audit"]["selected_recipe_id"] == "results_only_audit_basic"

    artifact = client.get(f"/insilicopop/agent/runs/{run_id}/artifacts/reproducibility/results_audit.json")
    assert artifact.status_code == 200
    assert artifact.json()["content"]["dry_run_only"] is True
    assert artifact.json()["content"]["declared_result_artifacts"][0]["raw_file_read"] is False
