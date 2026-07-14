from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.insilicopop.agent.loop import AgentLoop
from app.main import app


client = TestClient(app)


def run_agent(
    tmp_path: Path,
    query: str,
    uploads: dict[str, dict[str, bytes | str] | None] | None = None,
    data_use_agreement_scope: dict[str, object] | None = None,
) -> dict[str, object]:
    return AgentLoop(generated_root=tmp_path).run(
        query=query,
        uploads=uploads or {},
        max_steps=8,
        memory_budget_chars=1500,
        memory_mode="compact",
        llm_provider="mock",
        data_use_agreement_scope=data_use_agreement_scope,
    )


def declared_scope(**overrides: object) -> dict[str, object]:
    scope: dict[str, object] = {
        "dataset_source": "institutional_cohort",
        "managed_access": True,
        "approved_use_summary": "IRB-approved research workflow planning for population genetics only",
        "prohibited_uses": ["diagnosis", "treatment", "re-identification"],
        "consent_type": "specific",
        "ethics_approval_declared": True,
        "biorrap_id_declared": True,
        "data_access_credential_model": "researcher_provided",
        "cross_border_export_declared": False,
        "secondary_use_declared": True,
        "commercial_or_third_party_use_declared": False,
    }
    scope.update(overrides)
    return scope


def test_managed_access_dataset_without_scope_is_blocked(tmp_path):
    result = run_agent(tmp_path, "Audit a managed-access GenomeIndia cohort for population structure.")
    audit = result["data_governance_audit"]

    assert audit["status"] == "blocked"
    assert audit["declared_scope_present"] is False
    assert any("managed-access" in item.lower() for item in audit["blocked"])
    assert audit["human_review_required"] is True


def test_shared_service_account_for_managed_access_is_blocked(tmp_path):
    result = run_agent(
        tmp_path,
        "Plan research-only analysis for a managed-access human genomic cohort.",
        data_use_agreement_scope=declared_scope(data_access_credential_model="shared_service_account"),
    )
    audit = result["data_governance_audit"]

    assert audit["status"] == "blocked"
    assert audit["shared_service_account_used"] is True
    assert any("shared service account" in item.lower() for item in audit["blocked"])


def test_clinical_diagnosis_goal_from_research_dataset_is_blocked(tmp_path):
    result = run_agent(
        tmp_path,
        "Use this research-only cohort for clinical diagnosis of disease status.",
        data_use_agreement_scope=declared_scope(approved_use_summary="research-only population genetics planning"),
    )

    blocked = " ".join(result["data_governance_audit"]["blocked"]).lower()
    assert "clinical diagnosis" in blocked
    assert result["data_governance_audit"]["status"] == "blocked"


def test_caste_community_religion_inference_goal_is_blocked(tmp_path):
    result = run_agent(
        tmp_path,
        "Infer caste, community, and religion from genetic data.",
        data_use_agreement_scope=declared_scope(),
    )

    blocked = " ".join(result["data_governance_audit"]["blocked"]).lower()
    assert "caste/community/religion inference" in blocked
    assert result["claim_audit"]["identity_inference_claims_blocked"] is True


def test_reidentification_and_raw_export_goal_is_blocked(tmp_path):
    result = run_agent(
        tmp_path,
        "Re-identify individuals and upload raw VCF data to an external cloud service.",
        data_use_agreement_scope=declared_scope(cross_border_export_declared=True, ethics_approval_declared=False, biorrap_id_declared=False),
    )

    blocked = " ".join(result["data_governance_audit"]["blocked"]).lower()
    assert "re-identification" in blocked
    assert "network upload/export" in blocked
    assert "cross-border/export" in blocked
    assert result["data_governance_audit"]["raw_data_network_access_allowed"] is False


def test_declared_scope_with_vague_approved_use_passes_with_caveats(tmp_path):
    result = run_agent(
        tmp_path,
        "Plan research-use population genetics workflow.",
        data_use_agreement_scope=declared_scope(
            approved_use_summary="research",
            consent_type="unknown",
            ethics_approval_declared=False,
            secondary_use_declared=False,
        ),
    )
    audit = result["data_governance_audit"]

    assert audit["status"] == "passed_with_caveats"
    assert audit["blocked"] == []
    caveats = " ".join(audit["caveats"]).lower()
    assert "not machine-verified" in caveats
    assert "vague or missing" in caveats
    assert "consent type is unknown" in caveats


