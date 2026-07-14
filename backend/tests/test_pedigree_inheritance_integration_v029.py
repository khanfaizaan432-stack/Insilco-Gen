from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.insilicopop.agent.loop import AgentLoop
from app.insilicopop.agent.workbench import WorkbenchRunStore
from app.insilicopop.clinical.service import build_clinical_case_with_curation
from app.main import app


client = TestClient(app)
FORBIDDEN_OUTPUT_TERMS = (
    "paternity",
    "non-parentage",
    "relationship-discrepancy",
    "biological-discrepancy",
    "adoption",
    "donor conception",
    "consanguinity",
    "parental mosaicism",
    "sample-swap",
    "sample swap",
    "available_meioses",
    "penetrance",
    "lod score",
    "likelihood ratio",
    "segregation strength",
    "recurrence risk",
)


def clinical_payload(*, second_parent_testing="tested"):
    return {
        "schema_version": "0.27",
        "pseudonymous_case_id": "CASE-V029-INTEGRATION",
        "intended_use": "clinical_genetics_research_curation",
        "redaction_declared": True,
        "reviewer_status": "pending",
        "human_review_required": True,
        "genome_build": "GRCh38",
        "provenance": [{"source_id": "SRC-1", "source_type": "synthetic_fixture"}],
        "phenotypes": [{"observation_id": "PH-1", "supplied_term": "fictional finding not for ordinary output", "state": "unknown"}],
        "candidate_variants": [{"candidate_id": "VAR-1", "submitted_representation": "fictional candidate not for ordinary output", "gene": "GENE1"}],
        "pedigree": [
            {"family_member_id": "MEM-P", "relationship_to_proband": "proband", "affected_status": "affected", "testing_availability": "available"},
            {"family_member_id": "MEM-A", "relationship_to_proband": "parent", "affected_status": "unaffected", "testing_availability": "available"},
            {"family_member_id": "MEM-B", "relationship_to_proband": "parent", "affected_status": "unaffected", "testing_availability": "available"},
        ],
        "hypotheses": [{"hypothesis_id": "HYP-1", "hypothesis_type": "inheritance", "value": "supplied", "inheritance_candidate": "de_novo"}],
        "pedigree_inheritance_audit": {
            "schema_version": "0.29",
            "proband_member_id": "MEM-P",
            "relationships": [
                {"relationship_id": "REL-A", "relationship_type": "biological_parent", "parent_member_id": "MEM-A", "child_member_id": "MEM-P", "provenance_source_ids": ["SRC-1"]},
                {"relationship_id": "REL-B", "relationship_type": "biological_parent", "parent_member_id": "MEM-B", "child_member_id": "MEM-P", "provenance_source_ids": ["SRC-1"]},
            ],
            "variant_observations": [
                {"observation_id": "OBS-P", "family_member_id": "MEM-P", "candidate_variant_id": "VAR-1", "presence_state": "present", "zygosity": "heterozygous", "testing_state": "tested", "confirmation_state": "confirmed", "provenance_source_ids": ["SRC-1"]},
                {"observation_id": "OBS-A", "family_member_id": "MEM-A", "candidate_variant_id": "VAR-1", "presence_state": "absent", "testing_state": "tested", "confirmation_state": "confirmed", "provenance_source_ids": ["SRC-1"]},
                {"observation_id": "OBS-B", "family_member_id": "MEM-B", "candidate_variant_id": "VAR-1", "presence_state": "absent", "testing_state": second_parent_testing, "confirmation_state": "confirmed", "provenance_source_ids": ["SRC-1"]},
            ],
            "audit_targets": [{"audit_target_id": "TARGET-1", "hypothesis_id": "HYP-1", "candidate_variant_ids": ["VAR-1"]}],
            "phase_declarations": [],
            "human_review_required": True,
        },
    }


