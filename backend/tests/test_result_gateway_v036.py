from __future__ import annotations

import base64
import copy
import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.insilicopop.agent.loop import AgentLoop
from app.insilicopop.agent.workbench import WorkbenchRunStore
import app.insilicopop.clinical.result_gateway as gateway_module
import app.main as main_module
from app.insilicopop.clinical.result_gateway import build_result_gateway
from app.insilicopop.clinical.result_gateway_execution import (
    adapter_invocation_identity_payload,
    invoke_registered_adapter,
    registered_adapters,
)
from app.insilicopop.clinical.result_gateway_models import (
    AccreditationEvidence,
    AdapterExecutionStatus,
    AdapterInvocationRequest,
    AdapterOutputSummary,
    GatewayPackageStatus,
    ResultGatewayRequest,
    ResultGatewayResult,
    ReplayStatus,
    SummaryAdapterParameters,
    VerificationState,
    VariantScopeCount,
)
from app.insilicopop.clinical.result_gateway_parser import parse_vcf_bytes
from app.insilicopop.clinical.result_gateway_validation import (
    canonical_json_bytes,
    canonical_payload_sha256,
    manifest_digest,
    validate_safe_relative_path,
)


FIXTURE = Path(__file__).resolve().parents[2] / "examples" / "insilicopop_demo" / "canonical_v036_result_package.json"


def _payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _gateway_payload() -> dict:
    return copy.deepcopy(_payload()["result_gateway"])


def _file_for_role(payload: dict, role: str) -> dict:
    return next(item for item in payload["files"] if item["logical_role"] == role)


def _manifest_for_role(payload: dict, role: str) -> dict:
    return next(item for item in payload["manifest"] if item["logical_role"] == role)


def _bytes_for_role(payload: dict, role: str) -> bytes:
    item = _file_for_role(payload, role)
    if item.get("content_base64") is not None:
        return base64.b64decode(item["content_base64"])
    return item.get("content_text", item.get("content", "")).encode("utf-8")


def _replace_role_bytes(payload: dict, role: str, data: bytes) -> None:
    item = _file_for_role(payload, role)
    item.pop("content_text", None)
    item.pop("content", None)
    item["content_base64"] = base64.b64encode(data).decode("ascii")
    manifest = _manifest_for_role(payload, role)
    manifest["sha256"] = hashlib.sha256(data).hexdigest()
    manifest["byte_size"] = len(data)


def _vcf(records: list[str], *, samples: tuple[str, ...] = (), extra_headers: tuple[str, ...] = ()) -> bytes:
    header = ["##fileformat=VCFv4.2", "##reference=GRCh38", *extra_headers]
    columns = ["#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO"]
    if samples:
        columns.extend(["FORMAT", *samples])
    return ("\n".join([*header, "\t".join(columns), *records]) + "\n").encode("utf-8")


def _fixture_gateway():
    return build_result_gateway(_gateway_payload())


def test_fixture_manifest_parser_adapter_selection_and_provenance_are_deterministic():
    payload = _payload()
    first = build_result_gateway(payload["result_gateway"], pseudonymous_case_id=payload["pseudonymous_case_id"])
    second = build_result_gateway(payload["result_gateway"], pseudonymous_case_id=payload["pseudonymous_case_id"])

    assert first.schema_version == "0.36"
    assert first.package_status == GatewayPackageStatus.PARTIAL
    assert first.manifest_verified is True
    assert first.package_identity_sha256 == second.package_identity_sha256
    assert first.vcf is not None and first.vcf.record_count == 4
    assert len(first.vcf.records) == 5
    assert first.vcf.multiallelic_source_record_count == 1
    assert len(first.accepted_record_ids) == 4
    assert len(first.retained_out_of_scope_record_ids) == 1
    assert {item.status.value for item in first.adapter_results} == {"completed", "blocked", "unavailable"}
    completed = next(item for item in first.adapter_results if item.status.value == "completed")
    assert completed.output_summary is not None
    assert completed.output_summary.record_count == 2
    assert completed.output_summary.record_ids == completed.provenance.selected_record_ids
    assert completed.output_sha256 == next(item for item in second.adapter_results if item.status.value == "completed").output_sha256
    exact_hashes = {item.safe_relative_path: item.sha256 for item in first.input_file_hashes}
    assert all(exact_hashes[item.safe_relative_path] == item.sha256 for item in first.manifest_entries)
    assert first.external_tools_executed is False
    assert all(item.network_call_made is False for item in first.tool_provenance)


def test_fixture_preserves_format_order_samples_genotype_phase_ps_and_unknown_fields():
    parsed = _fixture_gateway().vcf
    assert parsed is not None and parsed.header is not None
    assert parsed.header.sample_names == ("SAMPLE-DEMO", "CONTROL-DEMO")
    record = parsed.records[0]
    assert record.format_keys == ("GT", "DP", "AD", "GQ", "PS", "XY")
    call = record.sample_calls[0]
    assert call.source_token == "0|1:10:6,4:99:123:opaque"
    assert call.genotype is not None
    assert call.genotype.source_token == "0|1"
    assert call.genotype.allele_indices == (0, 1)
    assert call.genotype.ploidy == 2
    assert call.genotype.phase_state.value == "phased"
    assert call.phase_set_source_token == "123"
    assert [item.source_token for item in call.format_values] == ["0|1", "10", "6,4", "99", "123", "opaque"]
    assert call.format_values[-1].key == "XY"
    assert call.format_values[-1].provenance_hash


def test_genotype_haploid_diploid_polyploid_complete_and_partial_missing_calls():
    data = _vcf(
        ["1\t1\tR1\tA\tG,T\t.\tPASS\t.\tGT:DP:PS:ZZ\t1:3:.:hap\t0/1:8:.:dip\t0/1/2:9:.:poly\t./.:.:.:.\t1/.:4:.:partial\t.|.:.:44:phased-missing"],
        samples=("HAP", "DIP", "POLY", "MISSING", "PARTIAL", "PHASED-MISSING"),
    )
    parsed = parse_vcf_bytes("calls.vcf", data, declared_reference_build="GRCh38")
    assert not [item for item in parsed.issues if item.severity.value == "error"]
    calls = parsed.records[0].sample_calls
    assert [(item.genotype.ploidy, item.genotype.phase_state.value) for item in calls[:3]] == [(1, "unknown"), (2, "unphased"), (3, "unphased")]
    assert calls[3].genotype.complete_missing is True
    assert calls[3].genotype.allele_indices == (None, None)
    assert calls[4].genotype.partial_missing is True
    assert calls[4].genotype.allele_indices == (1, None)
    assert calls[5].genotype.source_token == ".|."
    assert calls[5].genotype.phase_state.value == "phased"
    assert calls[5].phase_set_source_token == "44"
    assert [item.state.value for item in parsed.records[0].selected_alt_presence] == ["present", "present", "present", "unknown", "present", "unknown"]


