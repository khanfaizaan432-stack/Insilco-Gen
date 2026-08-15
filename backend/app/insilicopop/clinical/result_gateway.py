from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import PurePosixPath
from typing import Any

from pydantic import ValidationError

from app.insilicopop.clinical.result_gateway_execution import (
    invoke_registered_adapter,
    registered_adapters,
)
from app.insilicopop.clinical.result_gateway_models import (
    AdapterExecutionStatus,
    AdapterInvocationRequest,
    CANONICAL_RESULT_LOGICAL_ROLES,
    FileHashEntry,
    GatewayIssue,
    GatewayIssueSeverity,
    GatewayPackageStatus,
    ReplayStatus,
    ResultGatewayRequest,
    ResultGatewayResult,
    ResultManifestEntry,
    ResultLogicalRole,
    SuppliedResultFile,
    VariantScope,
)
from app.insilicopop.clinical.result_gateway_parser import (
    ParsedFile,
    parse_structured_result_file,
    parse_vcf_bytes,
)
from app.insilicopop.clinical.result_gateway_validation import (
    canonical_payload_sha256,
    manifest_digest,
    package_identity_digest,
    safe_path_collision_key,
    sha256_bytes,
    supplied_file_bytes,
    validate_safe_relative_path,
)


_REQUIRED_ROLES = CANONICAL_RESULT_LOGICAL_ROLES
_ROLE_MEDIA_TYPES: dict[str, frozenset[str]] = {
    "vcf": frozenset({"text/variant-call-format", "text/vcf", "application/vcf"}),
    "structured_laboratory_report": frozenset({"application/json"}),
    "qc": frozenset({"application/json"}),
    "coverage": frozenset({"application/json"}),
    "assay_metadata": frozenset({"application/json"}),
}


