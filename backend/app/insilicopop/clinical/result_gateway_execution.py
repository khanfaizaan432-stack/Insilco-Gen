from __future__ import annotations

import re
from typing import Iterable, Sequence

from app.insilicopop.clinical.result_gateway_models import (
    AdapterAvailability,
    AdapterDefinition,
    AdapterExecutionResult,
    AdapterExecutionStatus,
    AdapterInvocationRequest,
    AdapterOutputSummary,
    AdapterParameters,
    LeftNormalizationParameters,
    NetworkPolicy,
    NormalizedAdapterInvocation,
    SelectorValidationIssue,
    SummaryAdapterParameters,
    ToolProvenance,
    VCFParseResult,
    VCFVariantRecord,
    VariantScope,
    VariantScopeCount,
    VepReconciliationParameters,
)
from app.insilicopop.clinical.result_gateway_validation import (
    canonical_json_bytes,
    canonical_payload_sha256,
    sha256_bytes,
)


_BUILTIN_DIGEST = sha256_bytes(b"insilicopop-v0.36-builtin-deterministic-summary")
_UNAVAILABLE_DIGEST = sha256_bytes(b"insilicopop-v0.36-unavailable-adapter-placeholder")


_REGISTRY: tuple[AdapterDefinition, ...] = (
    AdapterDefinition(
        adapter_id="deterministic_supplied_result_summary",
        version="0.36.0",
        parameter_schema_id="insilicopop.summary.parameters",
        parameter_schema_version="1.0",
        input_contract="eligible supplied VCF records plus supplied QC/coverage/assay summaries",
        output_contract="bounded deterministic result summary",
        executable_identity="builtin://insilicopop/result-summary/v0.36",
        executable_digest=_BUILTIN_DIGEST,
        parser_version="insilicopop-result-package-parser-0.36.0",
        reference_version="declared-by-package",
        default_parameters=SummaryAdapterParameters(),
        network_policy=NetworkPolicy.DISABLED,
        availability=AdapterAvailability.AVAILABLE,
        synthetic_fixture=True,
    ),
    AdapterDefinition(
        adapter_id="bcftools_left_normalization",
        version="0.36.0",
        parameter_schema_id="insilicopop.bcftools-left-normalization.parameters",
        parameter_schema_version="1.0",
        input_contract="supplied VCF plus pinned reference sequence",
        output_contract="normalized VCF",
        executable_identity="external://bcftools",
        executable_digest=_UNAVAILABLE_DIGEST,
        parser_version="insilicopop-result-package-parser-0.36.0",
        reference_version="not_pinned",
        default_parameters=LeftNormalizationParameters(),
        network_policy=NetworkPolicy.DISABLED,
        availability=AdapterAvailability.UNAVAILABLE,
        synthetic_fixture=False,
        unavailable_reason="No approved local bcftools executable and reference database are registered; installation or download is prohibited.",
    ),
    AdapterDefinition(
        adapter_id="vep_supplied_annotation_reconciliation",
        version="0.36.0",
        parameter_schema_id="insilicopop.vep-reconciliation.parameters",
        parameter_schema_version="1.0",
        input_contract="supplied variant records plus pinned local annotation database",
        output_contract="provenance-linked supplied annotation reconciliation",
        executable_identity="external://vep",
        executable_digest=_UNAVAILABLE_DIGEST,
        parser_version="insilicopop-result-package-parser-0.36.0",
        transcript_version="not_pinned",
        database_versions=(),
        default_parameters=VepReconciliationParameters(),
        network_policy=NetworkPolicy.DISABLED,
        availability=AdapterAvailability.UNAVAILABLE,
        synthetic_fixture=False,
        unavailable_reason="No approved local VEP executable and database are registered; browsing, retrieval, installation, and download are prohibited.",
    ),
)


def registered_adapters() -> tuple[AdapterDefinition, ...]:
    return _REGISTRY


def get_registered_adapter(adapter_id: str) -> AdapterDefinition | None:
    return next((item for item in _REGISTRY if item.adapter_id == adapter_id), None)