def test_multiallelic_decomposition_keeps_identical_source_genotype_and_derives_presence_only():
    parsed = _fixture_gateway().vcf
    multi = [item for item in parsed.records if item.source_alt_count == 2]
    assert len(multi) == 2
    assert multi[0].sample_calls == multi[1].sample_calls
    assert multi[0].sample_calls[0].genotype.source_token == "1/2"
    assert multi[0].sample_calls[0].genotype.allele_indices == (1, 2)
    assert [item.source_alt_index for item in multi] == [1, 2]
    assert multi[0].selected_alt_presence[0].state.value == "present"
    assert multi[1].selected_alt_presence[0].state.value == "present"
    assert all(item.decomposition_performed for item in multi)


@pytest.mark.parametrize(
    ("format_token", "sample_token", "code"),
    [
        ("GT:DP", "0/1", "vcf_sample_format_malformed"),
        ("GT:DP", "0/1:4:extra", "vcf_sample_format_malformed"),
        ("GT::DP", "0/1:.:4", "vcf_format_key_malformed"),
        ("GT:DP:GT", "0/1:4:0/1", "vcf_format_key_duplicate"),
    ],
)
def test_malformed_format_and_sample_counts_fail_explicitly(format_token: str, sample_token: str, code: str):
    parsed = parse_vcf_bytes(
        "bad-format.vcf",
        _vcf([f"1\t1\tR1\tA\tG\t.\tPASS\t.\t{format_token}\t{sample_token}"], samples=("S1",)),
        declared_reference_build="GRCh38",
    )
    assert code in {item.code for item in parsed.issues}
    assert parsed.records == ()


def test_record_sample_column_count_mismatch_fails_without_dropping_columns():
    parsed = parse_vcf_bytes(
        "bad-columns.vcf",
        _vcf(["1\t1\tR1\tA\tG\t.\tPASS\t.\tGT\t0/1"], samples=("S1", "S2")),
        declared_reference_build="GRCh38",
    )
    assert "vcf_record_column_count_mismatch" in {item.code for item in parsed.issues}
    assert parsed.records == ()


def test_unknown_format_serialization_is_deterministic_and_detached():
    data = _vcf(["1\t1\tR1\tA\tG\t.\tPASS\tX=opaque\tGT:UNSEEN\t0/1:value"], samples=("S1",))
    first = parse_vcf_bytes("unknown-format.vcf", data, declared_reference_build="GRCh38")
    second = parse_vcf_bytes("unknown-format.vcf", data, declared_reference_build="GRCh38")
    assert canonical_json_bytes(first.model_dump(mode="json")) == canonical_json_bytes(second.model_dump(mode="json"))
    dump = first.model_dump(mode="json")
    dump["records"][0]["sample_calls"][0]["format_values"][1]["source_token"] = "mutated"
    assert first.records[0].sample_calls[0].format_values[1].source_token == "value"


def test_info_definitions_flags_and_unknown_well_formed_fields_are_preserved():
    data = _vcf(
        ["1\t1\tR1\tA\tG\t.\tPASS\tSOMATIC;KNOWN=abc;UNKNOWN=opaque"],
        extra_headers=(
            '##INFO=<ID=SOMATIC,Number=0,Type=Flag,Description="Supplied flag">',
            '##INFO=<ID=KNOWN,Number=1,Type=String,Description="Known field">',
        ),
    )
    parsed = parse_vcf_bytes("info.vcf", data, declared_reference_build="GRCh38")
    assert not [item for item in parsed.issues if item.severity.value == "error"]
    fields = {item.key: item for item in parsed.records[0].supplied_annotations}
    assert fields["SOMATIC"].is_flag is True and fields["SOMATIC"].declared_type == "Flag"
    assert fields["UNKNOWN"].declared_in_header is False
    assert fields["UNKNOWN"].source_token == "UNKNOWN=opaque"


@pytest.mark.parametrize(
    ("info", "code"),
    [
        ("A=1;A=2", "vcf_info_duplicate_key"),
        ("A=1;;B=2", "vcf_info_token_empty"),
        ("UNKNOWN", "vcf_info_bare_nonflag"),
        ("VALUE", "vcf_info_bare_nonflag"),
        ("FLAG=true", "vcf_info_flag_with_value"),
        ("=x", "vcf_info_token_malformed"),
    ],
)
def test_malformed_or_duplicate_info_is_rejected(info: str, code: str):
    data = _vcf(
        [f"1\t1\tR1\tA\tG\t.\tPASS\t{info}"],
        extra_headers=(
            '##INFO=<ID=FLAG,Number=0,Type=Flag,Description="Flag">',
            '##INFO=<ID=VALUE,Number=1,Type=String,Description="Value">',
        ),
    )
    parsed = parse_vcf_bytes("bad-info.vcf", data, declared_reference_build="GRCh38")
    assert code in {item.code for item in parsed.issues}
    assert parsed.records == ()


def test_conflicting_reference_headers_block_and_identical_repeats_warn_deterministically():
    conflict = _vcf(["1\t1\tR1\tA\tG\t.\tPASS\t."], extra_headers=("##assembly=GRCh37",))
    parsed = parse_vcf_bytes("conflict.vcf", conflict, declared_reference_build="GRCh38")
    assert "conflicting_reference_declarations" in {item.code for item in parsed.issues}
    assert parsed.header.build_validation == "mismatch"

    repeated = _vcf(["1\t1\tR1\tA\tG\t.\tPASS\t."], extra_headers=("##assembly=GRCh38",))
    first = parse_vcf_bytes("repeat.vcf", repeated, declared_reference_build="GRCh38")
    second = parse_vcf_bytes("repeat.vcf", repeated, declared_reference_build="GRCh38")
    assert first.header.reference_declarations == ("GRCh38", "GRCh38")
    assert "repeated_reference_declaration" in {item.code for item in first.issues}
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_out_of_scope_reasons_are_typed_and_only_repeat_or_mosaic_when_explicit():
    long_ref = "A" * 51
    data = _vcf(
        [
            "1\t1\tREP\tA\t<STR>\t.\tPASS\tSVTYPE=STR",
            "1\t2\tMOS\tA\tG\t.\tPASS\tMOSAIC",
            "MT\t3\tMITO\tA\tG\t.\tPASS\t.",
            "1\t4\tSYM\tA\t<UNK>\t.\tPASS\t.",
            "1\t5\tSV\tA\tA]2:10]\t.\tPASS\t.",
            "1\t6\tCNV\tA\t<CNV>\t.\tPASS\tSVTYPE=CNV",
            f"1\t7\tLARGE\t{long_ref}\tA\t.\tPASS\t.",
            "1\t8\tLOWAF\tA\tG\t.\tPASS\tAF=0.01",
        ],
        extra_headers=(
            '##INFO=<ID=SVTYPE,Number=1,Type=String,Description="Type">',
            '##INFO=<ID=MOSAIC,Number=0,Type=Flag,Description="Explicit mosaic">',
            '##INFO=<ID=AF,Number=A,Type=Float,Description="Frequency">',
        ),
    )
    parsed = parse_vcf_bytes("scope.vcf", data, declared_reference_build="GRCh38")
    by_source = {item.source_id: item for item in parsed.records}
    assert by_source["REP"].variant_scope.value == "repeat_out_of_scope"
    assert by_source["REP"].out_of_scope_reason_code.value == "explicit_repeat"
    assert by_source["MOS"].variant_scope.value == "mosaic_out_of_scope"
    assert by_source["MITO"].out_of_scope_reason_code.value == "mitochondrial_variant"
    assert by_source["SYM"].out_of_scope_reason_code.value == "symbolic_allele"
    assert by_source["SV"].out_of_scope_reason_code.value == "structural_variant"
    assert by_source["CNV"].out_of_scope_reason_code.value == "copy_number_variant"
    assert by_source["LARGE"].out_of_scope_reason_code.value == "large_indel"
    assert by_source["LOWAF"].variant_scope.value == "snv"