def expanded_determinism_payload():
    data = clinical_payload()
    data["provenance"] = [
        {"source_id": "SRC-1", "source_type": "synthetic_fixture"},
        {"source_id": "SRC-2", "source_type": "synthetic_fixture"},
    ]
    data["candidate_variants"] = [
        {"candidate_id": "VAR-1", "submitted_representation": "candidate one", "gene": "GENE1"},
        {"candidate_id": "VAR-2", "submitted_representation": "candidate two", "gene": "GENE1"},
    ]
    data["hypotheses"] = [
        {"hypothesis_id": "HYP-C", "hypothesis_type": "inheritance", "value": "compound", "inheritance_candidate": "compound_heterozygous"},
        {"hypothesis_id": "HYP-U", "hypothesis_type": "inheritance", "value": "unknown", "inheritance_candidate": "unknown"},
    ]
    declaration = data["pedigree_inheritance_audit"]
    declaration["relationships"] = [
        {"relationship_id": "REL-A", "relationship_type": "biological_parent", "parent_member_id": "MEM-A", "child_member_id": "MEM-P", "provenance_source_ids": ["SRC-2", "SRC-1"]},
        {"relationship_id": "REL-B", "relationship_type": "biological_parent", "parent_member_id": "MEM-B", "child_member_id": "MEM-P", "provenance_source_ids": ["SRC-2", "SRC-1"]},
    ]
    declaration["variant_observations"] = [
        {"observation_id": "OBS-P-1", "family_member_id": "MEM-P", "candidate_variant_id": "VAR-1", "presence_state": "present", "zygosity": "heterozygous", "testing_state": "tested", "confirmation_state": "confirmed", "provenance_source_ids": ["SRC-2", "SRC-1"]},
        {"observation_id": "OBS-P-2", "family_member_id": "MEM-P", "candidate_variant_id": "VAR-2", "presence_state": "present", "zygosity": "heterozygous", "testing_state": "tested", "confirmation_state": "confirmed", "provenance_source_ids": ["SRC-2", "SRC-1"]},
        {"observation_id": "OBS-A-1", "family_member_id": "MEM-A", "candidate_variant_id": "VAR-1", "presence_state": "present", "testing_state": "tested", "confirmation_state": "confirmed", "provenance_source_ids": ["SRC-2", "SRC-1"]},
        {"observation_id": "OBS-A-2", "family_member_id": "MEM-A", "candidate_variant_id": "VAR-2", "presence_state": "absent", "testing_state": "tested", "confirmation_state": "confirmed", "provenance_source_ids": ["SRC-2", "SRC-1"]},
        {"observation_id": "OBS-B-1", "family_member_id": "MEM-B", "candidate_variant_id": "VAR-1", "presence_state": "absent", "testing_state": "tested", "confirmation_state": "confirmed", "provenance_source_ids": ["SRC-2", "SRC-1"]},
        {"observation_id": "OBS-B-2", "family_member_id": "MEM-B", "candidate_variant_id": "VAR-2", "presence_state": "present", "testing_state": "tested", "confirmation_state": "confirmed", "provenance_source_ids": ["SRC-2", "SRC-1"]},
    ]
    declaration["audit_targets"] = [
        {"audit_target_id": "TARGET-C", "hypothesis_id": "HYP-C", "candidate_variant_ids": ["VAR-2", "VAR-1"]},
        {"audit_target_id": "TARGET-U", "hypothesis_id": "HYP-U", "candidate_variant_ids": ["VAR-1"]},
    ]
    declaration["phase_declarations"] = [
        {"phase_declaration_id": "PHASE-A", "candidate_variant_ids": ["VAR-1", "VAR-2"], "state": "unknown", "evidence_basis": "not_supplied", "provenance_source_ids": ["SRC-2", "SRC-1"], "review_state": "pending"},
        {"phase_declaration_id": "PHASE-B", "candidate_variant_ids": ["VAR-2", "VAR-1"], "state": "cannot_evaluate", "evidence_basis": "not_supplied", "provenance_source_ids": ["SRC-2", "SRC-1"], "review_state": "pending"},
    ]
    return data