def build_result_gateway(
    request: ResultGatewayRequest | dict[str, Any],
    *,
    pseudonymous_case_id: str | None = None,
) -> ResultGatewayResult:
    """Validate the complete package before invoking any parser or adapter."""

    if not isinstance(request, ResultGatewayRequest):
        request = ResultGatewayRequest.model_validate(request)

    structural_errors: list[GatewayIssue] = []
    warnings: list[GatewayIssue] = []
    _validate_exact_logical_roles(request, structural_errors)
    manifest_records = _validated_manifest_records(request, structural_errors)
    supplied_records, actual_hashes, actual_sizes = _validated_supplied_records(request, structural_errors)
    _validate_roles_and_paths(manifest_records, supplied_records, structural_errors)
    _validate_exact_bytes(manifest_records, supplied_records, actual_hashes, actual_sizes, structural_errors)
    _validate_media_and_content(manifest_records, supplied_records, structural_errors)

    input_manifest_sha256 = _manifest_digest_or_invalid(request.manifest)
    if request.expected_input_manifest_sha256 and request.expected_input_manifest_sha256.lower() != input_manifest_sha256:
        structural_errors.append(_issue("expected_manifest_digest_mismatch", "The supplied package does not match the expected deterministic manifest digest."))

    package_identity_sha256 = _package_identity_or_invalid(
        request,
        actual_hashes=actual_hashes,
        actual_sizes=actual_sizes,
    )
    if request.expected_package_identity_sha256 and request.expected_package_identity_sha256.lower() != package_identity_sha256:
        structural_errors.append(_issue("expected_package_identity_mismatch", "The supplied package does not match the expected complete package identity."))

    replay_status, stale_message, replay_error, replay_warning = _evaluate_replay(request, package_identity_sha256)
    if replay_error:
        structural_errors.append(replay_error)
    if replay_warning:
        warnings.append(replay_warning)

    if structural_errors:
        status = GatewayPackageStatus.STALE if replay_status == ReplayStatus.STALE else GatewayPackageStatus.BLOCKED
        return _result(
            request,
            pseudonymous_case_id=pseudonymous_case_id,
            package_status=status,
            replay_status=replay_status,
            input_manifest_sha256=input_manifest_sha256,
            package_identity_sha256=package_identity_sha256,
            actual_hashes=actual_hashes,
            canonical_hashes={},
            manifest_verified=False,
            errors=structural_errors,
            warnings=warnings,
            stale_message=stale_message,
        )

    manifest_by_path = {path: entry for path, entry in manifest_records}
    supplied_by_path = {path: (item, data) for path, item, data in supplied_records}
    parsed_by_role: dict[str, ParsedFile] = {}
    canonical_hashes: dict[str, str] = {}
    parse_errors: list[GatewayIssue] = []
    for role in _REQUIRED_ROLES:
        path = next(path for path, entry in manifest_records if entry.logical_role == role)
        entry = manifest_by_path[path]
        item, data = supplied_by_path[path]
        if role == "vcf":
            vcf = parse_vcf_bytes(
                path,
                data,
                declared_reference_build=request.declared_reference_build,
                expected_sample_id=request.expected_sample_id,
                max_records=min(request.limits.max_records, 1_000_000),
            )
            parsed = ParsedFile(
                vcf=vcf,
                issues=list(vcf.issues),
                canonical_payload=vcf.model_dump(mode="json"),
                record_count=vcf.record_count,
            )
        else:
            parsed = parse_structured_result_file(
                path,
                role,
                data,
                max_records=min(request.limits.max_records, 1_000_000),
            )
        parsed_by_role[role] = parsed
        canonical_hash = canonical_payload_sha256(parsed.canonical_payload) if parsed.canonical_payload is not None else sha256_bytes(data.replace(b"\r\n", b"\n"))
        canonical_hashes[path] = canonical_hash
        if entry.canonical_hash and entry.canonical_hash.lower() != canonical_hash.lower():
            parse_errors.append(_issue("manifest_canonical_hash_mismatch", "Canonical parsed representation does not match the manifest canonical hash.", path=path))
        parse_errors.extend(issue for issue in parsed.issues if issue.severity == GatewayIssueSeverity.ERROR)
        warnings.extend(issue for issue in parsed.issues if issue.severity != GatewayIssueSeverity.ERROR)

    vcf = parsed_by_role["vcf"].vcf
    lab = parsed_by_role[ResultLogicalRole.STRUCTURED_LABORATORY_REPORT.value].laboratory_report
    qc = parsed_by_role["qc"].qc
    coverage = parsed_by_role["coverage"].coverage
    assay = parsed_by_role["assay_metadata"].assay_scope
    reference_build_mismatch_blocked = bool(
        vcf and vcf.header and vcf.header.build_validation == "mismatch"
    ) or any(issue.code in {"reference_build_mismatch", "conflicting_reference_declarations"} for issue in parse_errors)

    invocations = list(request.adapter_invocations)
    if request.tool_analysis_intent and request.tool_analysis_intent.adapter_id:
        intent = request.tool_analysis_intent
        if not any(item.adapter_id == intent.adapter_id for item in invocations):
            try:
                invocations.append(
                    AdapterInvocationRequest(
                        invocation_id=f"intent-{intent.intent_id}",
                        adapter_id=intent.adapter_id,
                        input_record_ids=intent.target_record_ids,
                        parameters=intent.parameters,
                        timeout_seconds=intent.timeout_seconds,
                        max_records=intent.max_records,
                        max_output_bytes=intent.max_output_bytes,
                        network_policy=intent.network_policy,
                        human_review_approved=intent.human_review_approved,
                    )
                )
            except (ValidationError, ValueError) as exc:
                parse_errors.append(_issue("adapter_invocation_policy_blocked", f"The typed adapter intent was rejected: {type(exc).__name__}."))

    adapter_results = []
    if not parse_errors:
        for invocation in sorted(invocations, key=lambda item: item.invocation_id):
            adapter_results.append(
                invoke_registered_adapter(
                    invocation,
                    input_manifest_sha256=input_manifest_sha256,
                    package_identity_sha256=package_identity_sha256,
                    input_file_hashes=actual_hashes.values(),
                    records=vcf.records if vcf else (),
                    vcf=vcf,
                )
            )

    if replay_status == ReplayStatus.DUPLICATE:
        package_status = GatewayPackageStatus.DUPLICATE
    elif parse_errors:
        package_status = GatewayPackageStatus.BLOCKED
    elif any(item.status in {AdapterExecutionStatus.PARTIAL, AdapterExecutionStatus.FAILED, AdapterExecutionStatus.TIMED_OUT, AdapterExecutionStatus.BLOCKED, AdapterExecutionStatus.REJECTED} for item in adapter_results):
        package_status = GatewayPackageStatus.PARTIAL
    elif any(item.status == AdapterExecutionStatus.UNAVAILABLE for item in adapter_results) or warnings:
        package_status = GatewayPackageStatus.COMPLETED_WITH_WARNINGS
    else:
        package_status = GatewayPackageStatus.COMPLETED

    accepted_ids = tuple(sorted(
        item.record_id for item in (vcf.records if vcf else ())
        if item.variant_scope in {VariantScope.SNV, VariantScope.SMALL_INDEL}
    ))
    retained_ids = tuple(sorted(item.record_id for item in (vcf.retained_out_of_scope if vcf else ())))
    return _result(
        request,
        pseudonymous_case_id=pseudonymous_case_id,
        package_status=package_status,
        replay_status=replay_status,
        input_manifest_sha256=input_manifest_sha256,
        package_identity_sha256=package_identity_sha256,
        actual_hashes=actual_hashes,
        canonical_hashes=canonical_hashes,
        manifest_verified=not parse_errors,
        errors=parse_errors,
        warnings=warnings,
        stale_message=stale_message,
        vcf=vcf,
        lab=lab,
        qc=qc,
        coverage=coverage,
        assay=assay,
        adapter_results=tuple(adapter_results),
        accepted_ids=accepted_ids,
        retained_ids=retained_ids,
        reference_build_mismatch_blocked=reference_build_mismatch_blocked,
    )