def test_adapter_registry_declares_strict_immutable_parameter_schemas():
    definitions = {item.adapter_id: item for item in registered_adapters()}
    summary = definitions["deterministic_supplied_result_summary"]
    assert isinstance(summary.default_parameters, SummaryAdapterParameters)
    assert summary.parameter_schema_id == summary.default_parameters.parameter_schema_id
    assert summary.parameter_schema_version == summary.default_parameters.parameter_schema_version
    assert definitions["bcftools_left_normalization"].availability.value == "unavailable"
    assert isinstance(registered_adapters(), tuple)
    with pytest.raises(ValidationError):
        summary.default_parameters.mode = "anything"


@pytest.mark.parametrize(
    "parameters",
    [
        {"mode": "summary_only", "unknown": True},
        {"mode": 1},
        {"mode": True},
        {"mode": "summary; unsafe"},
        {"command": "echo unsafe"},
        {"url": "https://example.test"},
        {"parameter_schema_id": "insilicopop.summary.parameters", "parameter_schema_version": "2.0", "mode": "summary_only"},
    ],
)
def test_adapter_parameters_reject_unknown_wrong_typed_or_shell_like_values(parameters: dict):
    with pytest.raises(ValidationError):
        AdapterInvocationRequest(invocation_id="BAD-036", adapter_id="deterministic_supplied_result_summary", parameters=parameters)


def test_adapter_selector_omitted_empty_unknown_out_of_scope_and_version_semantics():
    gateway = _fixture_gateway()
    hashes = [item.sha256 for item in gateway.input_file_hashes]
    common = dict(input_manifest_sha256=gateway.input_manifest_sha256, package_identity_sha256=gateway.package_identity_sha256, input_file_hashes=hashes, records=gateway.vcf.records, vcf=gateway.vcf)

    omitted = invoke_registered_adapter(AdapterInvocationRequest(invocation_id="ALL", adapter_id="deterministic_supplied_result_summary", parameters={}, human_review_approved=True), **common)
    assert omitted.status.value == "completed"
    assert omitted.invocation.selector_mode == "all_eligible"
    assert omitted.output_summary.record_count == len(gateway.accepted_record_ids)

    empty = invoke_registered_adapter(AdapterInvocationRequest(invocation_id="EMPTY", adapter_id="deterministic_supplied_result_summary", input_record_ids=[], parameters={}, human_review_approved=True), **common)
    assert empty.status.value == "completed"
    assert empty.invocation.selector_mode == "explicit"
    assert empty.output_summary.record_count == 0
    assert empty.provenance.selected_record_ids == ()

    duplicate = invoke_registered_adapter(
        AdapterInvocationRequest(invocation_id="DUP", adapter_id="deterministic_supplied_result_summary", input_record_ids=[gateway.accepted_record_ids[0], gateway.accepted_record_ids[0]], parameters={}),
        **common,
    )
    assert duplicate.status.value == "blocked"
    assert duplicate.invocation.requested_input_record_ids == (gateway.accepted_record_ids[0], gateway.accepted_record_ids[0])
    assert duplicate.invocation.selected_input_record_ids == (gateway.accepted_record_ids[0],)
    assert duplicate.invocation.selector_validation_issues[0].code == "duplicate_input_record_id"

    unknown = invoke_registered_adapter(AdapterInvocationRequest(invocation_id="UNKNOWN", adapter_id="deterministic_supplied_result_summary", input_record_ids=["missing-record"], parameters={}, human_review_approved=True), **common)
    assert unknown.status.value == "blocked" and "Unknown" in unknown.errors[0]

    out_of_scope = invoke_registered_adapter(AdapterInvocationRequest(invocation_id="OUT", adapter_id="deterministic_supplied_result_summary", input_record_ids=[gateway.retained_out_of_scope_record_ids[0]], parameters={}, human_review_approved=True), **common)
    assert out_of_scope.status.value == "blocked" and "Out-of-scope" in out_of_scope.errors[0]

    mismatch = invoke_registered_adapter(AdapterInvocationRequest(invocation_id="VERSION", adapter_id="deterministic_supplied_result_summary", adapter_version="0.35.0", parameters={}, human_review_approved=True), **common)
    assert mismatch.status.value == "blocked" and "version" in mismatch.errors[0]


def test_unavailable_adapter_validates_selector_and_parameter_shape_before_unavailable():
    gateway = _fixture_gateway()
    common = dict(input_manifest_sha256=gateway.input_manifest_sha256, package_identity_sha256=gateway.package_identity_sha256, input_file_hashes=[item.sha256 for item in gateway.input_file_hashes], records=gateway.vcf.records, vcf=gateway.vcf)
    unknown = invoke_registered_adapter(AdapterInvocationRequest(invocation_id="U1", adapter_id="bcftools_left_normalization", input_record_ids=["missing"], parameters={}), **common)
    assert unknown.status.value == "blocked"
    valid = invoke_registered_adapter(AdapterInvocationRequest(invocation_id="U2", adapter_id="bcftools_left_normalization", input_record_ids=[], parameters={}), **common)
    assert valid.status.value == "unavailable"
    with pytest.raises(ValidationError):
        AdapterInvocationRequest(invocation_id="U3", adapter_id="bcftools_left_normalization", parameters={"mode": "wrong"})


