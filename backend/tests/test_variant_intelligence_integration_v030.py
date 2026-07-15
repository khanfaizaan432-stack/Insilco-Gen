from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.insilicopop.agent.loop import AgentLoop
from app.insilicopop.agent.workbench import WorkbenchRunStore
from app.main import app
from app.insilicopop.clinical.variant_reference_registry import SYNTHETIC_REFERENCE_SOURCE_ID


client = TestClient(app)
EXACT_VARIANT = "TEST1:2:A>G"


def clinical_payload():
    return {
        "schema_version": "0.27",
        "pseudonymous_case_id": "CASE-V030-INTEGRATION",
        "intended_use": "clinical_genetics_research_curation",
        "redaction_declared": True,
        "human_review_required": True,
        "genome_build": "InSilicoPopSynthetic-0.30",
        "provenance": [{"source_id": "SRC-1", "source_type": "synthetic_fixture"}],
        "candidate_variants": [{
            "candidate_id": "VAR-1", "submitted_representation": EXACT_VARIANT,
            "genome_build": "InSilicoPopSynthetic-0.30", "chromosome": "TEST1", "position": 2, "ref": "A", "alt": "G",
        }],
        "variant_intelligence": {
            "schema_version": "0.30",
            "human_review_required": True,
            "normalization_requests": [{
                "request_id": "REQ-1", "candidate_variant_id": "VAR-1",
                "supplied_representation": EXACT_VARIANT, "representation_type": "genomic_coordinate",
                "declared_variant_class": "snv",
                "structured_allele": {
                    "chromosome": "TEST1", "position": 2, "reference": "A", "alternate": "G",
                    "coordinate_system": "one_based_closed", "genome_build": "InSilicoPopSynthetic-0.30",
                    "reference_accession": "ISP_TESTREF.1", "reference_source_id": SYNTHETIC_REFERENCE_SOURCE_ID,
                },
                "requested_outputs": ["normalized_hgvs", "spdi", "canonical_internal_allele"],
                "provenance_source_ids": ["SRC-1"],
            }],
        },
    }


def test_run_writes_bounded_artifact_report_trace_checksum_and_lock(tmp_path):
    result = AgentLoop(generated_root=tmp_path).run(query="Validate supplied variant representation", uploads={}, clinical_case_intake=clinical_payload())
    repro = Path(result["reproducibility_bundle"]["path"])
    artifact = repro / "variant_intelligence.json"
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    report = Path(result["generated_files"]["final_report"]["absolute_path"]).read_text(encoding="utf-8")
    trace_text = json.dumps(result["agent_trace"], sort_keys=True)
    lock = json.loads((repro / "runtime_lock.json").read_text(encoding="utf-8"))
    checksums = (repro / "checksums.sha256").read_text(encoding="utf-8")
    assert payload["schema_version"] == "0.30"
    assert payload["normalization_results"][0]["normalization_status"] == "normalized"
    assert "## Variant Intelligence Preview" in report
    assert "reproducibility/variant_intelligence.json" in checksums
    assert lock["variant_intelligence_schema_version"] == "0.30"
    assert lock["variant_intelligence_algorithm_version"] == "insilicopop-variant-intelligence-0.30.1"
    assert lock["variant_pathogenicity_interpretation_performed"] is False
    assert lock["transcript_selection_performed"] is False
    assert EXACT_VARIANT in artifact.read_text(encoding="utf-8")
    assert EXACT_VARIANT not in report
    assert EXACT_VARIANT not in trace_text
    bounded = json.dumps(result["variant_intelligence"], sort_keys=True).casefold() + report.casefold() + trace_text.casefold()
    for prohibited in ("diagnosis provided", "treatment recommended", "pathogenic conclusion", "likely pathogenic", "benign classification"):
        assert prohibited not in bounded


def test_reordered_run_produces_identical_artifact_bytes_and_sha(tmp_path):
    first_data = clinical_payload()
    first = AgentLoop(generated_root=tmp_path).run(query="Validate supplied variant representation", uploads={}, clinical_case_intake=first_data)
    reordered = copy.deepcopy(first_data)
    req = reordered["variant_intelligence"]["normalization_requests"][0]
    req["requested_outputs"].reverse()
    req["provenance_source_ids"] = ["SRC-1", "SRC-1"]
    second = AgentLoop(generated_root=tmp_path).run(query="Validate supplied variant representation", uploads={}, clinical_case_intake=reordered)
    first_bytes = (Path(first["reproducibility_bundle"]["path"]) / "variant_intelligence.json").read_bytes()
    second_bytes = (Path(second["reproducibility_bundle"]["path"]) / "variant_intelligence.json").read_bytes()
    assert first["variant_intelligence"] == second["variant_intelligence"]
    assert first_bytes == second_bytes
    assert hashlib.sha256(first_bytes).hexdigest() == hashlib.sha256(second_bytes).hexdigest()