def _validated_manifest_records(
    request: ResultGatewayRequest,
    errors: list[GatewayIssue],
) -> list[tuple[str, ResultManifestEntry]]:
    if not request.manifest:
        errors.append(_issue("manifest_required", "A deterministic manifest is required before any supplied result bytes are accepted."))
    if len(request.manifest) > request.limits.max_files:
        errors.append(_issue("file_count_budget_exceeded", f"The manifest contains more than the configured file limit of {request.limits.max_files}."))
    records: list[tuple[str, ResultManifestEntry]] = []
    collisions: dict[str, list[str]] = defaultdict(list)
    for entry in request.manifest:
        try:
            path = validate_safe_relative_path(entry.safe_relative_path)
            records.append((path, entry))
            collisions[safe_path_collision_key(path)].append(entry.safe_relative_path)
        except ValueError as exc:
            errors.append(_issue("unsafe_manifest_path", str(exc), path=entry.safe_relative_path))
    for values in collisions.values():
        if len(values) > 1:
            errors.append(_issue("manifest_path_collision", f"Manifest paths collide after NFC normalization and case-folding: {', '.join(sorted(values))}."))
    return records


def _validate_exact_logical_roles(
    request: ResultGatewayRequest,
    errors: list[GatewayIssue],
) -> None:
    canonical_roles = set(CANONICAL_RESULT_LOGICAL_ROLES)
    for label, entries in (("manifest", request.manifest), ("supplied file", request.files)):
        for entry in entries:
            if entry.logical_role not in canonical_roles:
                errors.append(_issue(
                    "unknown_logical_role",
                    f"{label.capitalize()} declares noncanonical logical role {entry.logical_role!r}; exact canonical serialized values are required.",
                    path=entry.safe_relative_path,
                ))