def _set_path(payload: dict, role: str, path: str) -> None:
    _manifest_for_role(payload, role)["safe_relative_path"] = path
    _file_for_role(payload, role)["safe_relative_path"] = path


@pytest.mark.parametrize(
    ("first", "second", "code"),
    [
        ("QC/shared.json", "qc/SHARED.json", "manifest_path_collision"),
        ("qc/résumé.json", "qc/re\u0301sume\u0301.json", "manifest_path_collision"),
    ],
)
def test_casefolded_and_unicode_equivalent_paths_fail_closed(monkeypatch, first: str, second: str, code: str):
    payload = _gateway_payload()
    _set_path(payload, "qc", first)
    _set_path(payload, "coverage", second)
    called = []
    monkeypatch.setattr(gateway_module, "parse_vcf_bytes", lambda *args, **kwargs: called.append(True))
    result = build_result_gateway(payload)
    assert result.package_status == GatewayPackageStatus.BLOCKED
    assert result.manifest_verified is False
    assert result.vcf is None and result.adapter_results == ()
    assert code in {item.code for item in result.errors}
    assert called == []


def test_safe_path_normalizes_nfc_and_rejects_unsafe_forms():
    assert validate_safe_relative_path("reports/re\u0301sume\u0301.json") == "reports/résumé.json"
    for path in ("../escape", "/absolute", "C:/absolute", "https://example.test/a", "a\\b", "a//b", "a/./b"):
        with pytest.raises(ValueError):
            validate_safe_relative_path(path)


def test_duplicate_missing_and_unknown_roles_are_combined_typed_structural_errors():
    payload = _gateway_payload()
    _manifest_for_role(payload, "qc")["logical_role"] = "structured_laboratory_report"
    _file_for_role(payload, "qc")["logical_role"] = "structured_laboratory_report"
    _manifest_for_role(payload, "assay_metadata")["logical_role"] = "unknown_role"
    _file_for_role(payload, "assay_metadata")["logical_role"] = "unknown_role"
    result = build_result_gateway(payload)
    codes = [item.code for item in result.errors]
    assert result.manifest_verified is False and result.vcf is None
    assert "duplicate_logical_role" in codes
    assert "required_logical_role_missing" in codes
    assert "unknown_logical_role" in codes


def test_missing_required_role_blocks_without_parsing():
    payload = _gateway_payload()
    payload["manifest"] = [item for item in payload["manifest"] if item["logical_role"] != "coverage"]
    payload["files"] = [item for item in payload["files"] if item["logical_role"] != "coverage"]
    result = build_result_gateway(payload)
    assert result.package_status == GatewayPackageStatus.BLOCKED
    assert result.vcf is None
    assert [item.code for item in result.errors].count("required_logical_role_missing") == 2


@pytest.mark.parametrize("kind", ["media", "extension", "content"])
def test_role_media_extension_and_content_spoofing_are_rejected_before_domain_parsing(monkeypatch, kind: str):
    payload = _gateway_payload()
    if kind == "media":
        _manifest_for_role(payload, "vcf")["media_type"] = "application/json"
        _file_for_role(payload, "vcf")["media_type"] = "application/json"
        expected = "role_media_type_not_allowed"
    elif kind == "extension":
        _set_path(payload, "vcf", "results/synthetic.json")
        expected = "role_extension_mismatch"
    else:
        qc_bytes = _bytes_for_role(payload, "qc")
        coverage_bytes = _bytes_for_role(payload, "coverage")
        _replace_role_bytes(payload, "qc", coverage_bytes)
        _replace_role_bytes(payload, "coverage", qc_bytes)
        expected = "role_content_mismatch"
    called = []
    monkeypatch.setattr(gateway_module, "parse_vcf_bytes", lambda *args, **kwargs: called.append(True))
    result = build_result_gateway(payload)
    assert expected in {item.code for item in result.errors}
    assert result.manifest_verified is False and result.vcf is None and result.adapter_results == ()
    assert called == []


def test_hash_and_size_mismatch_combination_fails_closed_before_parsers(monkeypatch):
    payload = _gateway_payload()
    payload["manifest"][0]["sha256"] = "0" * 64
    payload["manifest"][1]["byte_size"] += 1
    called = []
    monkeypatch.setattr(gateway_module, "parse_vcf_bytes", lambda *args, **kwargs: called.append(True))
    result = build_result_gateway(payload)
    assert {"manifest_hash_mismatch", "manifest_byte_size_mismatch"}.issubset({item.code for item in result.errors})
    assert result.package_status == GatewayPackageStatus.BLOCKED
    assert result.manifest_verified is False and result.vcf is None and result.adapter_results == ()
    assert called == []


def test_complete_package_identity_replays_exactly_and_is_order_independent():
    payload = _gateway_payload()
    first = build_result_gateway(payload)
    reordered = copy.deepcopy(payload)
    reordered["manifest"].reverse()
    reordered["files"].reverse()
    assert build_result_gateway(reordered).package_identity_sha256 == first.package_identity_sha256

    replay = copy.deepcopy(payload)
    replay["previous_package_identity_sha256"] = first.package_identity_sha256
    replayed = build_result_gateway(replay)
    assert replayed.replay_status == ReplayStatus.REPLAYED
    assert replayed.package_identity_sha256 == first.package_identity_sha256


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("package_version", "0.36.1"),
        ("declared_reference_build", "GRCh37"),
        ("expected_sample_id", "SAMPLE-OTHER"),
        ("declared_case_id", "CASE-OTHER"),
    ],
)
def test_package_identity_changes_for_package_metadata(field: str, value: str):
    baseline = _fixture_gateway().package_identity_sha256
    changed = _gateway_payload()
    changed[field] = value
    assert build_result_gateway(changed).package_identity_sha256 != baseline


def test_package_identity_changes_for_manifest_assay_bytes_intent_and_selectors():
    baseline_payload = _gateway_payload()
    baseline = build_result_gateway(baseline_payload).package_identity_sha256

    manifest_change = copy.deepcopy(baseline_payload)
    manifest_change["manifest"][0]["parser_version"] = "parser-semantic-change"
    assert build_result_gateway(manifest_change).package_identity_sha256 != baseline

    assay_change = copy.deepcopy(baseline_payload)
    assay = json.loads(_bytes_for_role(assay_change, "assay_metadata"))
    assay["blind_spots"].append("new supplied blind spot")
    _replace_role_bytes(assay_change, "assay_metadata", json.dumps(assay, separators=(",", ":")).encode())
    assert build_result_gateway(assay_change).package_identity_sha256 != baseline

    selector_change = copy.deepcopy(baseline_payload)
    selector_change["adapter_invocations"][0]["input_record_ids"] = selector_change["adapter_invocations"][0]["input_record_ids"][:1]
    assert build_result_gateway(selector_change).package_identity_sha256 != baseline

    intent_change = copy.deepcopy(baseline_payload)
    intent_change["tool_analysis_intent"] = {
        "intent_id": "INTENT-036",
        "analysis_kind": "summary",
        "adapter_id": "deterministic_supplied_result_summary",
        "parameters": {"mode": "summary_only"},
        "target_record_ids": [],
        "human_review_approved": True,
    }
    assert build_result_gateway(intent_change).package_identity_sha256 != baseline