def test_run_writes_bounded_artifact_report_trace_checksum_and_runtime_lock(tmp_path):
    result = AgentLoop(generated_root=tmp_path).run(query="Audit supplied structured inheritance evidence", uploads={}, clinical_case_intake=clinical_payload())
    repro = Path(result["reproducibility_bundle"]["path"])
    artifact = repro / "pedigree_inheritance_audit.json"
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    report = Path(result["generated_files"]["final_report"]["absolute_path"]).read_text(encoding="utf-8")
    trace_text = json.dumps(result["agent_trace"], sort_keys=True)
    lock = json.loads((repro / "runtime_lock.json").read_text(encoding="utf-8"))
    checksums = (repro / "checksums.sha256").read_text(encoding="utf-8")

    assert artifact.is_file()
    assert result["clinical_case_intake"]["schema_version"] == "0.27"
    assert payload["schema_version"] == "0.29"
    assert payload["inheritance_consistency_audit_performed"] is True
    assert payload["inheritance_clinically_established"] is False
    assert payload["inheritance_audits"][0]["status"] == "consistent"
    assert "## Pedigree and Inheritance Audit Preview" in report
    assert "reproducibility/pedigree_inheritance_audit.json" in result["reproducibility_bundle"]["files"]
    assert "reproducibility/pedigree_inheritance_audit.json" in checksums
    assert lock["pedigree_inheritance_audit_schema_version"] == "0.29"
    assert lock["pedigree_inheritance_audit_algorithm_version"] == "insilicopop-pedigree-inheritance-audit-0.29.0"
    assert lock["inheritance_consistency_audit_performed"] is True
    assert lock["inheritance_clinically_established"] is False
    assert "fictional finding not for ordinary output" not in report
    assert "fictional finding not for ordinary output" not in trace_text
    assert "fictional candidate not for ordinary output" not in report
    bounded_outputs = "\n".join([json.dumps(payload, sort_keys=True), report, trace_text]).casefold()
    assert all(term not in bounded_outputs for term in FORBIDDEN_OUTPUT_TERMS)


def test_exact_candidate_biological_strings_are_preserved_in_serialized_intake_artifact_not_trace(tmp_path):
    data = clinical_payload()
    raw_candidate = {
        "candidate_id": "VAR-1",
        "submitted_representation": "  ACGTACGT  ",
        "gene": " GENE1 ",
        "transcript": " NM_000001.2 ",
        "genome_build": " GRCh38 ",
        "chromosome": " X ",
        "position": 100,
        "ref": " A ",
        "alt": " T ",
        "submitted_hgvs": [" NM_000001.2:c.1A>T "],
        "provenance": [{"source_id": "SRC-1", "source_type": "synthetic_fixture", "reference": " NC_000023.11 "}],
    }
    data["candidate_variants"] = [raw_candidate]
    result = AgentLoop(generated_root=tmp_path).run(query="Audit supplied structured inheritance evidence", uploads={}, clinical_case_intake=data)
    repro = Path(result["reproducibility_bundle"]["path"])
    serialized = json.loads((repro / "clinical_case_intake.json").read_text(encoding="utf-8"))["supplied_candidate_variants"][0]
    for field in ("submitted_representation", "gene", "transcript", "genome_build", "chromosome", "ref", "alt", "submitted_hgvs"):
        assert serialized[field] == raw_candidate[field]
    assert serialized["provenance"][0]["reference"] == " NC_000023.11 "
    assert "  ACGTACGT  " not in json.dumps(result["agent_trace"], sort_keys=True)
    assert "candidate_biological_string_formatting_anomaly" in {item["code"] for item in result["clinical_case_intake"]["validation_warnings"]}