def test_multi_request_warning_and_issue_reordering_preserves_artifact_bytes(tmp_path):
    first_data = clinical_payload()
    first_data["candidate_variants"].append({
        "candidate_id": "VAR-2", "submitted_representation": "TEST1:3:A>T",
        "genome_build": "InSilicoPopSynthetic-0.30", "chromosome": "TEST1", "position": 3, "ref": "A", "alt": "T",
    })
    second_request = copy.deepcopy(first_data["variant_intelligence"]["normalization_requests"][0])
    second_request.update(
        request_id="REQ-2",
        candidate_variant_id="VAR-2",
        supplied_representation="TEST1:3:A>T",
        provenance_source_ids=["SRC-2", "SRC-1"],
    )
    second_request["structured_allele"].update(
        position=3,
        alternate="T",
        reference_context_sequence=" supplied inline evidence ",
        reference_context_start=0,
        reference_context_verified=True,
    )
    first_data["variant_intelligence"]["normalization_requests"].append(second_request)
    first = AgentLoop(generated_root=tmp_path).run(query="Validate supplied variant representation", uploads={}, clinical_case_intake=first_data)

    reordered = copy.deepcopy(first_data)
    reordered["candidate_variants"].reverse()
    reordered["variant_intelligence"]["normalization_requests"].reverse()
    for item in reordered["variant_intelligence"]["normalization_requests"]:
        item["requested_outputs"].reverse()
        item["provenance_source_ids"].reverse()
    second = AgentLoop(generated_root=tmp_path).run(query="Validate supplied variant representation", uploads={}, clinical_case_intake=reordered)
    first_bytes = (Path(first["reproducibility_bundle"]["path"]) / "variant_intelligence.json").read_bytes()
    second_bytes = (Path(second["reproducibility_bundle"]["path"]) / "variant_intelligence.json").read_bytes()
    assert first["variant_intelligence"] == second["variant_intelligence"]
    assert first_bytes == second_bytes
    assert hashlib.sha256(first_bytes).hexdigest() == hashlib.sha256(second_bytes).hexdigest()


def test_clinical_variant_path_bypasses_external_and_raw_subsystems(tmp_path, monkeypatch):
    import app.insilicopop.agent.loop as loop_module

    def forbidden(*args, **kwargs):
        raise AssertionError("forbidden subsystem called")

    monkeypatch.setattr(loop_module, "retrieve_evidence", forbidden)
    monkeypatch.setattr(loop_module, "build_llm_provider", forbidden)
    monkeypatch.setattr(loop_module.InSilicoPopAuditService, "run", forbidden)
    monkeypatch.setattr(loop_module.ToolRouter, "run", forbidden, raising=False)
    result = AgentLoop(generated_root=tmp_path).run(query="Validate supplied variant representation", uploads={}, clinical_case_intake=clinical_payload())
    variant = result["variant_intelligence"]
    assert result["external_llm_called"] is False
    assert result["external_tools_executed"] is False
    assert variant["external_llm_called"] is False
    assert variant["external_tools_executed"] is False
    assert variant["raw_genomic_files_parsed"] is False


def test_api_workbench_stored_run_and_allowlisted_artifact_expose_v030():
    response = client.post(
        "/insilicopop/agent/run",
        data={"query": "Validate supplied variant representation", "clinical_case_intake": json.dumps(clinical_payload()), "llm_provider": "mock"},
    )
    assert response.status_code == 200
    body = response.json()
    detail_response = client.get(f"/insilicopop/agent/runs/{body['run_id']}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["variant_intelligence_request_count"] == 1
    assert detail["variant_validation_status_counts"] == {"valid": 1}
    assert detail["variant_normalization_status_counts"] == {"normalized": 1}
    assert detail["variant_intelligence_artifact_available"] is True
    artifact = client.get(f"/insilicopop/agent/runs/{body['run_id']}/artifacts/reproducibility/variant_intelligence.json")
    assert artifact.status_code == 200
    assert artifact.json()["content"]["schema_version"] == "0.30"
    ui = client.get("/insilicopop/workbench").text
    assert "Variant Intelligence Workspace" in ui
    assert "renderVariantIntelligence" in ui
    assert "Variant normalization establishes representation consistency only. It does not establish pathogenicity, causality, diagnosis, or transcript relevance." in ui
    assert 'if (["valid", "partially_valid"].includes(item.validation_status))' in ui
    assert 'if (item.normalization_status === "normalized")' in ui
    assert 'item.equivalence_status === "unresolved_equivalence"' in ui
    assert 'item.equivalence_status === "unsupported_representation"' in ui
    assert '<span class="badge">SUPPLIED</span><span class="badge safe">VALIDATED</span><span class="badge">NORMALIZED</span>' not in ui


def test_old_stored_runs_remain_readable_without_variant_intelligence(tmp_path):
    old_run = tmp_path / "old-run"
    old_run.mkdir()
    (old_run / "agent_state.json").write_text(json.dumps({
        "run_id": "old-run", "query": "old synthetic run",
        "workflow_selection": {"workflow_family": "clinical_case_intake"},
        "llm_provider": "mock", "external_llm_called": False, "external_tools_executed": False,
        "clinical_case_intake": {"schema_version": "0.27", "intake_completeness": "complete", "policy_blocks": []},
    }), encoding="utf-8")
    detail = WorkbenchRunStore(generated_root=tmp_path).run_detail("old-run")
    assert detail.variant_intelligence is None
    assert detail.variant_intelligence_request_count == 0
    assert detail.variant_intelligence_artifact_available is False
