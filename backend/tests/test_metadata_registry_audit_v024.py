from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.insilicopop.agent.loop import AgentLoop
from app.insilicopop.agent.metadata_registry_audit import build_metadata_registry_audit
from app.main import app


client = TestClient(app)


def run_agent(
    tmp_path: Path,
    query: str,
    uploads: dict[str, dict[str, bytes | str] | None] | None = None,
    metadata_registry: dict[str, object] | None = None,
) -> dict[str, object]:
    return AgentLoop(generated_root=tmp_path).run(
        query=query,
        uploads=uploads or {},
        max_steps=8,
        memory_budget_chars=1500,
        memory_mode="compact",
        llm_provider="mock",
        metadata_registry=metadata_registry,
    )


def population_registry(**overrides: object) -> dict[str, object]:
    registry: dict[str, object] = {
        "project_metadata": {"title": "Population study", "data_access_level": "managed", "ethics_approval_declared": True},
        "sample_metadata": {"sample_count_declared": False, "cohort_labels_declared": True},
        "sequencing_metadata": {"sequencing_platform_declared": False, "genome_build_declared": True, "batch_ids_declared": False},
        "population_genetics_metadata": {"population_labels_declared": True, "qc_steps_declared": False, "ld_pruning_declared": False, "sample_size_per_group_declared": False},
    }
    registry.update(overrides)
    return registry


def clinical_registry(**overrides: object) -> dict[str, object]:
    registry: dict[str, object] = {
        "project_metadata": {"title": "Clinical curation study", "data_access_level": "managed", "ethics_approval_declared": True},
        "clinical_metadata": {"hpo_terms_declared": False, "variant_list_declared": False, "inheritance_model_declared": False, "family_history_or_pedigree_declared": False, "clinician_review_declared": False},
    }
    registry.update(overrides)
    return registry


def test_metadata_registry_audit_returns_deterministic_object():
    audit = build_metadata_registry_audit(
        query="Plan population genetics PCA workflow.",
        uploaded_files={"vcf": "cohort.vcf.gz"},
        workflow_selection={"workflow_family": "vcf_population_structure"},
        metadata_registry=population_registry(),
    )

    assert audit["research_lane"] == "population_genetics"
    assert audit["human_review_required"] is True
    assert audit["biological_interpretation_made"] is False
    assert audit["clinical_decision_made"] is False
    assert isinstance(audit["metadata_completeness_score"], float)


def test_population_genetics_missing_metadata_gets_caveats(tmp_path):
    result = run_agent(
        tmp_path,
        "Plan PCA and ADMIXTURE population structure workflow.",
        {"vcf": {"content": b"placeholder\n", "filename": "cohort.vcf.gz"}},
        population_registry(),
    )
    audit = result["metadata_registry_audit"]
    missing = set(audit["missing_required_metadata"])

    assert audit["research_lane"] == "population_genetics"
    assert audit["status"] == "passed_with_caveats"
    assert {"sample_count_declared", "sample_size_per_group_declared", "sequencing_platform_declared", "qc_steps_declared", "ld_pruning_declared"} <= missing
    assert audit["human_review_required"] is True


def test_clinical_genetics_missing_metadata_gets_caveats(tmp_path):
    result = run_agent(tmp_path, "Clinical genetics research curation for HPO and variant evidence.", metadata_registry=clinical_registry())
    audit = result["metadata_registry_audit"]
    missing = set(audit["missing_required_metadata"])

    assert audit["research_lane"] == "clinical_genetics_research_curation"
    assert audit["status"] == "passed_with_caveats"
    assert {"hpo_terms_declared", "variant_list_declared", "inheritance_model_declared", "family_history_or_pedigree_declared", "clinician_review_declared"} <= missing
    assert audit["clinical_decision_made"] is False


def test_out_of_scope_diagnosis_treatment_and_final_acmg_are_blocked(tmp_path):
    result = run_agent(
        tmp_path,
        "Make a diagnosis, recommend treatment, and make final ACMG classification for this variant.",
        metadata_registry=clinical_registry(),
    )
    audit = result["metadata_registry_audit"]
    blocked = set(audit["blocked_out_of_scope_categories"])

    assert audit["status"] == "blocked"
    assert audit["research_lane"] == "blocked_out_of_scope"
    assert {"diagnosis_tool", "treatment_recommendation", "final_acmg_classification"} <= blocked


def test_caste_community_religion_request_is_blocked(tmp_path):
    result = run_agent(tmp_path, "Infer caste, community, and religion from PCA clusters.", metadata_registry=population_registry())
    audit = result["metadata_registry_audit"]

    assert audit["status"] == "blocked"
    assert "caste_community_religion_inference" in audit["blocked_out_of_scope_categories"]


def test_metadata_registry_artifact_report_and_checksum_are_generated(tmp_path):
    result = run_agent(
        tmp_path,
        "Plan VCF population structure workflow.",
        {"vcf": {"content": b"placeholder\n", "filename": "cohort.vcf.gz"}},
        population_registry(),
    )
    repro_dir = Path(result["reproducibility_bundle"]["path"])
    artifact = repro_dir / "metadata_registry_audit.json"
    report = Path(result["generated_files"]["final_report"]["absolute_path"]).read_text(encoding="utf-8")
    checksums = (repro_dir / "checksums.sha256").read_text(encoding="utf-8")

    assert "reproducibility/metadata_registry_audit.json" in result["reproducibility_bundle"]["files"]
    assert artifact.is_file()
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["human_review_required"] is True
    assert payload["biological_interpretation_made"] is False
    assert payload["clinical_decision_made"] is False
    assert "## Metadata Registry Audit" in report
    assert "clinical_decision_made: `false`" in report
    assert "reproducibility/metadata_registry_audit.json" in checksums
    assert "cohort.vcf" not in checksums


def test_workbench_api_exposes_metadata_registry_audit():
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

    detail = client.get(f"/insilicopop/agent/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["metadata_registry_audit"]["human_review_required"] is True
    assert detail.json()["research_lane"] == "population_genetics"

    artifact = client.get(f"/insilicopop/agent/runs/{run_id}/artifacts/reproducibility/metadata_registry_audit.json")
    assert artifact.status_code == 200
    assert artifact.json()["content"]["clinical_decision_made"] is False


def test_previous_audit_layers_and_runtime_invariants_remain_intact(tmp_path):
    result = run_agent(
        tmp_path,
        "Audit existing PCA result claims and governance.",
        {"result_pca_evec_file": {"content": b"placeholder\n", "filename": "demo.evec"}},
        population_registry(),
    )

    assert result["claim_audit"]["human_review_required"] is True
    assert result["results_audit"]["workflow_family"] == "results_only_audit"
    assert result["data_governance_audit"]["human_review_required"] is True
    assert result["metadata_registry_audit"]["human_review_required"] is True
    assert result["external_llm_called"] is False
    assert result["external_tools_executed"] is False