def test_stale_package_reuse_compares_complete_identity_not_manifest_only():
    payload = _gateway_payload()
    baseline = build_result_gateway(payload)
    changed = copy.deepcopy(payload)
    changed["package_version"] = "0.36.1"
    changed["previous_package_identity_sha256"] = baseline.package_identity_sha256
    stale = build_result_gateway(changed)
    assert stale.package_status == GatewayPackageStatus.STALE
    assert stale.replay_status == ReplayStatus.STALE
    assert "stale_replay_blocked" in {item.code for item in stale.errors}

    legacy = copy.deepcopy(payload)
    legacy["previous_input_manifest_sha256"] = baseline.input_manifest_sha256
    assert build_result_gateway(legacy).replay_status == ReplayStatus.STALE


def test_gateway_models_are_deeply_immutable_and_serialization_is_detached():
    source = _gateway_payload()
    request = ResultGatewayRequest.model_validate(source)
    source["manifest"][0]["sha256"] = "0" * 64
    assert request.manifest[0].sha256 != "0" * 64
    result = build_result_gateway(request)
    identity = result.package_identity_sha256
    output_hash = next(item.output_sha256 for item in result.adapter_results if item.output_sha256)

    mutation_probes = [
        lambda: result.manifest_entries.append(None),
        lambda: result.input_file_hashes.append(None),
        lambda: result.vcf.records.append(None),
        lambda: result.vcf.records[0].sample_calls.append(None),
        lambda: result.vcf.records[0].sample_calls[0].format_values.append(None),
        lambda: result.adapter_definitions.append(None),
        lambda: result.adapter_results[0].errors.append("x"),
        lambda: setattr(result.adapter_results[0].invocation.parameters, "mode", "x"),
        lambda: setattr(result.errors, "anything", "x"),
    ]
    for probe in mutation_probes:
        with pytest.raises((AttributeError, TypeError, ValidationError)):
            probe()

    detached = result.model_dump(mode="json")
    detached["input_file_hashes"]["changed"] = "0" * 64
    detached["manifest_entries"][0]["sha256"] = "0" * 64
    detached["vcf"]["records"][0]["sample_calls"][0]["format_values"][0]["source_token"] = "changed"
    detached["adapter_results"][0]["invocation"]["parameters"]["mode"] = "changed"
    assert result.package_identity_sha256 == identity
    assert next(item.output_sha256 for item in result.adapter_results if item.output_sha256) == output_hash
    assert all(item.safe_relative_path != "changed" for item in result.input_file_hashes)
    assert result.vcf.records[0].sample_calls[0].format_values[0].source_token != "changed"


@pytest.mark.parametrize("hostile", ["verified", "VERIFIED", "independently_verified", "Independently Verified", "yes", "trusted"])
def test_package_accreditation_wording_cannot_promote_trust(hostile: str):
    payload = _gateway_payload()
    lab = json.loads(_bytes_for_role(payload, "structured_laboratory_report"))
    lab["accreditation_status"] = hostile
    lab["accreditation_scope_verification"] = hostile
    lab["accreditation_claims"][0]["supplied_status_text"] = hostile
    lab["trusted_accreditation_evidence"] = [{"verification_status": "independently_verified", "certificate": "hostile"}]
    _replace_role_bytes(payload, "structured_laboratory_report", json.dumps(lab, separators=(",", ":")).encode())
    result = build_result_gateway(payload)
    report = result.laboratory_report
    assert report.accreditation_status == VerificationState.SUPPLIED_BUT_UNVERIFIED
    assert report.accreditation_scope_verification == VerificationState.SUPPLIED_BUT_UNVERIFIED
    assert all(item.verification_state == VerificationState.SUPPLIED_BUT_UNVERIFIED for item in report.accreditation_claims)
    assert report.trusted_accreditation_evidence == ()
    assert any("trusted evidence channel" in item.message for item in result.warnings)


def test_typed_accreditation_evidence_requires_trusted_provenance_fields():
    with pytest.raises(ValidationError):
        AccreditationEvidence(accreditation_body_or_standard="NABL", certificate_or_reference_identifier="CERT")
    evidence = AccreditationEvidence(
        accreditation_body_or_standard="NABL",
        certificate_or_reference_identifier="CERT-036",
        supplied_scope="Molecular genetics",
        evidence_digest="a" * 64,
        evidence_type="reviewed_certificate",
        verifier_provenance="trusted reviewer registry",
        verification_timestamp="2026-08-11T00:00:00Z",
        reviewer_action_identifier="REVIEW-036",
        verification_status="independently_verified",
        verification_reason="Certificate and scope reviewed through a trusted action.",
        trusted_channel="trusted_human_review_action",
    )
    assert evidence.verification_status == "independently_verified"


def test_agent_response_and_reproducibility_persist_gateway_without_raw_package_content(tmp_path):
    response = AgentLoop(generated_root=tmp_path).run(query="review supplied result package", uploads={}, clinical_case_intake=_payload())
    assert response["result_gateway"]["schema_version"] == "0.36"
    assert response["final_state"]["result_gateway"]["manifest_verified"] is True
    gateway_artifact = Path(response["reproducibility_bundle"]["path"]) / "result_gateway.json"
    artifact_text = gateway_artifact.read_text(encoding="utf-8")
    assert "content_base64" not in artifact_text
    assert "package_identity_sha256" in artifact_text
    assert "SAMPLE-DEMO" in artifact_text
    assert any(item.get("event") == "controlled_result_gateway_completed" for item in response["agent_trace"])


def test_v035_handoff_stages_9_and_10_remain_compatible(tmp_path):
    response = AgentLoop(generated_root=tmp_path).run(query="review supplied result package stages", uploads={}, clinical_case_intake=_payload())
    stages = {item["stage_id"]: item for item in response["handoff_workspace"]["case_stages"]}
    assert stages["result_intake"]["status"] == "completed_for_draft_use"
    assert stages["qc_assay_scope"]["status"] == "completed_for_draft_use"
    assert set(stages["result_intake"]["source_classifications"]) == {"supplied_fact", "deterministic_finding"}

    blocked = _payload()
    blocked["result_gateway"]["manifest"][0]["sha256"] = "0" * 64
    blocked_response = AgentLoop(generated_root=tmp_path / "blocked").run(query="review blocked supplied result package", uploads={}, clinical_case_intake=blocked)
    blocked_stages = {item["stage_id"]: item for item in blocked_response["handoff_workspace"]["case_stages"]}
    assert blocked_stages["result_intake"]["status"] == "blocked"
    assert blocked_stages["qc_assay_scope"]["status"] == "blocked"