def _validated_supplied_records(
    request: ResultGatewayRequest,
    errors: list[GatewayIssue],
) -> tuple[list[tuple[str, SuppliedResultFile, bytes]], dict[str, str], dict[str, int]]:
    if len(request.files) > request.limits.max_files:
        errors.append(_issue("file_count_budget_exceeded", f"The package contains more than the configured file limit of {request.limits.max_files}."))
    records: list[tuple[str, SuppliedResultFile, bytes]] = []
    collisions: dict[str, list[str]] = defaultdict(list)
    hashes: dict[str, str] = {}
    sizes: dict[str, int] = {}
    total_bytes = 0
    total_reported = False
    for item in request.files:
        try:
            path = validate_safe_relative_path(item.safe_relative_path)
            collisions[safe_path_collision_key(path)].append(item.safe_relative_path)
        except ValueError as exc:
            errors.append(_issue("unsafe_supplied_path", str(exc), path=item.safe_relative_path))
            continue
        if item.is_symlink:
            errors.append(_issue("symlink_input_rejected", "Symlink entries are rejected; only persisted bytes at safe relative paths are accepted.", path=path))
            continue
        try:
            data = supplied_file_bytes(item)
        except ValueError as exc:
            errors.append(_issue("supplied_bytes_invalid", str(exc), path=path))
            continue
        if len(data) > request.limits.max_file_bytes:
            errors.append(_issue("file_byte_budget_exceeded", f"File exceeds the configured byte limit of {request.limits.max_file_bytes}.", path=path))
        total_bytes += len(data)
        if total_bytes > request.limits.max_total_bytes and not total_reported:
            errors.append(_issue("total_byte_budget_exceeded", f"Package exceeds the configured total byte limit of {request.limits.max_total_bytes}."))
            total_reported = True
        records.append((path, item, data))
        if path not in hashes:
            hashes[path] = sha256_bytes(data)
            sizes[path] = len(data)
    for values in collisions.values():
        if len(values) > 1:
            errors.append(_issue("supplied_path_collision", f"Supplied file paths collide after NFC normalization and case-folding: {', '.join(sorted(values))}."))
    return records, hashes, sizes


def _validate_roles_and_paths(
    manifest_records: list[tuple[str, ResultManifestEntry]],
    supplied_records: list[tuple[str, SuppliedResultFile, bytes]],
    errors: list[GatewayIssue],
) -> None:
    canonical_roles = set(_REQUIRED_ROLES)
    manifest_roles = Counter(entry.logical_role for _, entry in manifest_records if entry.logical_role in canonical_roles)
    supplied_roles = Counter(item.logical_role for _, item, _ in supplied_records if item.logical_role in canonical_roles)
    for label, roles in (("manifest", manifest_roles), ("supplied", supplied_roles)):
        for role in _REQUIRED_ROLES:
            count = roles.get(role, 0)
            if count == 0:
                errors.append(_issue("required_logical_role_missing", f"{label.capitalize()} is missing required logical role {role}."))
            elif count > 1:
                errors.append(_issue("duplicate_logical_role", f"{label.capitalize()} contains {count} entries for required logical role {role}; exactly one is required."))

    manifest_paths = [path for path, _ in manifest_records]
    supplied_paths = [path for path, _, _ in supplied_records]
    if Counter(manifest_paths) != Counter(supplied_paths):
        errors.append(_issue("manifest_file_set_mismatch", "Manifest paths and supplied byte paths must match exactly, including multiplicity."))
    manifest_by_path = _unique_mapping(manifest_records)
    supplied_by_path = _unique_mapping((path, item) for path, item, _ in supplied_records)
    for path in sorted(set(manifest_by_path) & set(supplied_by_path)):
        if manifest_by_path[path].logical_role != supplied_by_path[path].logical_role:
            errors.append(_issue("manifest_logical_role_mismatch", "Supplied file logical role differs from its manifest entry.", path=path))


def _validate_exact_bytes(
    manifest_records: list[tuple[str, ResultManifestEntry]],
    supplied_records: list[tuple[str, SuppliedResultFile, bytes]],
    hashes: dict[str, str],
    sizes: dict[str, int],
    errors: list[GatewayIssue],
) -> None:
    manifest_by_path = _unique_mapping(manifest_records)
    supplied_by_path = _unique_mapping((path, item) for path, item, _ in supplied_records)
    for path in sorted(set(manifest_by_path) & set(supplied_by_path)):
        entry = manifest_by_path[path]
        if hashes.get(path, "").lower() != entry.sha256.lower():
            errors.append(_issue("manifest_hash_mismatch", "Persisted input bytes do not match the manifest SHA-256.", path=path))
        if sizes.get(path) != entry.byte_size:
            errors.append(_issue("manifest_byte_size_mismatch", "Persisted input byte size does not match the manifest.", path=path))