def adapter_invocation_identity_payload(
    request: AdapterInvocationRequest,
    adapter: AdapterDefinition,
    *,
    package_identity_sha256: str,
    input_manifest_sha256: str,
    input_file_hashes: tuple[str, ...],
    requested_input_record_ids: tuple[str, ...] | None,
    selected_input_record_ids: tuple[str, ...],
    selector_validation_issues: tuple[SelectorValidationIssue, ...] = (),
) -> dict[str, object]:
    """Return the complete canonical payload used for v0.36 invocation identity."""

    return {
        "identity_schema": "insilicopop.adapter-invocation-identity.v0.36.1",
        "package_identity_sha256": package_identity_sha256,
        "input_manifest_sha256": input_manifest_sha256,
        "invocation_id": request.invocation_id,
        "adapter_id": adapter.adapter_id,
        "adapter_version": adapter.version,
        "parameter_schema_id": adapter.parameter_schema_id,
        "parameter_schema_version": adapter.parameter_schema_version,
        "parameters": request.parameters.model_dump(mode="json"),
        "input_file_hashes": input_file_hashes,
        "requested_input_record_ids": requested_input_record_ids,
        "selected_input_record_ids": selected_input_record_ids,
        "selector_validation_issues": tuple(
            item.model_dump(mode="json") for item in selector_validation_issues
        ),
        "selector_mode": "all_eligible" if requested_input_record_ids is None else "explicit",
        "timeout_seconds": min(request.timeout_seconds, adapter.timeout_seconds),
        "max_records": request.max_records,
        "max_output_bytes": min(request.max_output_bytes, adapter.max_output_bytes),
        "network_policy": NetworkPolicy.DISABLED.value,
        "working_directory_policy": request.working_directory_policy,
        "human_review_approved": request.human_review_approved,
        "replay_key": request.replay_key,
    }


