from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.insilicopop.agent.loop import AgentLoop
from app.insilicopop.agent.workbench import WorkbenchRunStore
from app.insilicopop.cli import _load_v038_fixture, main
from app.insilicopop.clinical.integrated_analysis import build_clinical_case_v038_workspace
from app.insilicopop.clinical.integrated_analysis_models import (
    BcftoolsInvocation,
    CandidateBinding,
    MosaicismMeasurement,
    SourceBinding,
    SuppliedCNVFinding,
    SuppliedMitochondrialFinding,
    TypedRetrievalQuery,
)
from app.insilicopop.clinical.retrieval_registry import (
    ControlledRetrievalService,
    FixtureTransport,
    RetrievalCache,
    TransportResponse,
    validate_allowlisted_url,
)
from app.insilicopop.clinical.tool_execution import BcftoolsAdapter
from app.main import app


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO_ROOT / "examples" / "insilicopop_demo" / "canonical_v038_integrated_analysis.json"
EXPECTED_OUTPUT_PATH = REPO_ROOT / "examples" / "insilicopop_demo" / "expected_v038_integrated_analysis_output.json"
AUTHORIZED_EXPECTED_OUTPUT_PATH = (
    REPO_ROOT / "examples" / "insilicopop_demo" / "expected_v038_wsl_bcftools_authorized_output.json"
)


def _payload() -> dict:
    return _load_v038_fixture(str(FIXTURE_PATH))


def _binding(path: str = "results/synthetic.vcf") -> SourceBinding:
    return SourceBinding(
        source_report_id="REPORT-SYNTH-036",
        source_manifest_entry_path=path,
        source_manifest_entry_sha256="a" * 64,
        source_package_identity_sha256="b" * 64,
        source_manifest_identity_sha256="c" * 64,
    )


def test_v038_fixture_replays_with_stable_identity_and_no_raw_response_body() -> None:
    first = build_clinical_case_v038_workspace(_payload())
    second = build_clinical_case_v038_workspace(_payload())

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.status.value == "partial"
    assert len(first.ranked_candidates) == 4
    assert len(first.excluded_candidates) == 2
    assert {item.pmid for item in first.papers} == {"33623413", "38356310"}
    assert {item.record_id for item in first.database_evidence} >= {"VCV000634837", "rs113993960"}
    assert first.evidence_lifecycle_summary.quarantined_count == 1
    assert first.evidence_lifecycle_summary.excluded_count == 1
    serialized = json.dumps(first.model_dump(mode="json"), sort_keys=True)
    assert "response_body" not in serialized
    assert "Authorization" not in serialized
    first.verify_integrity()


def test_v038_snv_summaries_preserve_source_and_normalized_allele_identity() -> None:
    workspace = build_clinical_case_v038_workspace(_payload())
    first = workspace.normalized_snv_small_indel_summaries[0]

    assert first["reference_allele"] == "A"
    assert first["alternate_allele"] == "G"
    assert first["filter_status"] == "PASS"
    assert first["normalized_reference_allele"] == "A"
    assert first["normalized_alternate_allele"] == "G"
    assert first["source_record_sha256"]
    assert "ref" not in first
    assert "alt" not in first
    assert "filter" not in first