def _validate_media_and_content(
    manifest_records: list[tuple[str, ResultManifestEntry]],
    supplied_records: list[tuple[str, SuppliedResultFile, bytes]],
    errors: list[GatewayIssue],
) -> None:
    manifest_by_path = _unique_mapping(manifest_records)
    supplied_by_path = _unique_mapping((path, (item, data)) for path, item, data in supplied_records)
    existing_exact_errors = {(item.code, item.path) for item in errors}
    for path in sorted(set(manifest_by_path) & set(supplied_by_path)):
        entry = manifest_by_path[path]
        item, data = supplied_by_path[path]
        role = entry.logical_role
        if role not in _ROLE_MEDIA_TYPES:
            continue
        manifest_media = entry.media_type.lower()
        supplied_media = item.media_type.lower()
        if manifest_media != supplied_media:
            errors.append(_issue("manifest_media_type_mismatch", "Supplied file media type differs from its manifest entry.", path=path))
        if manifest_media not in _ROLE_MEDIA_TYPES[role] or supplied_media not in _ROLE_MEDIA_TYPES[role]:
            errors.append(_issue("role_media_type_not_allowed", f"Media type is not allowlisted for logical role {role}.", path=path))
        suffix = PurePosixPath(path).suffix.casefold()
        expected_suffix = ".vcf" if role == "vcf" else ".json"
        if suffix != expected_suffix:
            errors.append(_issue("role_extension_mismatch", f"Logical role {role} requires a {expected_suffix} path.", path=path))
        if ("manifest_hash_mismatch", path) in existing_exact_errors or ("manifest_byte_size_mismatch", path) in existing_exact_errors:
            continue
        content_error = _content_consistency_error(role, data)
        if content_error:
            errors.append(_issue("role_content_mismatch", content_error, path=path))


def _content_consistency_error(role: str, data: bytes) -> str | None:
    if role == "vcf":
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return "VCF role bytes are not UTF-8 text."
        lines = text.splitlines()
        if not lines or not lines[0].startswith("##fileformat=VCFv") or not any(line.startswith("#CHROM\t") for line in lines):
            return "VCF role bytes do not contain the required VCF fileformat and column headers."
        return None
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return f"{role} role bytes are not a UTF-8 JSON object."
    if not isinstance(payload, dict):
        return f"{role} role bytes are not a JSON object."
    markers = {
        "structured_laboratory_report": {"report_id", "laboratory_name", "findings", "accreditation_status", "assay_or_test_type"},
        "qc": {"metrics", "warnings"},
        "coverage": {"poor_regions", "minimum_coverage", "mean_coverage", "regions"},
        "assay_metadata": {"reportable_genes", "reportable_transcripts", "reportable_regions", "blind_spots", "cnv_scope", "mitochondrial_scope", "repeat_scope", "mosaic_scope"},
    }[role]
    if not markers.intersection(payload):
        return f"JSON content does not contain any allowlisted structural marker for logical role {role}."
    return None


def _evaluate_replay(
    request: ResultGatewayRequest,
    package_identity_sha256: str,
) -> tuple[ReplayStatus, str | None, GatewayIssue | None, GatewayIssue | None]:
    previous = request.previous_package_identity_sha256 or request.previous_input_manifest_sha256
    duplicate = request.duplicate_of_package_identity_sha256 or request.duplicate_of_input_manifest_sha256
    if previous:
        if previous.lower() == package_identity_sha256:
            return ReplayStatus.REPLAYED, "The complete analysis identity matches the previous package identity.", None, None
        message = "The complete analysis identity differs from the previous package identity; stale replay was blocked."
        return ReplayStatus.STALE, message, _issue("stale_replay_blocked", message), None
    if duplicate:
        if duplicate.lower() == package_identity_sha256:
            message = "The package was marked as a duplicate of the same complete analysis identity."
            return ReplayStatus.DUPLICATE, message, None, _issue("duplicate_input_declared", message, severity=GatewayIssueSeverity.WARNING)
        return ReplayStatus.NEW_INPUT, None, None, None
    if request.replay_key:
        return ReplayStatus.NEW_INPUT, None, None, None
    return ReplayStatus.NOT_REQUESTED, None, None, None