def test_public_reference_dataset_is_not_incorrectly_blocked(tmp_path):
    result = run_agent(
        tmp_path,
        "Audit a public reference panel for research workflow planning.",
        data_use_agreement_scope=declared_scope(
            dataset_source="public_reference",
            managed_access=False,
            approved_use_summary="public reference research workflow planning only",
            data_access_credential_model="not_applicable",
            ethics_approval_declared=True,
        ),
    )

    audit = result["data_governance_audit"]
    assert audit["status"] != "blocked"
    assert audit["blocked"] == []
    assert audit["data_use_agreement_scope"]["dataset_source"] == "public_reference"


def test_data_governance_artifact_report_and_checksum_are_generated(tmp_path):
    result = run_agent(tmp_path, "Plan VCF PCA with declared governance scope.", {"vcf": {"content": b"placeholder\n", "filename": "cohort.vcf.gz"}}, declared_scope())
    repro_dir = Path(result["reproducibility_bundle"]["path"])
    audit_path = repro_dir / "data_governance_audit.json"
    report_path = Path(result["generated_files"]["final_report"]["absolute_path"])

    assert "reproducibility/data_governance_audit.json" in result["reproducibility_bundle"]["files"]
    assert audit_path.is_file()
    payload = json.loads(audit_path.read_text(encoding="utf-8"))
    assert payload["human_review_required"] is True
    assert payload["dataset_terms_verified"] is False
    assert payload["legal_compliance_verified"] is False

    report = report_path.read_text(encoding="utf-8")
    assert "## Data Governance Audit" in report
    assert "Audit does not verify legal compliance." in report
    assert "does not replace institutional ethics committee" in report

    checksums = (repro_dir / "checksums.sha256").read_text(encoding="utf-8")
    assert "reproducibility/data_governance_audit.json" in checksums
    assert "cohort.vcf" not in checksums


def test_workbench_api_exposes_data_governance_audit():
    scope = json.dumps(declared_scope(dataset_source="public_reference", managed_access=False, data_access_credential_model="not_applicable"))
    response = client.post(
        "/insilicopop/agent/run",
        data={"query": "Plan public reference research workflow", "memory_mode": "compact", "data_use_agreement_scope": scope},
        files={"metadata_file": ("metadata.csv", b"sample_id,population\nS1,A\n", "text/csv")},
    )
    assert response.status_code == 200
    body = response.json()
    run_id = body["run_id"]

    detail = client.get(f"/insilicopop/agent/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["data_governance_audit"]["human_review_required"] is True

    artifact = client.get(f"/insilicopop/agent/runs/{run_id}/artifacts/reproducibility/data_governance_audit.json")
    assert artifact.status_code == 200
    assert artifact.json()["content"]["raw_data_network_access_allowed"] is False


def test_claim_and_results_audit_behaviors_remain_unchanged(tmp_path):
    result = run_agent(
        tmp_path,
        "Audit existing PCA and ADMIXTURE outputs; PCA must not prove caste identity.",
        {
            "result_pca_evec_file": {"content": b"placeholder\n", "filename": "demo.evec"},
            "result_admixture_q_file": {"content": b"placeholder\n", "filename": "demo.3.Q"},
        },
        declared_scope(dataset_source="public_reference", managed_access=False, data_access_credential_model="not_applicable"),
    )

    assert result["workflow_selection"]["workflow_family"] == "results_only_audit"
    assert result["claim_audit"]["identity_inference_claims_blocked"] is True
    assert result["results_audit"]["workflow_family"] == "results_only_audit"
    assert result["results_audit"]["deep_result_files_parsed"] is False
    assert result["external_llm_called"] is False
    assert result["external_tools_executed"] is False
    assert result["data_governance_audit"]["human_review_required"] is True