def test_existing_agent_api_preview_and_persistence_expose_gateway(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "AgentLoop", lambda: AgentLoop(generated_root=tmp_path))
    monkeypatch.setattr(main_module, "WorkbenchRunStore", lambda: WorkbenchRunStore(generated_root=tmp_path))
    client = TestClient(main_module.app)
    fixture_response = client.get("/insilicopop/workbench/fixtures/v036")
    assert fixture_response.status_code == 200
    fixture_body = fixture_response.json()
    assert fixture_body["gateway_preview"]["manifest_verified"] is True
    assert len(fixture_body["adapter_definitions"]) == 3

    preview = client.post("/insilicopop/workbench/result-gateway/preview", json=_payload())
    assert preview.status_code == 200
    assert preview.json()["gateway_preview"]["package_identity_sha256"]

    response = client.post("/insilicopop/agent/run", data={"query": "review supplied result package", "memory_mode": "compact", "clinical_case_intake": json.dumps(_payload())})
    assert response.status_code == 200
    body = response.json()
    run_id = body["run_id"]
    assert body["result_gateway"]["package_status"] == "partial"
    detail = client.get(f"/insilicopop/agent/runs/{run_id}")
    assert detail.status_code == 200 and detail.json()["result_gateway"]["manifest_verified"] is True
    artifact = client.get(f"/insilicopop/agent/runs/{run_id}/artifacts/reproducibility/result_gateway.json")
    assert artifact.status_code == 200
    assert "content_base64" not in json.dumps(artifact.json()["content"])


class _WorkbenchParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids: set[str] = set()
        self.positive_tabindex: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(values["id"])
        tabindex = values.get("tabindex")
        if tabindex and tabindex.lstrip("-").isdigit() and int(tabindex) > 0:
            self.positive_tabindex.append(values.get("id", tag))


def test_workbench_rendered_dom_has_complete_gateway_workflow_and_natural_tab_order():
    client = TestClient(main_module.app)
    response = client.get("/insilicopop/workbench")
    assert response.status_code == 200
    html = response.text
    parser = _WorkbenchParser()
    parser.feed(html)
    required = {
        "gateway-package-file", "gateway-load-fixture", "gateway-reject-package",
        "gateway-manifest-preview", "gateway-sample-review", "gateway-build-confirmation",
        "gateway-qc-review", "gateway-adapter-select", "gateway-parameter-controls",
        "gateway-record-selector", "gateway-human-approval", "gateway-execution-result",
    }
    assert required.issubset(parser.ids)
    assert parser.positive_tabindex == []
    assert ':focus-visible' in html
    assert "grid-template-columns: minmax(0, 1fr)" in html
    assert "technical-table-wrap" in html and "overflow-x: auto" in html
    assert "draft_not_clinically_approved" in html
    assert "No diagnosis" in html


def test_blocked_preview_api_returns_typed_errors_without_parsed_or_adapter_state():
    payload = _payload()
    payload["result_gateway"]["manifest"][0]["sha256"] = "0" * 64
    body = TestClient(main_module.app).post("/insilicopop/workbench/result-gateway/preview", json=payload).json()["gateway_preview"]
    assert body["manifest_verified"] is False
    assert body["vcf"] is None
    assert body["adapter_results"] == []
    assert "manifest_hash_mismatch" in {item["code"] for item in body["errors"]}


def test_manifest_only_hash_remains_distinct_from_complete_package_identity():
    request = ResultGatewayRequest.model_validate(_gateway_payload())
    result = build_result_gateway(request)
    assert result.input_manifest_sha256 == manifest_digest(request.manifest)
    assert result.package_identity_sha256 != result.input_manifest_sha256


@pytest.mark.parametrize(
    ("canonical_role", "alias"),
    [
        ("vcf", "variant"),
        ("vcf", "variants"),
        ("vcf", "VCF"),
        ("vcf", "vcf "),
        ("structured_laboratory_report", "lab_report"),
        ("structured_laboratory_report", "laboratory_report"),
        ("structured_laboratory_report", "STRUCTURED_LABORATORY_REPORT"),
    ],
)
def test_alias_role_rejected_before_parsing(monkeypatch, canonical_role: str, alias: str):
    payload = _gateway_payload()
    _manifest_for_role(payload, canonical_role)["logical_role"] = alias
    _file_for_role(payload, canonical_role)["logical_role"] = alias
    parser_calls: list[bool] = []
    adapter_calls: list[bool] = []
    monkeypatch.setattr(gateway_module, "parse_vcf_bytes", lambda *args, **kwargs: parser_calls.append(True))
    monkeypatch.setattr(gateway_module, "invoke_registered_adapter", lambda *args, **kwargs: adapter_calls.append(True))

    result = build_result_gateway(payload)

    codes = {item.code for item in result.errors}
    assert result.package_status == GatewayPackageStatus.BLOCKED
    assert result.manifest_verified is False
    assert result.vcf is None and result.adapter_results == ()
    assert {"unknown_logical_role", "required_logical_role_missing"}.issubset(codes)
    assert parser_calls == [] and adapter_calls == []


def test_mixed_canonical_and_alias_roles_are_rejected_and_exact_five_roles_pass():
    canonical = _gateway_payload()
    expected = {"vcf", "structured_laboratory_report", "qc", "coverage", "assay_metadata"}
    assert {item["logical_role"] for item in canonical["manifest"]} == expected
    assert {item["logical_role"] for item in canonical["files"]} == expected
    assert build_result_gateway(canonical).manifest_verified is True

    mixed = copy.deepcopy(canonical)
    _manifest_for_role(mixed, "vcf")["logical_role"] = "variant"
    result = build_result_gateway(mixed)
    assert result.manifest_verified is False
    assert result.vcf is None and result.adapter_results == ()
    assert {"unknown_logical_role", "required_logical_role_missing", "manifest_logical_role_mismatch"}.issubset(
        {item.code for item in result.errors}
    )