def _result(
    request: ResultGatewayRequest,
    *,
    pseudonymous_case_id: str | None,
    package_status: GatewayPackageStatus,
    replay_status: ReplayStatus,
    input_manifest_sha256: str,
    package_identity_sha256: str,
    actual_hashes: dict[str, str],
    canonical_hashes: dict[str, str],
    manifest_verified: bool,
    errors: list[GatewayIssue],
    warnings: list[GatewayIssue],
    stale_message: str | None,
    vcf: Any = None,
    lab: Any = None,
    qc: Any = None,
    coverage: Any = None,
    assay: Any = None,
    adapter_results: tuple[Any, ...] = (),
    accepted_ids: tuple[str, ...] = (),
    retained_ids: tuple[str, ...] = (),
    reference_build_mismatch_blocked: bool = False,
) -> ResultGatewayResult:
    definitions = registered_adapters()
    return ResultGatewayResult(
        pseudonymous_case_id=pseudonymous_case_id or request.declared_case_id,
        package_id=request.package_id,
        package_version=request.package_version,
        package_status=package_status,
        replay_status=replay_status,
        input_manifest_sha256=input_manifest_sha256,
        package_identity_sha256=package_identity_sha256,
        input_file_hashes=actual_hashes,
        manifest_entries=_normalized_manifest_entries(request.manifest),
        manifest_verified=manifest_verified,
        canonical_file_hashes=canonical_hashes,
        vcf=vcf,
        laboratory_report=lab,
        qc=qc,
        coverage=coverage,
        assay_scope=assay,
        tool_analysis_intent=request.tool_analysis_intent,
        adapter_definitions=definitions,
        adapter_results=adapter_results,
        tool_provenance=tuple(item.provenance for item in adapter_results),
        warnings=tuple(sorted(warnings, key=lambda item: (item.code, item.path or "", item.message))),
        errors=tuple(sorted(errors, key=lambda item: (item.code, item.path or "", item.message))),
        partial_output=package_status in {GatewayPackageStatus.PARTIAL, GatewayPackageStatus.COMPLETED_WITH_WARNINGS},
        stale_or_replay_message=stale_message,
        limits=request.limits,
        accepted_record_ids=accepted_ids,
        retained_out_of_scope_record_ids=retained_ids,
        reference_build_mismatch_blocked=reference_build_mismatch_blocked,
    )


def _manifest_digest_or_invalid(entries: tuple[ResultManifestEntry, ...]) -> str:
    try:
        return manifest_digest(entries)
    except ValueError:
        return canonical_payload_sha256([item.model_dump(mode="json") for item in entries])


def _normalized_manifest_entries(entries: tuple[ResultManifestEntry, ...]) -> tuple[ResultManifestEntry, ...]:
    normalized: list[ResultManifestEntry] = []
    for item in entries:
        try:
            normalized.append(
                item.model_copy(
                    update={
                        "safe_relative_path": validate_safe_relative_path(item.safe_relative_path),
                        "sha256": item.sha256.lower(),
                        "canonical_hash": item.canonical_hash.lower() if item.canonical_hash else None,
                    }
                )
            )
        except ValueError:
            normalized.append(item)
    return tuple(sorted(normalized, key=lambda item: (item.safe_relative_path.casefold(), item.safe_relative_path)))


def _package_identity_or_invalid(
    request: ResultGatewayRequest,
    *,
    actual_hashes: dict[str, str],
    actual_sizes: dict[str, int],
) -> str:
    try:
        return package_identity_digest(request, exact_file_hashes=actual_hashes, exact_file_sizes=actual_sizes)
    except ValueError:
        return canonical_payload_sha256({
            "identity_schema": "insilicopop.invalid-package-identity.v0.36.1",
            "package_id": request.package_id,
            "package_version": request.package_version,
            "schema_version": request.schema_version,
            "manifest": [item.model_dump(mode="json") for item in request.manifest],
            "exact_file_hashes": dict(sorted(actual_hashes.items())),
            "exact_file_sizes": dict(sorted(actual_sizes.items())),
        })


def _unique_mapping(records: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    duplicated: set[str] = set()
    for path, value in records:
        if path in result:
            duplicated.add(path)
        else:
            result[path] = value
    for path in duplicated:
        result.pop(path, None)
    return result


def _issue(
    code: str,
    message: str,
    *,
    path: str | None = None,
    severity: GatewayIssueSeverity = GatewayIssueSeverity.ERROR,
) -> GatewayIssue:
    return GatewayIssue(code=code, severity=severity, message=message, path=path)