def test_equivalent_reordered_runs_have_identical_objects_artifacts_and_issue_ids(tmp_path):
    data = clinical_payload(second_parent_testing="not_tested")
    first = AgentLoop(generated_root=tmp_path).run(query="Audit supplied structured inheritance evidence", uploads={}, clinical_case_intake=data)
    reordered = copy.deepcopy(data)
    reordered["pedigree"] = list(reversed(reordered["pedigree"]))
    declaration = reordered["pedigree_inheritance_audit"]
    declaration["relationships"] = list(reversed(declaration["relationships"]))
    declaration["variant_observations"] = list(reversed(declaration["variant_observations"]))
    second = AgentLoop(generated_root=tmp_path).run(query="Audit supplied structured inheritance evidence", uploads={}, clinical_case_intake=reordered)
    first_repro = Path(first["reproducibility_bundle"]["path"])
    second_repro = Path(second["reproducibility_bundle"]["path"])
    first_bytes = (first_repro / "pedigree_inheritance_audit.json").read_bytes()
    second_bytes = (second_repro / "pedigree_inheritance_audit.json").read_bytes()

    assert first["run_id"] != second["run_id"]
    assert first["pedigree_inheritance_audit"] == second["pedigree_inheritance_audit"]
    assert first_bytes == second_bytes
    assert hashlib.sha256(first_bytes).hexdigest() == hashlib.sha256(second_bytes).hexdigest()
    first_ids = [item["issue_id"] for item in first["pedigree_inheritance_audit"]["missing_relative_requirements"]]
    second_ids = [item["issue_id"] for item in second["pedigree_inheritance_audit"]["missing_relative_requirements"]]
    assert first_ids == second_ids


def test_expanded_reordering_preserves_audit_objects_ids_artifact_bytes_and_sha256(tmp_path):
    data = expanded_determinism_payload()
    first = AgentLoop(generated_root=tmp_path).run(query="Audit supplied structured inheritance evidence", uploads={}, clinical_case_intake=data)
    reordered = copy.deepcopy(data)
    reordered["provenance"].reverse()
    reordered["candidate_variants"].reverse()
    reordered["pedigree"].reverse()
    reordered["hypotheses"].reverse()
    declaration = reordered["pedigree_inheritance_audit"]
    declaration["relationships"].reverse()
    declaration["variant_observations"].reverse()
    declaration["audit_targets"].reverse()
    declaration["phase_declarations"].reverse()
    for record in [*declaration["relationships"], *declaration["variant_observations"], *declaration["phase_declarations"]]:
        record["provenance_source_ids"].reverse()
    second = AgentLoop(generated_root=tmp_path).run(query="Audit supplied structured inheritance evidence", uploads={}, clinical_case_intake=reordered)
    first_path = Path(first["reproducibility_bundle"]["path"]) / "pedigree_inheritance_audit.json"
    second_path = Path(second["reproducibility_bundle"]["path"]) / "pedigree_inheritance_audit.json"
    first_bytes = first_path.read_bytes()
    second_bytes = second_path.read_bytes()
    assert first["pedigree_inheritance_audit"] == second["pedigree_inheritance_audit"]
    assert first_bytes == second_bytes
    assert hashlib.sha256(first_bytes).hexdigest() == hashlib.sha256(second_bytes).hexdigest()


def test_clinical_path_bypasses_retrieval_llm_tools_parsers_and_raw_processing(tmp_path, monkeypatch):
    import app.insilicopop.agent.loop as loop_module

    def forbidden(*args, **kwargs):
        raise AssertionError("forbidden subsystem called")

    monkeypatch.setattr(loop_module, "retrieve_evidence", forbidden)
    monkeypatch.setattr(loop_module, "build_llm_provider", forbidden)
    monkeypatch.setattr(loop_module.InSilicoPopAuditService, "run", forbidden)
    monkeypatch.setattr(loop_module.ToolRouter, "run", forbidden, raising=False)
    result = AgentLoop(generated_root=tmp_path).run(query="Audit supplied structured inheritance evidence", uploads={}, clinical_case_intake=clinical_payload())
    audit = result["pedigree_inheritance_audit"]
    assert result["selected_recipe"] is None
    assert result["external_llm_called"] is False
    assert result["external_tools_executed"] is False
    assert audit["external_api_call_made"] is False
    assert audit["external_llm_called"] is False
    assert audit["external_tools_executed"] is False
    assert audit["raw_genomic_files_parsed"] is False