def invoke_registered_adapter(
    request: AdapterInvocationRequest,
    *,
    input_manifest_sha256: str,
    input_file_hashes: Iterable[str],
    package_identity_sha256: str,
    records: Sequence[VCFVariantRecord] | None = None,
    vcf: VCFParseResult | None = None,
) -> AdapterExecutionResult:
    """Run only the in-process allowlisted summary; no subprocess or network path exists."""

    actual_hashes = tuple(sorted({value.lower() for value in input_file_hashes if re.fullmatch(r"[a-fA-F0-9]{64}", value)}))
    identity_hash = package_identity_sha256
    all_rows = tuple(records if records is not None else (vcf.records if vcf else ()))
    rows_by_id = {item.record_id: item for item in all_rows}
    eligible_rows = tuple(item for item in all_rows if item.variant_scope in {VariantScope.SNV, VariantScope.SMALL_INDEL})
    eligible_ids = {item.record_id for item in eligible_rows}
    selector_mode = "all_eligible" if request.input_record_ids is None else "explicit"
    requested_input_record_ids = request.input_record_ids
    effective_ids = (
        tuple(item.record_id for item in eligible_rows)
        if requested_input_record_ids is None
        else requested_input_record_ids
    )
    selected_rows_list: list[VCFVariantRecord] = []
    selector_issues: list[SelectorValidationIssue] = []
    seen_requested: set[str] = set()
    seen_selected: set[str] = set()
    for record_id in effective_ids:
        if record_id in seen_requested:
            selector_issues.append(SelectorValidationIssue(
                code="duplicate_input_record_id",
                record_id=record_id,
                message="The requested input record ID occurs more than once.",
            ))
            continue
        seen_requested.add(record_id)
        if record_id not in rows_by_id:
            selector_issues.append(SelectorValidationIssue(
                code="unknown_input_record_id",
                record_id=record_id,
                message="The requested input record ID is unknown.",
            ))
            continue
        if record_id not in eligible_ids:
            selector_issues.append(SelectorValidationIssue(
                code="out_of_scope_input_record_id",
                record_id=record_id,
                message="The requested input record ID is retained out of scope.",
            ))
            continue
        if record_id not in seen_selected:
            selected_rows_list.append(rows_by_id[record_id])
            seen_selected.add(record_id)
    selected_rows = tuple(selected_rows_list)
    selected_ids = tuple(item.record_id for item in selected_rows)

    adapter = get_registered_adapter(request.adapter_id)
    if adapter is None:
        raise ValueError("Adapter request passed schema validation without a registered adapter")
    if selector_issues:
        selector_errors_list: list[str] = []
        selector_error_messages = {
            "duplicate_input_record_id": "Duplicate input_record_ids were rejected",
            "unknown_input_record_id": "Unknown input_record_ids were rejected",
            "out_of_scope_input_record_id": "Out-of-scope input_record_ids are not eligible for this adapter",
        }
        for code, message in selector_error_messages.items():
            ids = tuple(item.record_id for item in selector_issues if item.code == code)
            if ids:
                selector_errors_list.append(f"{message}: {', '.join(ids)}.")
        selector_errors = tuple(selector_errors_list)
        return _result(request, adapter, AdapterExecutionStatus.BLOCKED, input_manifest_sha256=input_manifest_sha256, package_identity_sha256=identity_hash, input_file_hashes=actual_hashes, selected_record_ids=selected_ids, selector_mode=selector_mode, selector_validation_issues=tuple(selector_issues), errors=selector_errors)
    if request.input_file_hashes and tuple(sorted(value.lower() for value in request.input_file_hashes)) != actual_hashes:
        return _result(request, adapter, AdapterExecutionStatus.BLOCKED, input_manifest_sha256=input_manifest_sha256, package_identity_sha256=identity_hash, input_file_hashes=actual_hashes, selected_record_ids=selected_ids, selector_mode=selector_mode, errors=("Requested input_file_hashes do not match the structurally verified package files.",))
    if request.adapter_version and request.adapter_version != adapter.version:
        return _result(request, adapter, AdapterExecutionStatus.BLOCKED, input_manifest_sha256=input_manifest_sha256, package_identity_sha256=identity_hash, input_file_hashes=actual_hashes, selected_record_ids=selected_ids, selector_mode=selector_mode, errors=("Requested adapter version does not match the registered immutable version.",))
    if request.parameters.parameter_schema_id != adapter.parameter_schema_id or request.parameters.parameter_schema_version != adapter.parameter_schema_version:
        return _result(request, adapter, AdapterExecutionStatus.BLOCKED, input_manifest_sha256=input_manifest_sha256, package_identity_sha256=identity_hash, input_file_hashes=actual_hashes, selected_record_ids=selected_ids, selector_mode=selector_mode, errors=("Requested parameter schema does not match the registered immutable adapter schema.",))
    if adapter.availability == AdapterAvailability.UNAVAILABLE:
        return _result(request, adapter, AdapterExecutionStatus.UNAVAILABLE, input_manifest_sha256=input_manifest_sha256, package_identity_sha256=identity_hash, input_file_hashes=actual_hashes, selected_record_ids=selected_ids, selector_mode=selector_mode, errors=(adapter.unavailable_reason or "Registered adapter is unavailable.",))
    if not request.human_review_approved:
        return _result(request, adapter, AdapterExecutionStatus.BLOCKED, input_manifest_sha256=input_manifest_sha256, package_identity_sha256=identity_hash, input_file_hashes=actual_hashes, selected_record_ids=selected_ids, selector_mode=selector_mode, errors=("Human-review approval is required before adapter execution.",))
    if request.network_policy != NetworkPolicy.DISABLED or adapter.network_policy != NetworkPolicy.DISABLED:
        return _result(request, adapter, AdapterExecutionStatus.BLOCKED, input_manifest_sha256=input_manifest_sha256, package_identity_sha256=identity_hash, input_file_hashes=actual_hashes, selected_record_ids=selected_ids, selector_mode=selector_mode, errors=("Network access is disabled by the v0.36 execution policy.",))
    if request.max_output_bytes > adapter.max_output_bytes:
        return _result(request, adapter, AdapterExecutionStatus.BLOCKED, input_manifest_sha256=input_manifest_sha256, package_identity_sha256=identity_hash, input_file_hashes=actual_hashes, selected_record_ids=selected_ids, selector_mode=selector_mode, errors=("Requested output budget exceeds the registered adapter output limit.",))
    if len(selected_rows) > request.max_records:
        return _result(request, adapter, AdapterExecutionStatus.FAILED, input_manifest_sha256=input_manifest_sha256, package_identity_sha256=identity_hash, input_file_hashes=actual_hashes, selected_record_ids=selected_ids, selector_mode=selector_mode, errors=("Adapter input record count exceeds the requested record budget.",))

    scope_counts: dict[VariantScope, int] = {}
    for record in selected_rows:
        scope_counts[record.variant_scope] = scope_counts.get(record.variant_scope, 0) + 1
    output_summary = AdapterOutputSummary(
        record_count=len(selected_rows),
        record_ids=selected_ids,
        selected_record_ids=selected_ids,
        variant_scope_counts=tuple(VariantScopeCount(variant_scope=key, count=value) for key, value in sorted(scope_counts.items(), key=lambda item: item[0].value)),
        decomposition_only=any(record.decomposition_performed for record in selected_rows),
        partial_output=False,
    )
    output_bytes = canonical_json_bytes(output_summary.model_dump(mode="json"))
    if len(output_bytes) > request.max_output_bytes:
        return _result(request, adapter, AdapterExecutionStatus.FAILED, input_manifest_sha256=input_manifest_sha256, package_identity_sha256=identity_hash, input_file_hashes=actual_hashes, selected_record_ids=selected_ids, selector_mode=selector_mode, errors=("Adapter output exceeded the requested output-byte budget.",))
    return _result(
        request,
        adapter,
        AdapterExecutionStatus.COMPLETED,
        input_manifest_sha256=input_manifest_sha256,
        package_identity_sha256=identity_hash,
        input_file_hashes=actual_hashes,
        selected_record_ids=selected_ids,
        selector_mode=selector_mode,
        output_summary=output_summary,
        output_bytes=output_bytes,
    )


