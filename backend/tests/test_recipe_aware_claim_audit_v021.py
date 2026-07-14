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


def test_recipe_claim_audit_exists_and_preserves_safety_invariants(tmp_path):
    result = run_agent(
        tmp_path,
        "plan VCF PCA but avoid clinical diagnosis and caste/community/religion claims",
        {"vcf": {"content": b"placeholder\n", "filename": "cohort.vcf.gz"}},
    )
    claim_audit = result["claim_audit"]

    assert claim_audit["selected_recipe_id"] == "vcf_population_structure_basic"
    assert claim_audit["workflow_family"] == "vcf_population_structure"
    assert claim_audit["dry_run_only"] is True
    assert claim_audit["human_review_required"] is True
    assert claim_audit["external_tools_executed"] is False
    assert claim_audit["raw_genomic_files_parsed"] is False
    assert claim_audit["clinical_or_consumer_claims_blocked"] is True
    assert claim_audit["identity_inference_claims_blocked"] is True


def test_required_blocked_categories_are_explicit_for_recipe_selected_runs(tmp_path):
    result = run_agent(
        tmp_path,
        "ADMIXTURE proves literal ancestry, PCA proves identity, selection is proven, endogamy is proven, genetic purity is superior",
        {"vcf": {"content": b"placeholder\n", "filename": "cohort.vcf.gz"}},
    )
    claim_audit = result["claim_audit"]
    blocked = " ".join(claim_audit["blocked_interpretations"]).lower()
    unsupported = " ".join(claim_audit["unsupported_claim_categories"]).lower()

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
        assert required in blocked
        assert required in unsupported


def test_claim_audit_required_caveats_cover_population_genetics_overclaims(tmp_path):
    result = run_agent(
        tmp_path,
        "audit PCA ADMIXTURE FST selection ROH and founder-effect claims",
        {"pca": {"content": b"x,y\n", "filename": "demo.evec"}},
    )
    claim_audit = result["claim_audit"]
    caveats = " ".join(claim_audit["required_caveats"]).lower()
    flags = " ".join(claim_audit["human_review_flags"]).lower()

    assert claim_audit["selected_recipe_id"] == "results_only_audit_basic"
    assert "pca shows structure/clustering, not identity" in caveats
    assert "admixture components are model components, not literal ancestry" in caveats
    assert "cannot alone prove selection" in caveats
    assert "cannot alone prove endogamy" in caveats
    assert "india-specific population labels" in caveats
    assert "human expert review is mandatory" in flags
    assert "bad" not in caveats
    assert "superior" not in " ".join(claim_audit["required_caveats"]).lower()


def test_claim_audit_json_is_generated_and_in_checksum_scope(tmp_path):
    result = run_agent(
        tmp_path,
        "clinical diagnosis and treatment recommendation should be blocked",
        {"vcf": {"content": b"placeholder\n", "filename": "cohort.vcf.gz"}},
    )
    repro_dir = Path(result["reproducibility_bundle"]["path"])
    claim_audit_path = repro_dir / "claim_audit.json"

    assert claim_audit_path.is_file()
    claim_audit = json.loads(claim_audit_path.read_text(encoding="utf-8"))
    assert claim_audit["selected_recipe_id"] == "vcf_population_structure_basic"
    assert claim_audit["dry_run_only"] is True
    assert claim_audit["human_review_required"] is True
    assert claim_audit["external_tools_executed"] is False
    assert claim_audit["raw_genomic_files_parsed"] is False
    assert claim_audit["clinical_or_consumer_claims_blocked"] is True
    assert "reproducibility/claim_audit.json" in result["reproducibility_bundle"]["files"]

    checksums = (repro_dir / "checksums.sha256").read_text(encoding="utf-8")
    assert "reproducibility/claim_audit.json" in checksums
    assert "cohort.vcf" not in checksums


def test_final_report_includes_recipe_aware_claim_audit(tmp_path):
    result = run_agent(
        tmp_path,
        "PCA cluster identity and consumer ancestry claims must be blocked",
        {"vcf": {"content": b"placeholder\n", "filename": "cohort.vcf.gz"}},
    )
    report_path = Path(result["generated_files"]["final_report"]["absolute_path"])
    report = report_path.read_text(encoding="utf-8")

    assert "## Recipe-Aware Claim Audit" in report
    assert "selected_recipe_id: `vcf_population_structure_basic`" in report
    assert "Blocked interpretation categories:" in report
    assert "Unsupported claim categories:" in report
    assert "Required caveats:" in report
    assert "Human review flags:" in report
    assert "PCA shows structure/clustering, not identity." in report
    assert "ADMIXTURE components are model components, not literal ancestry." in report
    assert "raw_genomic_files_parsed: `false`" in report


def test_workbench_api_can_surface_claim_audit_safely():
    response = client.post(
        "/insilicopop/agent/run",
        data={"query": "selection is proven and consumer ancestry claims should be blocked", "memory_mode": "compact"},
        files={"vcf_file": ("cohort.vcf.gz", b"##fileformat=VCFv4.2\n", "application/gzip")},
    )
    assert response.status_code == 200
    body = response.json()
    run_id = body["run_id"]

    detail = client.get(f"/insilicopop/agent/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["claim_audit"]["selected_recipe_id"] == "vcf_population_structure_basic"

    artifact = client.get(f"/insilicopop/agent/runs/{run_id}/artifacts/reproducibility/claim_audit.json")
    assert artifact.status_code == 200
    content = artifact.json()["content"]
    assert content["selected_recipe_id"] == "vcf_population_structure_basic"
    assert content["consumer_ancestry_claims_blocked"] is True
    assert content["human_review_required"] is True