def test_v038_tampering_and_stale_upstream_fail_closed() -> None:
    workspace = build_clinical_case_v038_workspace(_payload())
    tampered = workspace.model_dump(mode="json")
    tampered["papers"][0]["title"] = "tampered"
    with pytest.raises(ValueError, match="identity|integrity"):
        type(workspace).verified_load(tampered)

    stale = _payload()
    stale["integrated_analysis"]["source_package_identity_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="package identity"):
        build_clinical_case_v038_workspace(stale)


def test_v038_strict_multimodal_validation_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        SuppliedCNVFinding(
            finding_id="cnv-1",
            source_binding=_binding(),
            genome_build="GRCh38",
            chromosome="1",
            start=20,
            end=10,
            event_type="deletion",
            assay="array",
        )
    with pytest.raises(ValueError):
        SuppliedCNVFinding(
            finding_id="cnv-2",
            source_binding=_binding(),
            genome_build="GRCh38",
            chromosome="1",
            start=10,
            end=20,
            event_type="deletion",
            population_frequency=True,
            assay="array",
        )
    with pytest.raises(ValueError):
        SuppliedMitochondrialFinding(
            finding_id="mito-1",
            source_binding=_binding("reports/laboratory_report.json"),
            reference_sequence="rCRS",
            coordinate=3243,
            ref="A",
            alt="G",
            heteroplasmy=0.8,
            alternate_read_count=80,
            total_read_count=20,
            depth=20,
            tissue="blood",
            assay="amplicon",
        )
    with pytest.raises(ValueError):
        MosaicismMeasurement(
            measurement_id="mosaic-1",
            source_binding=_binding(),
            variant_allele_fraction=float("nan"),
            tissue="blood",
            assay="amplicon",
        )


def test_typed_queries_and_url_security() -> None:
    with pytest.raises(ValueError):
        TypedRetrievalQuery(source_id="pubmed", rsid="rs1", gene="CFTR", condition_terms=("https://evil.example",))
    with pytest.raises(ValueError):
        validate_allowlisted_url("http://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi", "pubmed")
    with pytest.raises(ValueError):
        validate_allowlisted_url("https://evil.example/entrez/eutils/esearch.fcgi", "pubmed")
    with pytest.raises(ValueError):
        validate_allowlisted_url("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi#fragment", "pubmed")
    with pytest.raises(ValueError):
        validate_allowlisted_url("https://user:password@eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi", "pubmed")


def test_fixture_live_separation_and_cache_lifecycle() -> None:
    query = TypedRetrievalQuery(source_id="ensembl", rsid="rs113993960", assembly="GRCh38")
    blocked = ControlledRetrievalService().retrieve(query)
    assert blocked.event.failure_state.value == "blocked"

    now = [100.0]
    cache = RetrievalCache(clock=lambda: now[0], ttl_seconds=10)
    response = TransportResponse(
        url="https://rest.ensembl.org/vep/human/id/rs113993960",
        body=b'{"vep":[]}',
        content_type="application/json",
    )
    cache.put("key", response)
    assert cache.get("key")[1].value == "hit"
    now[0] = 111.0
    assert cache.get("key")[1].value == "expired"


def test_bcftools_adapter_is_typed_and_never_fabricates_execution() -> None:
    adapter = BcftoolsAdapter()
    result = adapter.execute(BcftoolsInvocation(operation="stats", input_relative_path="examples/insilicopop_demo/canonical_v038_input.vcf"))
    assert result.record.tool_name == "bcftools"
    assert result.record.shell_used is False
    assert result.record.network_disabled is True
    assert result.record.execution_status.value in {"unavailable", "completed", "failed", "timed_out", "blocked"}
    blocked = BcftoolsAdapter(authorization_granted=False).execute(
        BcftoolsInvocation(operation="stats", input_relative_path="examples/insilicopop_demo/canonical_v038_input.vcf")
    )
    assert blocked.record.execution_status.value == "blocked"
    assert blocked.record.availability.value == "auth_required"
    assert blocked.record.error_code == "TOOL_AUTHORIZATION_REQUIRED"
    with pytest.raises(ValueError):
        BcftoolsInvocation(operation="stats", input_relative_path="../outside.vcf")


def test_cli_v038_output_is_byte_stable(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["v038-demo", "--fixture", str(FIXTURE_PATH)]) == 0
    first = capsys.readouterr().out
    assert main(["v038-demo", "--fixture", str(FIXTURE_PATH)]) == 0
    second = capsys.readouterr().out
    assert first == second
    output = json.loads(first)
    expected = json.loads(EXPECTED_OUTPUT_PATH.read_text(encoding="utf-8"))
    assert output == expected
    assert output["workspace_status"] == "partial"
    assert output["identities"]["candidate_analysis_identity_sha256"]
    assert output["identities"]["final_integrity_sha256"]


def test_v038_fixture_api_and_static_workbench_contract() -> None:
    client = TestClient(app)
    fixture_response = client.get("/insilicopop/workbench/fixtures/v038")
    assert fixture_response.status_code == 200
    fixture_payload = fixture_response.json()
    assert fixture_payload["workspace"]["schema_version"] == "0.38"
    assert fixture_payload["workspace"]["status"] == "partial"
    serialized = json.dumps(fixture_payload, sort_keys=True)
    assert "response_body" not in serialized
    assert "Authorization" not in serialized

    ui_response = client.get("/insilicopop/workbench")
    assert ui_response.status_code == 200
    ui = ui_response.text
    assert 'Integrated Analysis Workspace (v0.38)' in ui
    assert 'tablist' in ui
    assert 'integrated-candidate-search' in ui
    assert 'official_pubmed_url' in ui
    assert 'integrity_error' in ui
    assert 'safeToolExecutionDetail' in ui
    assert 'network_isolation_level' in ui
    assert 'No raw tool output, credentials, or approval record is rendered.' in ui
    assert 'value(item, "reference_allele")' in ui
    assert 'value(item, "alternate_allele")' in ui
    assert '.integrated-tab-panel li {' in ui
    assert 'overflow-wrap: anywhere;' in ui

    default_tool = fixture_payload["workspace"]["external_tool_executions"][0]
    assert default_tool["execution_status"] == "blocked"
    assert default_tool["availability"] == "auth_required"
    authorized = json.loads(AUTHORIZED_EXPECTED_OUTPUT_PATH.read_text(encoding="utf-8"))
    assert authorized["workspace_status"] == "complete"
    assert all(item["status"] == "completed" for item in authorized["external_tool_executions"])


def test_agent_state_artifact_and_workbench_tamper_fail_closed(tmp_path: Path) -> None:
    payload = _payload()
    result = AgentLoop(generated_root=tmp_path).run(
        query="v0.38 fixture",
        uploads={},
        clinical_case_intake=payload,
    )
    run_id = result["run_id"]
    artifact_path = tmp_path / run_id / "reproducibility" / "integrated_analysis_workspace.json"
    assert artifact_path.is_file()
    store = WorkbenchRunStore(generated_root=tmp_path)
    verified = store.read_artifact(run_id, "reproducibility/integrated_analysis_workspace.json")
    assert verified.integrity_status == "verified"

    tampered = json.loads(artifact_path.read_text(encoding="utf-8"))
    tampered["status"] = "complete"
    artifact_path.write_text(json.dumps(tampered), encoding="utf-8")
    failed = store.read_artifact(run_id, "reproducibility/integrated_analysis_workspace.json")
    assert failed.integrity_status == "integrity_error"
    assert isinstance(failed.content, dict)
    assert "integrity_error" in failed.content