def test_execution_identity_binds_package_identity_and_manifest_identity_and_reconstructs():
    baseline_payload = _gateway_payload()
    baseline = build_result_gateway(baseline_payload)
    completed = next(item for item in baseline.adapter_results if item.invocation.invocation_id == "ADAPTER-SUCCESS-036")
    request = next(item for item in ResultGatewayRequest.model_validate(baseline_payload).adapter_invocations if item.invocation_id == "ADAPTER-SUCCESS-036")
    identity_payload = adapter_invocation_identity_payload(
        request,
        completed.adapter,
        package_identity_sha256=completed.invocation.package_identity_sha256,
        input_manifest_sha256=completed.invocation.input_manifest_sha256,
        input_file_hashes=completed.invocation.input_file_hashes,
        requested_input_record_ids=completed.invocation.requested_input_record_ids,
        selected_input_record_ids=completed.invocation.selected_input_record_ids,
        selector_validation_issues=completed.invocation.selector_validation_issues,
    )
    assert canonical_payload_sha256(identity_payload) == completed.invocation.invocation_sha256

    version_changed = copy.deepcopy(baseline_payload)
    version_changed["package_version"] = "fixture-2"
    changed = build_result_gateway(version_changed)
    changed_completed = next(item for item in changed.adapter_results if item.invocation.invocation_id == "ADAPTER-SUCCESS-036")
    assert changed.package_identity_sha256 != baseline.package_identity_sha256
    assert changed_completed.invocation.invocation_sha256 != completed.invocation.invocation_sha256

    hashes = [item.sha256 for item in baseline.input_file_hashes]
    with pytest.raises(TypeError):
        invoke_registered_adapter(
            request,
            input_manifest_sha256=baseline.input_manifest_sha256,
            input_file_hashes=hashes,
            records=baseline.vcf.records,
            vcf=baseline.vcf,
        )
    direct_common = dict(package_identity_sha256=baseline.package_identity_sha256, input_file_hashes=hashes, records=baseline.vcf.records, vcf=baseline.vcf)
    manifest_a = invoke_registered_adapter(request, input_manifest_sha256="a" * 64, **direct_common)
    manifest_b = invoke_registered_adapter(request, input_manifest_sha256="b" * 64, **direct_common)
    assert manifest_a.invocation.invocation_sha256 != manifest_b.invocation.invocation_sha256

    reordered = copy.deepcopy(baseline_payload)
    reordered["manifest"].reverse()
    reordered["files"].reverse()
    reordered_result = build_result_gateway(reordered)
    reordered_completed = next(item for item in reordered_result.adapter_results if item.invocation.invocation_id == "ADAPTER-SUCCESS-036")
    assert reordered_result.package_identity_sha256 == baseline.package_identity_sha256
    assert reordered_completed.invocation.invocation_sha256 == completed.invocation.invocation_sha256


def test_blocked_invocation_binds_original_invalid_selectors_and_valid_selection():
    gateway = _fixture_gateway()
    hashes = [item.sha256 for item in gateway.input_file_hashes]
    common = dict(input_manifest_sha256=gateway.input_manifest_sha256, package_identity_sha256=gateway.package_identity_sha256, input_file_hashes=hashes, records=gateway.vcf.records, vcf=gateway.vcf)

    def invoke(record_ids: list[str], invocation_id: str = "SELECTOR-IDENTITY"):
        return invoke_registered_adapter(
            AdapterInvocationRequest(invocation_id=invocation_id, adapter_id="deterministic_supplied_result_summary", input_record_ids=record_ids, parameters={}, human_review_approved=True),
            **common,
        )

    missing_one = invoke(["missing-one"])
    missing_two = invoke(["missing-two"])
    assert missing_one.status == missing_two.status == AdapterExecutionStatus.BLOCKED
    assert missing_one.invocation.invocation_sha256 != missing_two.invocation.invocation_sha256
    assert missing_one.invocation.requested_input_record_ids == ("missing-one",)
    assert missing_one.invocation.selected_input_record_ids == ()
    assert missing_one.provenance.selector_validation_issues[0].code == "unknown_input_record_id"

    unknown = invoke(["missing-one"])
    out_of_scope = invoke([gateway.retained_out_of_scope_record_ids[0]])
    assert unknown.invocation.invocation_sha256 != out_of_scope.invocation.invocation_sha256
    assert out_of_scope.provenance.selector_validation_issues[0].code == "out_of_scope_input_record_id"

    selected = gateway.accepted_record_ids[0]
    duplicate_two = invoke([selected, selected])
    duplicate_three = invoke([selected, selected, selected])
    assert duplicate_two.status == duplicate_three.status == AdapterExecutionStatus.BLOCKED
    assert duplicate_two.invocation.invocation_sha256 != duplicate_three.invocation.invocation_sha256
    assert duplicate_two.invocation.requested_input_record_ids == (selected, selected)
    assert duplicate_two.invocation.selected_input_record_ids == (selected,)

    first, second = gateway.accepted_record_ids[:2]
    forward = invoke([first, second])
    reverse = invoke([second, first])
    replay = invoke([first, second])
    assert forward.status == reverse.status == AdapterExecutionStatus.COMPLETED
    assert forward.invocation.selected_input_record_ids == (first, second)
    assert reverse.invocation.selected_input_record_ids == (second, first)
    assert forward.invocation.invocation_sha256 != reverse.invocation.invocation_sha256
    assert replay.invocation.invocation_sha256 == forward.invocation.invocation_sha256


def test_summary_fields_use_selected_records_only():
    gateway = _fixture_gateway()
    hashes = [item.sha256 for item in gateway.input_file_hashes]
    non_decomposed = next(item for item in gateway.vcf.records if item.variant_scope.value in {"snv", "small_indel"} and not item.decomposition_performed)
    request = AdapterInvocationRequest(invocation_id="SELECTED-ONLY", adapter_id="deterministic_supplied_result_summary", input_record_ids=[non_decomposed.record_id], parameters={}, human_review_approved=True)
    common = dict(input_manifest_sha256=gateway.input_manifest_sha256, package_identity_sha256=gateway.package_identity_sha256, input_file_hashes=hashes)
    full = invoke_registered_adapter(request, records=gateway.vcf.records, vcf=gateway.vcf, **common)
    selected_vcf = gateway.vcf.model_copy(update={
        "records": (non_decomposed,),
        "retained_out_of_scope": (),
        "record_count": 1,
        "in_scope_record_count": 1,
        "out_of_scope_record_count": 0,
        "multiallelic_source_record_count": 0,
        "decomposition_performed": False,
    })
    selected_only = invoke_registered_adapter(request, records=(non_decomposed,), vcf=selected_vcf, **common)
    assert full.output_summary == selected_only.output_summary
    assert full.output_sha256 == selected_only.output_sha256
    assert full.output_summary.decomposition_only is False

    decomposed = next(item for item in gateway.vcf.records if item.decomposition_performed)
    one_decomposed = invoke_registered_adapter(
        AdapterInvocationRequest(invocation_id="ONE-DECOMPOSED", adapter_id="deterministic_supplied_result_summary", input_record_ids=[decomposed.record_id], parameters={}, human_review_approved=True),
        records=gateway.vcf.records,
        vcf=gateway.vcf,
        **common,
    )
    mixed = invoke_registered_adapter(
        AdapterInvocationRequest(invocation_id="MIXED", adapter_id="deterministic_supplied_result_summary", input_record_ids=[non_decomposed.record_id, decomposed.record_id], parameters={}, human_review_approved=True),
        records=gateway.vcf.records,
        vcf=gateway.vcf,
        **common,
    )
    empty = invoke_registered_adapter(
        AdapterInvocationRequest(invocation_id="NONE", adapter_id="deterministic_supplied_result_summary", input_record_ids=[], parameters={}, human_review_approved=True),
        records=gateway.vcf.records,
        vcf=gateway.vcf,
        **common,
    )
    omitted = invoke_registered_adapter(
        AdapterInvocationRequest(invocation_id="ALL-SELECTED", adapter_id="deterministic_supplied_result_summary", parameters={}, human_review_approved=True),
        records=gateway.vcf.records,
        vcf=gateway.vcf,
        **common,
    )
    assert one_decomposed.output_summary.decomposition_only is True
    assert mixed.output_summary.decomposition_only is True and mixed.output_summary.record_count == 2
    assert empty.output_summary.decomposition_only is False and empty.output_summary.record_count == 0
    assert omitted.output_summary.decomposition_only is True
    assert gateway.retained_out_of_scope_record_ids[0] not in omitted.output_summary.record_ids