def test_api_workbench_and_allowlisted_artifact_expose_bounded_v029_result():
    response = client.post(
        "/insilicopop/agent/run",
        data={"query": "Audit supplied structured inheritance evidence", "clinical_case_intake": json.dumps(clinical_payload()), "llm_provider": "mock"},
    )
    assert response.status_code == 200
    body = response.json()
    run_id = body["run_id"]
    assert body["pedigree_inheritance_audit"]["inheritance_audits"][0]["status"] == "consistent"
    detail_response = client.get(f"/insilicopop/agent/runs/{run_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["inheritance_audit_count"] == 1
    assert detail["inheritance_audit_status_counts"] == {"consistent": 1}
    assert detail["evaluable_parent_child_transmission_count"] == 2
    assert detail["pedigree_inheritance_audit_artifact_available"] is True
    artifact = client.get(f"/insilicopop/agent/runs/{run_id}/artifacts/reproducibility/pedigree_inheritance_audit.json")
    assert artifact.status_code == 200
    assert artifact.json()["content"]["schema_version"] == "0.29"
    ui = client.get("/insilicopop/workbench").text
    assert "Pedigree and Inheritance Audit Preview" in ui
    assert "renderPedigreeInheritanceAudit" in ui
    assert "available_meioses" not in ui
    bounded_outputs = "\n".join([json.dumps(body, sort_keys=True), json.dumps(detail, sort_keys=True), artifact.text, ui]).casefold()
    assert all(term not in bounded_outputs for term in FORBIDDEN_OUTPUT_TERMS)


def test_old_stored_run_and_v027_two_value_service_contract_remain_compatible(tmp_path):
    old_run = tmp_path / "old-run"
    old_run.mkdir()
    old_state = {
        "run_id": "old-run",
        "query": "old synthetic run",
        "workflow_selection": {"workflow_family": "clinical_case_intake"},
        "llm_provider": "mock",
        "external_llm_called": False,
        "external_tools_executed": False,
        "clinical_case_intake": {"schema_version": "0.27", "intake_completeness": "complete", "policy_blocks": []},
    }
    (old_run / "agent_state.json").write_text(json.dumps(old_state), encoding="utf-8")
    detail = WorkbenchRunStore(generated_root=tmp_path).run_detail("old-run")
    assert detail.pedigree_inheritance_audit is None
    assert detail.inheritance_audit_count == 0
    assert detail.pedigree_inheritance_audit_artifact_available is False

    old_payload = clinical_payload()
    old_payload.pop("pedigree_inheritance_audit")
    result = build_clinical_case_with_curation(old_payload)
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert result[0].schema_version == "0.27"
    assert result[0].inheritance_calculation_performed is False


def test_frozen_archive_hashes_remain_exact():
    root = Path(__file__).resolve().parents[2]
    expected = {
        "insilicopop_v0.25_local_chroma_langchain_retrieval.tar.gz": "9487E82C0085122499BDA65DD83ADBB1B4EA64CD7B066C73ED86591C68C5966D",
        "insilicopop_v0.26_controlled_langgraph_orchestration.tar.gz": "DA1053DFEB37A03C1C4C1DE5E92E0E6BE5E13D836019793446A1896525079B30",
        "insilicopop_v0.27_clinical_intake_case_schema.tar.gz": "E1AA70C24CD1B70AE277BA6F3DDF9CBD568F95B2744F97DF07A9E9A72B5320DD",
        "insilicopop_v0.28_phenotype_hpo_curation.tar.gz": "DC980618A2B0EEA6AB18D577F7708FE90710F3090B9FC78E5C41BFC204386BD7",
    }
    for filename, digest in expected.items():
        assert hashlib.sha256((root / filename).read_bytes()).hexdigest().upper() == digest