def _result(
    request: AdapterInvocationRequest,
    adapter: AdapterDefinition,
    status: AdapterExecutionStatus,
    *,
    input_manifest_sha256: str,
    package_identity_sha256: str,
    input_file_hashes: tuple[str, ...],
    selected_record_ids: tuple[str, ...],
    selector_mode: str,
    output_summary: AdapterOutputSummary | None = None,
    output_bytes: bytes | None = None,
    errors: tuple[str, ...] = (),
    selector_validation_issues: tuple[SelectorValidationIssue, ...] = (),
) -> AdapterExecutionResult:
    parameters: AdapterParameters = request.parameters
    requested_input_record_ids = request.input_record_ids
    invocation_payload = adapter_invocation_identity_payload(
        request,
        adapter,
        package_identity_sha256=package_identity_sha256,
        input_manifest_sha256=input_manifest_sha256,
        input_file_hashes=input_file_hashes,
        requested_input_record_ids=requested_input_record_ids,
        selected_input_record_ids=selected_record_ids,
        selector_validation_issues=selector_validation_issues,
    )
    invocation_sha256 = canonical_payload_sha256(invocation_payload)
    invocation = NormalizedAdapterInvocation(
        invocation_id=request.invocation_id,
        adapter_id=adapter.adapter_id,
        adapter_version=adapter.version,
        parameter_schema_id=adapter.parameter_schema_id,
        parameter_schema_version=adapter.parameter_schema_version,
        parameters=parameters,
        package_identity_sha256=package_identity_sha256,
        input_manifest_sha256=input_manifest_sha256,
        input_file_hashes=input_file_hashes,
        requested_input_record_ids=requested_input_record_ids,
        selected_input_record_ids=selected_record_ids,
        input_record_ids=selected_record_ids,
        selector_validation_issues=selector_validation_issues,
        selector_mode=selector_mode,
        timeout_seconds=min(request.timeout_seconds, adapter.timeout_seconds),
        max_records=request.max_records,
        max_output_bytes=min(request.max_output_bytes, adapter.max_output_bytes),
        network_policy=NetworkPolicy.DISABLED,
        working_directory_policy=request.working_directory_policy,
        human_review_approved=request.human_review_approved,
        invocation_sha256=invocation_sha256,
        replay_key=request.replay_key,
    )
    output_hash = sha256_bytes(output_bytes) if output_bytes is not None else None
    provenance = ToolProvenance(
        adapter_id=adapter.adapter_id,
        adapter_version=adapter.version,
        parameter_schema_id=adapter.parameter_schema_id,
        parameter_schema_version=adapter.parameter_schema_version,
        executable_identity=adapter.executable_identity,
        executable_digest=adapter.executable_digest,
        container_identity=adapter.container_identity,
        container_digest=adapter.container_digest,
        parser_version=adapter.parser_version,
        reference_version=adapter.reference_version,
        transcript_version=adapter.transcript_version,
        database_versions=adapter.database_versions,
        normalized_parameters=parameters,
        input_manifest_sha256=input_manifest_sha256,
        package_identity_sha256=package_identity_sha256,
        input_file_hashes=input_file_hashes,
        requested_input_record_ids=requested_input_record_ids,
        selected_input_record_ids=selected_record_ids,
        selected_record_ids=selected_record_ids,
        selector_validation_issues=selector_validation_issues,
        invocation_sha256=invocation_sha256,
        output_sha256=output_hash,
    )
    status_message = {
        AdapterExecutionStatus.COMPLETED: "Deterministic built-in adapter completed.",
        AdapterExecutionStatus.UNAVAILABLE: "Registered adapter is unavailable.",
        AdapterExecutionStatus.REJECTED: "Adapter execution was rejected by the allowlist.",
        AdapterExecutionStatus.BLOCKED: "Adapter execution was blocked by policy or validation.",
        AdapterExecutionStatus.FAILED: "Adapter execution failed bounded validation.",
        AdapterExecutionStatus.TIMED_OUT: "Adapter execution timed out within its bounded policy.",
        AdapterExecutionStatus.PARTIAL: "Adapter produced a partial bounded result.",
    }[status]
    return AdapterExecutionResult(
        invocation=invocation,
        adapter=adapter,
        status=status,
        output_summary=output_summary,
        output_sha256=output_hash,
        output_byte_size=len(output_bytes or b""),
        stdout_excerpt=status_message if status in {AdapterExecutionStatus.COMPLETED, AdapterExecutionStatus.PARTIAL} else "",
        stderr_excerpt="; ".join(errors)[:4000],
        errors=errors,
        provenance=provenance,
    )
