from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import subprocess
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
    reference_context = payload["normalization_results"][0]["reference_context_used"]
    assert reference_context["reference_source_id"] == SYNTHETIC_REFERENCE_SOURCE_ID
    assert reference_context["reference_accession"] == "ISP_TESTREF.1"
    assert reference_context["registry_version"] == "insilicopop-reference-windows-0.30.1"
    assert reference_context["fixture_only"] is True
    assert "## Variant Intelligence Preview" in report
    assert "synthetic and fixture-only" in report
    assert "Genome-wide human reference normalization is not available in v0.30" in report
    assert "clinical significance" in report
    assert "pinned reference context (authoritative resolved fixture window)" in report
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
    assert "synthetic and fixture-only" in ui
    assert "Genome-wide human reference normalization is not available in v0.30" in ui
    assert "clinical significance" in ui
    assert "Reference sequence SHA-256 prefix:" in ui
    assert "variantBadgeLabels" in ui
    assert "variantReferencePresentation" in ui


def test_ui_badge_rules_execute_for_success_refusal_unresolved_and_absent_states():
    ui = client.get("/insilicopop/workbench").text
    match = re.search(
        r"// VARIANT_BADGE_LABELS_START(?P<body>.*?)// VARIANT_BADGE_LABELS_END",
        ui,
        flags=re.DOTALL,
    )
    assert match is not None
    node = shutil.which("node")
    assert node is not None, "Node.js is required to execute the Workbench badge contract test"
    states = [
        {
            "supplied_request_snapshot": {"supplied_representation": "TEST1:2:A>G"},
            "validation_status": "valid",
            "normalization_status": "normalized",
            "equivalence_status": "exact_equivalence",
            "human_review_required": True,
        },
        {
            "supplied_request_snapshot": {"supplied_representation": "HLA-A*01:01"},
            "validation_status": "unsupported",
            "normalization_status": "unsupported",
            "equivalence_status": "unsupported_representation",
            "human_review_required": True,
        },
        {
            "supplied_request_snapshot": {"supplied_representation": "unresolved"},
            "validation_status": "cannot_validate",
            "normalization_status": "cannot_normalize",
            "equivalence_status": "unresolved_equivalence",
            "human_review_required": True,
        },
        {},
        {"human_review_required": False},
        {"human_review_required": None},
    ]
    script = (
        match.group("body")
        + "\nconst states = "
        + json.dumps(states)
        + ";\nprocess.stdout.write(JSON.stringify(states.map(variantBadgeLabels)));"
    )
    completed = subprocess.run(
        [node, "-e", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert json.loads(completed.stdout) == [
        ["SUPPLIED", "VALIDATED", "NORMALIZED", "REVIEW REQUIRED"],
        ["SUPPLIED", "UNSUPPORTED", "REVIEW REQUIRED"],
        ["SUPPLIED", "UNRESOLVED", "REVIEW REQUIRED"],
        [],
        [],
        [],
    ]


def test_ui_reference_wording_executes_for_verified_and_unverified_contexts():
    ui = client.get("/insilicopop/workbench").text
    match = re.search(
        r"// VARIANT_REFERENCE_PRESENTATION_START(?P<body>.*?)// VARIANT_REFERENCE_PRESENTATION_END",
        ui,
        flags=re.DOTALL,
    )
    assert match is not None
    node = shutil.which("node")
    assert node is not None, "Node.js is required to execute the Workbench reference-label contract test"
    states = [
        {"reference_context_verified": True},
        {
            "reference_context_verified": False,
            "reference_accession": "CALLER_REF.1",
            "genome_build": "caller-build",
            "chromosome": "caller-contig",
        },
        {},
    ]
    script = (
        match.group("body")
        + "\nconst states = "
        + json.dumps(states)
        + ";\nprocess.stdout.write(JSON.stringify(states.map(variantReferencePresentation)));"
    )
    completed = subprocess.run(
        [node, "-e", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    verified, unverified, absent = json.loads(completed.stdout)
    assert verified["heading"] == "Authoritative pinned reference identity"
    assert verified["accessionLabel"] == "Resolved accession/version"
    for item in (unverified, absent):
        assert item["heading"] == "Supplied/unresolved reference context"
        assert item["accessionLabel"] == "Supplied accession/version"
        assert item["status"] == "No authoritative pinned reference window was resolved."
        assert "Resolved accession/version" not in item.values()


def test_hgvs_syntax_only_report_uses_supplied_unresolved_reference_wording(tmp_path):
    data = clinical_payload()
    variant_request = data["variant_intelligence"]["normalization_requests"][0]
    variant_request.update(
        supplied_representation="ISP_TESTREF.1:g.2A>G",
        representation_type="hgvs_genomic",
        supplied_genome_build="InSilicoPopSynthetic-0.30",
        supplied_reference_accession="ISP_TESTREF.1",
        structured_allele=None,
    )
    result = AgentLoop(generated_root=tmp_path).run(
        query="Validate supplied HGVS syntax",
        uploads={},
        clinical_case_intake=data,
    )
    report = Path(result["generated_files"]["final_report"]["absolute_path"]).read_text(encoding="utf-8")
    public_result = result["variant_intelligence"]["normalization_results"][0]
    assert public_result["reference_context_used"]["reference_context_verified"] is False
    assert "supplied/unresolved reference context" in report
    assert "no authoritative pinned reference window was resolved" in report
    assert "  - pinned reference context" not in report


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
