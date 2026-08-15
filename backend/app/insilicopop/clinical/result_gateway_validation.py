from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import unicodedata
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping

from app.insilicopop.clinical.result_gateway_models import (
    AdapterInvocationRequest,
    ResultGatewayRequest,
    ResultManifestEntry,
    SuppliedResultFile,
    ToolAnalysisIntent,
)
from app.insilicopop.clinical.validation import detect_direct_identifiers


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize an already-typed value with deterministic JSON ordering."""

    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_payload_sha256(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def stable_gateway_identifier(prefix: str, value: Any, *, length: int = 20) -> str:
    return f"{prefix}-{canonical_payload_sha256(value)[:length]}"


def validate_safe_relative_path(value: str) -> str:
    """Return the NFC canonical package path without resolving it on the host OS."""

    if not isinstance(value, str) or not value:
        raise ValueError("safe_relative_path must be a non-empty string")
    normalized_value = unicodedata.normalize("NFC", value)
    if "\x00" in normalized_value or any(unicodedata.category(char) == "Cc" for char in normalized_value):
        raise ValueError("safe_relative_path cannot contain control characters")
    if "://" in normalized_value or normalized_value.lower().startswith(("http:", "https:", "file:")):
        raise ValueError("remote and URL paths are not accepted")
    if "\\" in normalized_value:
        raise ValueError("safe_relative_path must use forward slashes only")
    if normalized_value.startswith("/") or re.match(r"^[A-Za-z]:", normalized_value):
        raise ValueError("absolute paths are not accepted")
    parts = normalized_value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("safe_relative_path cannot contain empty, dot, or parent components")
    if any(part.endswith((" ", ".")) for part in parts):
        raise ValueError("safe_relative_path components cannot end with a space or dot")
    canonical = str(PurePosixPath(*parts))
    if canonical != normalized_value or canonical.startswith("../"):
        raise ValueError("safe_relative_path is not canonical")
    return canonical


def safe_path_collision_key(value: str) -> str:
    """The uniqueness key mandated by v0.36: NFC normalization then case-folding."""

    return validate_safe_relative_path(value).casefold()


def supplied_file_bytes(item: SuppliedResultFile) -> bytes:
    if item.content_base64 is not None:
        try:
            return base64.b64decode(item.content_base64.encode("ascii"), validate=True)
        except (ValueError, UnicodeEncodeError, binascii.Error) as exc:
            raise ValueError("content_base64 is not valid base64") from exc
    if item.content_text is not None:
        return item.content_text.encode("utf-8")
    if item.content is None:
        raise ValueError("supplied file has no content")
    if item.content_encoding == "base64":
        try:
            return base64.b64decode(item.content.encode("ascii"), validate=True)
        except (ValueError, UnicodeEncodeError, binascii.Error) as exc:
            raise ValueError("content is not valid base64 for content_encoding=base64") from exc
    return item.content.encode("utf-8")


def manifest_digest(entries: Iterable[ResultManifestEntry]) -> str:
    payload = [
        {
            "logical_role": item.logical_role,
            "safe_relative_path": validate_safe_relative_path(item.safe_relative_path),
            "media_type": item.media_type,
            "sha256": item.sha256.lower(),
            "canonical_hash": item.canonical_hash.lower() if item.canonical_hash else None,
            "byte_size": item.byte_size,
            "parser_version": item.parser_version,
            "schema_version": item.schema_version,
        }
        for item in sorted(entries, key=lambda value: safe_path_collision_key(value.safe_relative_path))
    ]
    return canonical_payload_sha256(payload)


def package_identity_payload(
    request: ResultGatewayRequest,
    *,
    exact_file_hashes: Mapping[str, str],
    exact_file_sizes: Mapping[str, int],
) -> dict[str, Any]:
    """Build the complete, order-independent v0.36 analysis identity payload.

    Raw identifiers are represented only through domain-separated fingerprints.
    Replay control fields and runtime timestamps are intentionally excluded.
    """

    manifests = [
        {
            "safe_relative_path": validate_safe_relative_path(item.safe_relative_path),
            "logical_role": item.logical_role,
            "media_type": item.media_type,
            "sha256": item.sha256.lower(),
            "canonical_hash": item.canonical_hash.lower() if item.canonical_hash else None,
            "byte_size": item.byte_size,
            "parser_version": item.parser_version,
            "schema_version": item.schema_version,
        }
        for item in sorted(request.manifest, key=lambda value: safe_path_collision_key(value.safe_relative_path))
    ]
    exact_files = [
        {
            "safe_relative_path": path,
            "sha256": exact_file_hashes[path].lower(),
            "byte_size": exact_file_sizes[path],
        }
        for path in sorted(exact_file_hashes, key=lambda value: value.casefold())
        if path in exact_file_sizes
    ]
    assay_entry = next((item for item in manifests if item["logical_role"] == "assay_metadata"), None)
    return {
        "identity_schema": "insilicopop.package-identity.v0.36.1",
        "package": {
            "package_id": request.package_id,
            "schema_version": request.schema_version,
            "package_version": request.package_version,
            "declared_reference_build": request.declared_reference_build,
            "sample_identity_fingerprint": _binding_fingerprint("sample", request.expected_sample_id),
            "case_identity_fingerprint": _binding_fingerprint("case", request.declared_case_id),
            "human_review_required": request.human_review_required,
            "draft_not_clinically_approved": request.draft_not_clinically_approved,
        },
        "limits": request.limits.model_dump(mode="json"),
        "manifest": manifests,
        "exact_files": exact_files,
        "assay_metadata_binding": None
        if assay_entry is None
        else {
            "safe_relative_path": assay_entry["safe_relative_path"],
            "sha256": exact_file_hashes.get(assay_entry["safe_relative_path"], assay_entry["sha256"]).lower(),
            "byte_size": exact_file_sizes.get(assay_entry["safe_relative_path"], assay_entry["byte_size"]),
            "canonical_hash": assay_entry["canonical_hash"],
            "schema_version": assay_entry["schema_version"],
            "parser_version": assay_entry["parser_version"],
        },
        "tool_analysis_intent": _intent_identity(request.tool_analysis_intent),
        "adapter_invocations": [
            _invocation_identity(item)
            for item in sorted(request.adapter_invocations, key=lambda value: value.invocation_id)
        ],
    }


def package_identity_digest(
    request: ResultGatewayRequest,
    *,
    exact_file_hashes: Mapping[str, str],
    exact_file_sizes: Mapping[str, int],
) -> str:
    return canonical_payload_sha256(
        package_identity_payload(
            request,
            exact_file_hashes=exact_file_hashes,
            exact_file_sizes=exact_file_sizes,
        )
    )


def _binding_fingerprint(kind: str, value: str | None) -> str | None:
    if value is None:
        return None
    return sha256_bytes(f"insilicopop-v0.36-{kind}-binding\x00{value}".encode("utf-8"))


def _parameters_identity(parameters: Any) -> dict[str, Any] | None:
    return None if parameters is None else parameters.model_dump(mode="json")


def _intent_identity(intent: ToolAnalysisIntent | None) -> dict[str, Any] | None:
    if intent is None:
        return None
    return {
        "intent_id": intent.intent_id,
        "analysis_kind": intent.analysis_kind,
        "adapter_id": intent.adapter_id,
        "parameters": _parameters_identity(intent.parameters),
        "target_record_ids": intent.target_record_ids,
        "timeout_seconds": intent.timeout_seconds,
        "max_output_bytes": intent.max_output_bytes,
        "max_records": intent.max_records,
        "network_policy": intent.network_policy.value,
        "human_review_approved": intent.human_review_approved,
    }


def _invocation_identity(invocation: AdapterInvocationRequest) -> dict[str, Any]:
    return {
        "invocation_id": invocation.invocation_id,
        "adapter_id": invocation.adapter_id,
        "adapter_version": invocation.adapter_version,
        "parameters": invocation.parameters.model_dump(mode="json"),
        "input_file_hashes": sorted(value.lower() for value in invocation.input_file_hashes),
        "input_record_ids": invocation.input_record_ids,
        "timeout_seconds": invocation.timeout_seconds,
        "max_records": invocation.max_records,
        "max_output_bytes": invocation.max_output_bytes,
        "network_policy": invocation.network_policy.value,
        "working_directory_policy": invocation.working_directory_policy,
        "human_review_approved": invocation.human_review_approved,
    }


def redact_gateway_text(value: str | None, field_path: str) -> tuple[str | None, list[str]]:
    if value is None:
        return None, []
    codes = detect_direct_identifiers(value, field_path)
    if not codes:
        return value, []
    return "[REDACTED_DIRECT_IDENTIFIER]", sorted(set(codes))


def bounded_excerpt(value: str | None, *, max_chars: int = 4000) -> str:
    if not value:
        return ""
    text = value[:max_chars]
    return re.sub(
        r"(?i)(api[_ -]?key|access[_ -]?token|authorization|password|secret)\s*[:=]\s*\S+",
        r"\1=[REDACTED]",
        text,
    )
