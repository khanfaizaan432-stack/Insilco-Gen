from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.insilicopop.agent.loop import AgentLoop
from app.main import app


client = TestClient(app)


def population_registry() -> dict[str, object]:
    return {
        "project_metadata": {"title": "Population study", "data_access_level": "managed", "ethics_approval_declared": True},
        "sample_metadata": {"sample_count_declared": False, "cohort_labels_declared": True},
        "sequencing_metadata": {"sequencing_platform_declared": False, "genome_build_declared": True, "batch_ids_declared": False},
        "population_genetics_metadata": {"population_labels_declared": True, "qc_steps_declared": False, "ld_pruning_declared": False, "sample_size_per_group_declared": False},
    }


def clinical_registry() -> dict[str, object]:
    return {
        "project_metadata": {"title": "Clinical curation study", "data_access_level": "managed", "ethics_approval_declared": True},
        "clinical_metadata": {"hpo_terms_declared": False, "variant_list_declared": False, "inheritance_model_declared": False, "family_history_or_pedigree_declared": False, "clinician_review_declared": False},
    }


def run_agent(tmp_path: Path, query: str, metadata_registry: dict[str, object] | None = None) -> dict[str, object]:
    return AgentLoop(generated_root=tmp_path).run(
        query=query,
        uploads={"vcf": {"content": b"placeholder\n", "filename": "cohort.vcf.gz"}},
        max_steps=8,
        memory_budget_chars=1500,
        memory_mode="compact",
        llm_provider="mock",
        metadata_registry=metadata_registry or population_registry(),
    )


def test_evidence_retrieval_json_and_final_report_are_generated(tmp_path: Path):
    result = run_agent(tmp_path, "Plan PCA and ADMIXTURE population structure workflow.")
    repro_dir = Path(result["reproducibility_bundle"]["path"])
    artifact = repro_dir / "evidence_retrieval.json"
    report = Path(result["generated_files"]["final_report"]["absolute_path"]).read_text(encoding="utf-8")
    checksums = (repro_dir / "checksums.sha256").read_text(encoding="utf-8")

    assert "reproducibility/evidence_retrieval.json" in result["reproducibility_bundle"]["files"]
    assert artifact.is_file()
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["retrieval_mode"] == "deterministic_keyword_fallback"
    assert payload["local_only"] is True
    assert payload["external_call_made"] is False
    assert payload["raw_data_ingested"] is False
    assert payload["human_review_required"] is True
    assert payload["snippets_returned"] > 0
    assert "## Evidence Retrieval Preview" in report
    assert "local evidence retrieval only" in report
    assert "no external database/API call made" in report
    assert "no biological/clinical conclusion made" in report
    assert "human review required" in report
    assert "reproducibility/evidence_retrieval.json" in checksums
    assert "cohort.vcf" not in checksums


def test_workbench_api_exposes_evidence_retrieval():
    response = client.post(
        "/insilicopop/agent/run",
        data={
            "query": "Plan VCF population structure workflow",
            "memory_mode": "compact",
            "metadata_registry": json.dumps(population_registry()),
        },
        files={"vcf_file": ("cohort.vcf.gz", b"inventory placeholder only\n", "text/plain")},
    )
    assert response.status_code == 200
    run_id = response.json()["run_id"]
    assert response.json()["evidence_retrieval"]["local_only"] is True

    detail = client.get(f"/insilicopop/agent/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["evidence_retrieval"]["external_call_made"] is False
    assert detail.json()["evidence_retrieval_mode"] == "deterministic_keyword_fallback"
    assert detail.json()["evidence_snippet_count"] > 0

    artifact = client.get(f"/insilicopop/agent/runs/{run_id}/artifacts/reproducibility/evidence_retrieval.json")
    assert artifact.status_code == 200
    assert artifact.json()["content"]["raw_data_ingested"] is False


def test_existing_audit_layers_and_safety_invariants_remain_intact(tmp_path: Path):
    result = run_agent(
        tmp_path,
        "Clinical genetics research curation for HPO and variant evidence.",
        metadata_registry=clinical_registry(),
    )
    retrieval = result["evidence_retrieval"]

    assert result["claim_audit"]["human_review_required"] is True
    assert result["results_audit"] is None
    assert result["data_governance_audit"]["human_review_required"] is True
    assert result["metadata_registry_audit"]["human_review_required"] is True
    assert result["external_llm_called"] is False
    assert result["external_tools_executed"] is False
    assert retrieval["external_call_made"] is False
    assert retrieval["raw_genomic_files_parsed"] is False
    assert retrieval["clinical_decision_made"] is False
    assert retrieval["final_acmg_classification_made"] is False