def test_persisted_json_round_trips_into_result_gateway_result(tmp_path):
    source_result = _fixture_gateway()
    public = source_result.model_dump(mode="json")
    decoded = json.loads(json.dumps(public))
    reloaded = ResultGatewayResult.model_validate(decoded)
    assert reloaded == source_result
    assert reloaded.model_dump(mode="json") == public
    assert reloaded.package_identity_sha256 == source_result.package_identity_sha256
    assert reloaded.input_manifest_sha256 == source_result.input_manifest_sha256
    assert [item.invocation.invocation_sha256 for item in reloaded.adapter_results] == [item.invocation.invocation_sha256 for item in source_result.adapter_results]

    decoded["input_file_hashes"]["detached.json"] = "0" * 64
    decoded["adapter_results"][0]["invocation"]["selected_input_record_ids"].append("detached")
    assert all(item.safe_relative_path != "detached.json" for item in reloaded.input_file_hashes)
    assert "detached" not in reloaded.adapter_results[0].invocation.selected_input_record_ids

    blocked_payload = _gateway_payload()
    blocked_payload["manifest"][0]["sha256"] = "0" * 64
    blocked = build_result_gateway(blocked_payload)
    blocked_public = json.loads(json.dumps(blocked.model_dump(mode="json")))
    assert ResultGatewayResult.model_validate(blocked_public).model_dump(mode="json") == blocked.model_dump(mode="json")

    response = AgentLoop(generated_root=tmp_path).run(query="round-trip persisted gateway", uploads={}, clinical_case_intake=_payload())
    artifact = Path(response["reproducibility_bundle"]["path"]) / "result_gateway.json"
    persisted = json.loads(artifact.read_text(encoding="utf-8"))
    persisted_result = ResultGatewayResult.model_validate(persisted)
    assert persisted_result.package_identity_sha256 == response["result_gateway"]["package_identity_sha256"]
    assert persisted_result.input_manifest_sha256 == response["result_gateway"]["input_manifest_sha256"]
    assert persisted_result.model_dump(mode="json") == persisted


def test_missing_output_remains_json_null_and_scope_count_mapping_reloads_immutably():
    gateway = _fixture_gateway()
    without_output = next(item for item in gateway.adapter_results if item.output_summary is None)
    dumped_execution = without_output.model_dump(mode="json")
    assert dumped_execution["output_summary"] is None
    assert type(without_output).model_validate(json.loads(json.dumps(dumped_execution))).output_summary is None

    summary = AdapterOutputSummary(record_count=1, record_ids=("record-1",), selected_record_ids=("record-1",), variant_scope_counts={"snv": 1})
    public = summary.model_dump(mode="json")
    assert public["variant_scope_counts"] == {"snv": 1}
    reloaded = AdapterOutputSummary.model_validate(json.loads(json.dumps(public)))
    assert reloaded == summary
    public["variant_scope_counts"]["snv"] = 99
    assert reloaded.variant_scope_counts == (VariantScopeCount(variant_scope="snv", count=1),)

    for invalid in ({"snv": True}, {"snv": -1}, {"snv": "1"}, {"snv": 1.0}, {"invalid_scope": 1}):
        with pytest.raises(ValidationError):
            AdapterOutputSummary(record_count=1, variant_scope_counts=invalid)
    with pytest.raises(ValidationError):
        AdapterOutputSummary(record_count=2, variant_scope_counts=[{"variant_scope": "snv", "count": 1}, {"variant_scope": "snv", "count": 1}])


def test_empty_info_is_rejected_while_dot_info_is_accepted():
    dot = parse_vcf_bytes("dot.vcf", _vcf(["1\t1\tDOT\tA\tG\t.\tPASS\t."]))
    assert dot.record_count == 1 and dot.records[0].supplied_annotations == ()
    assert not [item for item in dot.issues if item.severity.value == "error"]

    for name, record, expected_code in (
        ("empty", "1\t1\tEMPTY\tA\tG\t.\tPASS\t", "vcf_info_field_empty"),
        ("whitespace", "1\t1\tSPACE\tA\tG\t.\tPASS\t   ", "vcf_info_field_empty"),
        ("missing-column", "1\t1\tSHORT\tA\tG\t.\tPASS", "vcf_record_column_count_mismatch"),
    ):
        parsed = parse_vcf_bytes(f"{name}.vcf", _vcf([record]))
        assert parsed.records == ()
        issue = next(item for item in parsed.issues if item.code == expected_code)
        assert issue.path == f"{name}.vcf" and issue.message.startswith("Line 4:")
        if expected_code == "vcf_info_field_empty":
            assert issue.record_id

    flag = parse_vcf_bytes("flag.vcf", _vcf(["1\t1\tFLAG\tA\tG\t.\tPASS\tSOMATIC"], extra_headers=('##INFO=<ID=SOMATIC,Number=0,Type=Flag,Description="Supplied flag">',)))
    assert flag.record_count == 1 and flag.records[0].supplied_annotations[0].is_flag is True

    package = _gateway_payload()
    _replace_role_bytes(package, "vcf", _vcf(["1\t1\tEMPTY\tA\tG\t.\tPASS\t"]))
    blocked = build_result_gateway(package)
    assert blocked.package_status == GatewayPackageStatus.BLOCKED
    assert blocked.adapter_results == ()
    assert "vcf_info_field_empty" in {item.code for item in blocked.errors}
