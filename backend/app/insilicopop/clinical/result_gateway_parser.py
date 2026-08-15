from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.insilicopop.clinical.result_gateway_models import (
    PARSER_VERSION,
    AltPresenceState,
    AssayScopeSummary,
    CoverageSummary,
    GatewayIssue,
    GatewayIssueSeverity,
    LaboratoryReportFinding,
    OutOfScopeReasonCode,
    PoorCoverageRegion,
    QualityControlSummary,
    ResultLogicalRole,
    ResultSourceState,
    RetainedOutOfScopeRecord,
    StructuredLaboratoryReport,
    SuppliedAccreditationClaim,
    SuppliedAnnotation,
    VCFFormatValue,
    VCFGenotypeCall,
    VCFHeaderMetadata,
    VCFInfoDefinition,
    VCFParseResult,
    VCFPhaseState,
    VCFSampleAltPresence,
    VCFSampleCall,
    VCFVariantRecord,
    VariantNormalizationState,
    VariantScope,
    VerificationState,
)
from app.insilicopop.clinical.result_gateway_validation import (
    bounded_excerpt,
    canonical_payload_sha256,
    redact_gateway_text,
    sha256_bytes,
    stable_gateway_identifier,
)


_FIELD_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]*$")
_INFO_TYPES = {"Integer", "Float", "Flag", "Character", "String"}


@dataclass
class ParsedFile:
    """Mutable only while a file is being parsed; never persisted or returned by the API."""

    vcf: VCFParseResult | None = None
    laboratory_report: StructuredLaboratoryReport | None = None
    qc: QualityControlSummary | None = None
    coverage: CoverageSummary | None = None
    assay_scope: AssayScopeSummary | None = None
    issues: list[GatewayIssue] = field(default_factory=list)
    canonical_payload: Any | None = None
    record_count: int = 0


def parse_vcf_bytes(
    source_file: str,
    data: bytes,
    *,
    declared_reference_build: str | None = None,
    expected_sample_id: str | None = None,
    max_records: int = 10_000,
) -> VCFParseResult:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return _empty_vcf(
            source_file,
            _issue("vcf_not_utf8", "VCF bytes could not be decoded as UTF-8.", source_file),
        )

    lines = text.splitlines()
    header_lines = [line for line in lines if line.startswith("#")]
    issues: list[GatewayIssue] = []
    format_lines = [line for line in header_lines if line.startswith("##fileformat=")]
    chrom_lines = [line for line in header_lines if line.startswith("#CHROM\t")]
    if len(format_lines) != 1 or not format_lines[0].split("=", 1)[1].startswith("VCFv"):
        issues.append(_issue("vcf_fileformat_header_missing_or_invalid", "Exactly one valid ##fileformat=VCFv header is required.", source_file))
    if len(chrom_lines) != 1:
        issues.append(_issue("vcf_column_header_missing_or_duplicate", "Exactly one #CHROM column header is required.", source_file))
    chrom_line = chrom_lines[0] if len(chrom_lines) == 1 else None

    reference_declarations = tuple(
        line.split("=", 1)[1].strip()
        for line in header_lines
        if (line.startswith("##reference=") or line.startswith("##assembly=")) and line.split("=", 1)[1].strip()
    )
    unique_references = tuple(dict.fromkeys(reference_declarations))
    reference_build: str | None = unique_references[0] if len(unique_references) == 1 else None
    if len(unique_references) > 1:
        issues.append(_issue("conflicting_reference_declarations", "VCF reference/build declarations conflict; processing is blocked.", source_file))
    elif len(reference_declarations) > 1:
        issues.append(_issue("repeated_reference_declaration", "Identical VCF reference/build declarations were retained deterministically.", source_file, GatewayIssueSeverity.WARNING))

    info_definitions, info_definition_issues = _parse_info_definitions(header_lines, source_file)
    issues.extend(info_definition_issues)
    info_by_id = {item.info_id: item for item in info_definitions}
    contigs = tuple(
        value.split("ID=", 1)[1].split(",", 1)[0].rstrip(">")
        for value in header_lines
        if value.startswith("##contig=<") and "ID=" in value
    )

    header_columns: tuple[str, ...] = ()
    raw_sample_names: tuple[str, ...] = ()
    clean_sample_names: list[str] = []
    if chrom_line:
        header_columns = tuple(chrom_line.split("\t"))
        fixed = ("#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO")
        if len(header_columns) < 8 or header_columns[:8] != fixed:
            issues.append(_issue("vcf_column_header_invalid", "VCF columns must begin with CHROM, POS, ID, REF, ALT, QUAL, FILTER, INFO.", source_file))
        if len(header_columns) == 9 and header_columns[8] != "FORMAT":
            issues.append(_issue("vcf_format_header_invalid", "A ninth VCF column must be named FORMAT.", source_file))
        if len(header_columns) > 9 and header_columns[8] != "FORMAT":
            issues.append(_issue("vcf_format_header_invalid", "Sample columns require a ninth FORMAT column.", source_file))
        raw_sample_names = header_columns[9:] if len(header_columns) > 9 else ()
        if any(not name for name in raw_sample_names) or len(raw_sample_names) != len(set(raw_sample_names)):
            issues.append(_issue("vcf_sample_header_invalid", "VCF sample identifiers must be non-empty and unique.", source_file))
        for index, sample_name in enumerate(raw_sample_names):
            redacted, codes = redact_gateway_text(sample_name, f"{source_file}.sample_name[{index}]")
            if codes:
                issues.append(_issue("direct_identifier_in_sample_name", "A direct identifier was detected in a VCF sample name and was redacted before persistence.", source_file))
            clean_sample_names.append(redacted or "[REDACTED_DIRECT_IDENTIFIER]")

    build_validation: str = "not_assessed"
    if len(unique_references) > 1:
        build_validation = "mismatch"
    elif declared_reference_build and reference_build:
        if declared_reference_build == reference_build:
            build_validation = "matched"
        else:
            build_validation = "mismatch"
            issues.append(_issue("reference_build_mismatch", "Declared reference build and VCF header reference build differ; gateway processing is blocked.", source_file))
    elif declared_reference_build or reference_build:
        issues.append(_issue("reference_build_not_fully_declared", "Only one of the package and VCF header reference-build declarations was supplied.", source_file, GatewayIssueSeverity.WARNING))
    else:
        build_validation = "not_declared"
        issues.append(_issue("reference_build_not_declared", "No VCF or package reference build was declared.", source_file, GatewayIssueSeverity.WARNING))

    if expected_sample_id and clean_sample_names and expected_sample_id not in clean_sample_names:
        issues.append(_issue("sample_identifier_mismatch", "The expected pseudonymous sample ID is not present; no sample identity inference was attempted.", source_file))

    header = VCFHeaderMetadata(
        source_file=source_file,
        fileformat=format_lines[0].split("=", 1)[1] if len(format_lines) == 1 else "unknown",
        reference_build=reference_build,
        reference_declarations=reference_declarations,
        contig_names=contigs,
        sample_names=tuple(clean_sample_names),
        info_definitions=tuple(info_definitions),
        header_sha256=sha256_bytes(("\n".join(header_lines) + ("\n" if header_lines else "")).encode("utf-8")),
        build_validation=build_validation,
    )

    records: list[VCFVariantRecord] = []
    retained: list[RetainedOutOfScopeRecord] = []
    all_annotations: list[SuppliedAnnotation] = []
    source_record_count = 0
    multiallelic_count = 0
    if not header_columns:
        return VCFParseResult(
            source_file=source_file,
            header=header,
            records=(),
            retained_out_of_scope=(),
            supplied_annotations=(),
            issues=tuple(issues),
            record_count=0,
            in_scope_record_count=0,
            out_of_scope_record_count=0,
            multiallelic_source_record_count=0,
        )

    for line_number, line in enumerate(lines, start=1):
        if not line or line.startswith("#"):
            continue
        source_record_count += 1
        if source_record_count > max_records:
            issues.append(_issue("vcf_record_budget_exceeded", f"VCF record count exceeded the configured limit of {max_records}.", source_file))
            break
        source_hash = sha256_bytes(line.encode("utf-8"))
        source_record_id = stable_gateway_identifier("vcf-source", {"file": source_file, "line": line_number, "sha256": source_hash})
        columns = line.split("\t")
        if len(columns) != len(header_columns):
            issues.append(_record_issue("vcf_record_column_count_mismatch", "VCF record column count does not match the #CHROM header; no columns were dropped.", source_file, line_number, source_record_id))
            continue
        chromosome, position_text, source_id, reference, alt_text, quality, filter_status, info_token = columns[:8]
        if not chromosome or not reference or reference == "." or not alt_text or alt_text == ".":
            issues.append(_record_issue("vcf_record_required_field_invalid", "VCF CHROM, REF and ALT must be supplied.", source_file, line_number))
            continue
        try:
            position = int(position_text)
            if position < 1:
                raise ValueError
        except ValueError:
            issues.append(_record_issue("vcf_position_invalid", "VCF POS must be a positive integer.", source_file, line_number))
            continue
        alternates = tuple(alt_text.split(","))
        if any(not value or value == "." for value in alternates):
            issues.append(_record_issue("vcf_alt_invalid", "VCF ALT contains an empty or missing allele.", source_file, line_number))
            continue
        if len(alternates) > 1:
            multiallelic_count += 1
        info_fields, info_errors = _parse_info_fields(info_token, info_by_id, source_file, source_record_id)
        if info_errors:
            issues.extend(_record_issue(code, message, source_file, line_number, source_record_id) for code, message in info_errors)
            continue
        all_annotations.extend(info_fields)

        format_keys: tuple[str, ...] = ()
        source_format_token: str | None = None
        sample_calls: tuple[VCFSampleCall, ...] = ()
        if len(header_columns) >= 9:
            source_format_token = columns[8]
            format_keys, format_error = _parse_format_keys(source_format_token)
            if format_error:
                issues.append(_record_issue(format_error[0], format_error[1], source_file, line_number, source_record_id))
                continue
            parsed_calls: list[VCFSampleCall] = []
            sample_error = False
            for sample_index, (sample_name, sample_token) in enumerate(zip(clean_sample_names, columns[9:])):
                try:
                    parsed_calls.append(
                        _parse_sample_call(
                            source_file,
                            source_record_id,
                            sample_index,
                            sample_name,
                            sample_token,
                            format_keys,
                            alt_count=len(alternates),
                        )
                    )
                except ValueError as exc:
                    issues.append(_record_issue("vcf_sample_format_malformed", str(exc), source_file, line_number, source_record_id))
                    sample_error = True
            if sample_error:
                continue
            sample_calls = tuple(parsed_calls)

        for alt_index, alternate in enumerate(alternates, start=1):
            record_id = stable_gateway_identifier(
                "vcf-record",
                {"source_record_id": source_record_id, "alt_index": alt_index, "alternate": alternate},
            )
            scope, reason_code, reason = _variant_scope(chromosome, reference, alternate, info_fields)
            in_scope = scope in {VariantScope.SNV, VariantScope.SMALL_INDEL}
            selected_presence = tuple(_alt_presence(call, alt_index) for call in sample_calls)
            record = VCFVariantRecord(
                record_id=record_id,
                source_record_id=source_record_id,
                source_file=source_file,
                source_record_sha256=source_hash,
                chromosome=chromosome,
                position=position,
                source_id=None if source_id == "." else source_id,
                reference_allele=reference,
                alternate_allele=alternate,
                quality=None if quality == "." else quality,
                filter_status=None if filter_status == "." else filter_status,
                source_info_token=info_token,
                source_format_token=source_format_token,
                format_keys=format_keys,
                sample_calls=sample_calls,
                selected_alt_presence=selected_presence,
                variant_scope=scope,
                source_state=ResultSourceState.SUPPLIED,
                normalized_state=(
                    VariantNormalizationState.REFERENCE_DEPENDENT_LEFT_NORMALIZATION_NOT_APPLIED
                    if in_scope
                    else VariantNormalizationState.OUT_OF_SCOPE_RETAINED
                ),
                normalized_chromosome=chromosome if in_scope else None,
                normalized_position=position if in_scope else None,
                normalized_reference_allele=reference if in_scope else None,
                normalized_alternate_allele=alternate if in_scope else None,
                source_alt_index=alt_index,
                source_alt_count=len(alternates),
                decomposition_performed=len(alternates) > 1,
                supplied_annotations=tuple(info_fields),
                out_of_scope_reason_code=reason_code,
                reason_if_out_of_scope=reason,
                review_status="accepted_for_review" if in_scope else "retained_out_of_scope",
            )
            records.append(record)
            if not in_scope and reason_code is not None and reason is not None:
                retained.append(
                    RetainedOutOfScopeRecord(
                        record_id=record_id,
                        source_file=source_file,
                        source_record_sha256=source_hash,
                        variant_scope=scope,
                        reason_code=reason_code,
                        reason=reason,
                    )
                )

    in_scope_count = sum(item.variant_scope in {VariantScope.SNV, VariantScope.SMALL_INDEL} for item in records)
    return VCFParseResult(
        source_file=source_file,
        header=header,
        records=tuple(records),
        retained_out_of_scope=tuple(retained),
        supplied_annotations=tuple(all_annotations),
        issues=tuple(issues),
        record_count=min(source_record_count, max_records),
        in_scope_record_count=in_scope_count,
        out_of_scope_record_count=len(retained),
        multiallelic_source_record_count=multiallelic_count,
        decomposition_performed=multiallelic_count > 0,
    )


def parse_structured_result_file(
    source_file: str,
    logical_role: str,
    data: bytes,
    *,
    max_records: int = 10_000,
) -> ParsedFile:
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ParsedFile(issues=[_issue("structured_result_json_invalid", f"Structured {logical_role} input must be valid UTF-8 JSON.", source_file)])
    if not isinstance(payload, dict):
        return ParsedFile(issues=[_issue("structured_result_shape_invalid", f"Structured {logical_role} input must be a JSON object.", source_file)])
    role = logical_role
    if role == ResultLogicalRole.STRUCTURED_LABORATORY_REPORT.value:
        model = _parse_laboratory_report(source_file, payload, max_records=max_records)
        return ParsedFile(laboratory_report=model, issues=_report_warnings(model.warnings, source_file), canonical_payload=model.model_dump(mode="json"), record_count=len(model.findings))
    if role == "qc":
        model = _parse_qc(source_file, payload)
        return ParsedFile(qc=model, canonical_payload=model.model_dump(mode="json"), record_count=len(model.metrics))
    if role == "coverage":
        model = _parse_coverage(source_file, payload, max_records=max_records)
        return ParsedFile(coverage=model, canonical_payload=model.model_dump(mode="json"), record_count=len(model.poor_regions))
    if role == "assay_metadata":
        model = _parse_assay_scope(source_file, payload)
        return ParsedFile(assay_scope=model, canonical_payload=model.model_dump(mode="json"), record_count=len(model.reportable_regions) + len(model.reportable_genes))
    return ParsedFile(issues=[_issue("unregistered_logical_role", f"No fixed v0.36 parser is registered for logical role {logical_role}.", source_file)])


def _parse_info_definitions(header_lines: list[str], source_file: str) -> tuple[list[VCFInfoDefinition], list[GatewayIssue]]:
    definitions: list[VCFInfoDefinition] = []
    issues: list[GatewayIssue] = []
    seen: set[str] = set()
    for line in header_lines:
        if not line.startswith("##INFO="):
            continue
        try:
            if not line.startswith("##INFO=<") or not line.endswith(">"):
                raise ValueError("INFO definition must use ##INFO=<...> syntax")
            inner = line[len("##INFO=<") : -1]
            tokens = next(csv.reader([inner], skipinitialspace=True))
            values: dict[str, str] = {}
            for token in tokens:
                if "=" not in token:
                    raise ValueError("INFO definition attributes require key=value syntax")
                key, value = token.split("=", 1)
                if not key or key in values:
                    raise ValueError("INFO definition attributes must be non-empty and unique")
                values[key] = value
            info_id = values.get("ID", "")
            number = values.get("Number", "")
            value_type = values.get("Type", "")
            if not _FIELD_ID.fullmatch(info_id) or not number or value_type not in _INFO_TYPES:
                raise ValueError("INFO definition requires valid ID, Number and Type attributes")
            if info_id in seen:
                issues.append(_issue("duplicate_info_header_definition", f"INFO definition {info_id} is duplicated.", source_file))
                continue
            seen.add(info_id)
            definitions.append(
                VCFInfoDefinition(
                    info_id=info_id,
                    number=number,
                    value_type=value_type,
                    description=values.get("Description"),
                    source_token=line,
                )
            )
        except (ValueError, csv.Error) as exc:
            issues.append(_issue("malformed_info_header_definition", str(exc), source_file))
    return definitions, issues


def _parse_info_fields(
    token_value: str,
    definitions: dict[str, VCFInfoDefinition],
    source_file: str,
    source_record_id: str,
) -> tuple[tuple[SuppliedAnnotation, ...], list[tuple[str, str]]]:
    if token_value == ".":
        return (), []
    if token_value == "" or token_value.isspace():
        return (), [("vcf_info_field_empty", "INFO is empty or whitespace-only; '.' is the sole missing INFO representation.")]
    parsed: list[SuppliedAnnotation] = []
    errors: list[tuple[str, str]] = []
    seen: set[str] = set()
    for source_token in token_value.split(";"):
        if not source_token:
            errors.append(("vcf_info_token_empty", "INFO contains an empty token."))
            continue
        if "=" in source_token:
            key, value = source_token.split("=", 1)
            if not _FIELD_ID.fullmatch(key) or value == "":
                errors.append(("vcf_info_token_malformed", f"INFO token {source_token!r} is malformed."))
                continue
            is_flag = False
        else:
            key, value = source_token, "true"
            definition = definitions.get(key)
            if not _FIELD_ID.fullmatch(key) or definition is None or definition.value_type != "Flag":
                errors.append(("vcf_info_bare_nonflag", f"Bare INFO key {key!r} is permitted only for a declared Type=Flag field."))
                continue
            is_flag = True
        if key in seen:
            errors.append(("vcf_info_duplicate_key", f"INFO key {key!r} occurs more than once in one record."))
            continue
        seen.add(key)
        definition = definitions.get(key)
        if definition is not None and definition.value_type == "Flag" and not is_flag:
            errors.append(("vcf_info_flag_with_value", f"Declared Flag INFO key {key!r} must be supplied as a bare key."))
            continue
        parsed.append(
            SuppliedAnnotation(
                key=key,
                value=value,
                source_token=source_token,
                declared_type=definition.value_type if definition else None,
                declared_in_header=definition is not None,
                is_flag=is_flag,
                source_field="vcf_info",
                source_file=source_file,
                source_record_id=source_record_id,
                provenance_hash=canonical_payload_sha256({"file": source_file, "record": source_record_id, "token": source_token}),
            )
        )
    return tuple(parsed), errors


def _parse_format_keys(source_token: str) -> tuple[tuple[str, ...], tuple[str, str] | None]:
    if source_token in {"", "."}:
        return (), None
    keys = tuple(source_token.split(":"))
    if any(not key or not _FIELD_ID.fullmatch(key) for key in keys):
        return (), ("vcf_format_key_malformed", "FORMAT contains an empty or malformed key.")
    if len(keys) != len(set(keys)):
        return (), ("vcf_format_key_duplicate", "FORMAT keys must be unique within a record.")
    return keys, None


def _parse_sample_call(
    source_file: str,
    source_record_id: str,
    sample_index: int,
    sample_name: str,
    source_token: str,
    format_keys: tuple[str, ...],
    *,
    alt_count: int,
) -> VCFSampleCall:
    if not format_keys:
        if source_token not in {"", "."}:
            raise ValueError("sample data was supplied without FORMAT keys")
        return VCFSampleCall(sample_index=sample_index, sample_name=sample_name, source_token=source_token)
    values = tuple("." for _ in format_keys) if source_token == "." else tuple(source_token.split(":"))
    if len(values) != len(format_keys):
        raise ValueError("sample value count does not match FORMAT key count")
    format_values = tuple(
        VCFFormatValue(
            key=key,
            source_token=value,
            is_missing=value in {"", "."},
            provenance_hash=canonical_payload_sha256(
                {"file": source_file, "record": source_record_id, "sample_index": sample_index, "key": key, "value": value}
            ),
        )
        for key, value in zip(format_keys, values)
    )
    value_by_key = dict(zip(format_keys, values))
    genotype = _parse_genotype(value_by_key["GT"], alt_count=alt_count) if "GT" in value_by_key else None
    phase_set = value_by_key.get("PS")
    if phase_set in {None, "", "."}:
        phase_set = None
    return VCFSampleCall(
        sample_index=sample_index,
        sample_name=sample_name,
        source_token=source_token,
        format_values=format_values,
        genotype=genotype,
        phase_set_source_token=phase_set,
    )


def _parse_genotype(source_token: str, *, alt_count: int) -> VCFGenotypeCall:
    if source_token == "":
        raise ValueError("GT cannot be an empty token; use '.' for a missing allele")
    pieces = re.split(r"([/|])", source_token)
    allele_tokens = pieces[::2]
    separators = tuple(pieces[1::2])
    if not allele_tokens or any(token == "" for token in allele_tokens) or len(separators) != len(allele_tokens) - 1:
        raise ValueError("GT has malformed allele separators")
    if len(allele_tokens) > 100:
        raise ValueError("GT ploidy exceeds the bounded limit of 100")
    alleles: list[int | None] = []
    for token in allele_tokens:
        if token == ".":
            alleles.append(None)
        elif token.isdigit():
            index = int(token)
            if index > alt_count:
                raise ValueError("GT allele index exceeds the ALT allele count")
            alleles.append(index)
        else:
            raise ValueError("GT alleles must be non-negative indices or '.'")
    if separators and all(value == "|" for value in separators):
        phase_state = VCFPhaseState.PHASED
    elif separators and all(value == "/" for value in separators):
        phase_state = VCFPhaseState.UNPHASED
    else:
        phase_state = VCFPhaseState.UNKNOWN
    complete_missing = all(value is None for value in alleles)
    partial_missing = any(value is None for value in alleles) and not complete_missing
    return VCFGenotypeCall(
        source_token=source_token,
        allele_indices=tuple(alleles),
        separators=separators,
        ploidy=len(alleles),
        phase_state=phase_state,
        complete_missing=complete_missing,
        partial_missing=partial_missing,
    )


def _alt_presence(call: VCFSampleCall, selected_alt_index: int) -> VCFSampleAltPresence:
    genotype = call.genotype
    if genotype is None:
        state, reason = AltPresenceState.UNKNOWN, "source_gt_not_supplied"
    elif selected_alt_index in genotype.allele_indices:
        state, reason = AltPresenceState.PRESENT, "selected_alt_index_present_in_source_gt"
    elif any(value is None for value in genotype.allele_indices):
        state, reason = AltPresenceState.UNKNOWN, "source_gt_missing_or_partial"
    else:
        state, reason = AltPresenceState.ABSENT, "selected_alt_index_absent_from_complete_source_gt"
    return VCFSampleAltPresence(
        sample_index=call.sample_index,
        sample_name=call.sample_name,
        selected_alt_index=selected_alt_index,
        state=state,
        reason=reason,
    )


def _parse_laboratory_report(source_file: str, payload: dict[str, Any], *, max_records: int) -> StructuredLaboratoryReport:
    warnings: list[str] = []
    findings: list[LaboratoryReportFinding] = []
    raw_findings = payload.get("findings", [])
    if not isinstance(raw_findings, list):
        warnings.append("findings was supplied but was not a list; no findings were parsed.")
        raw_findings = []
    for index, item in enumerate(raw_findings[:max_records]):
        if isinstance(item, dict):
            value = _text(item.get("value_as_reported") or item.get("value") or item.get("finding"))
            classification = _text(item.get("classification_as_reported") or item.get("classification"))
            source_payload = item
        else:
            value, classification, source_payload = _text(item), None, {"value": item}
        if not value:
            warnings.append(f"finding[{index}] had no supplied value and was skipped.")
            continue
        safe_value, codes = redact_gateway_text(value, f"{source_file}.findings[{index}]")
        safe_classification, class_codes = redact_gateway_text(classification, f"{source_file}.findings[{index}].classification")
        if codes or class_codes:
            warnings.append(f"finding[{index}] contained a direct identifier; affected text was redacted.")
        findings.append(
            LaboratoryReportFinding(
                finding_id=stable_gateway_identifier("lab-finding", {"file": source_file, "index": index, "value": value}),
                value_as_reported=safe_value or "[REDACTED_DIRECT_IDENTIFIER]",
                source_hash=canonical_payload_sha256(source_payload),
                classification_as_reported=safe_classification,
            )
        )
    fields = {
        "report_id": _safe_text(payload.get("report_id") or payload.get("id"), source_file, "report_id", warnings),
        "laboratory_name": _safe_text(payload.get("laboratory_name") or payload.get("lab_name"), source_file, "laboratory_name", warnings),
        "laboratory_reference": _safe_text(payload.get("laboratory_reference") or payload.get("lab_reference"), source_file, "laboratory_reference", warnings),
        "accreditation_scope": _safe_text(payload.get("accreditation_scope"), source_file, "accreditation_scope", warnings),
        "assay_or_test_type": _safe_text(payload.get("assay_or_test_type") or payload.get("test_type") or payload.get("assay"), source_file, "assay_or_test_type", warnings),
        "platform": _safe_text(payload.get("platform"), source_file, "platform", warnings),
        "genome_build": _safe_text(payload.get("genome_build") or payload.get("reference_build"), source_file, "genome_build", warnings),
        "transcript_version": _safe_text(payload.get("transcript_version"), source_file, "transcript_version", warnings),
        "confirmation_method": _safe_text(payload.get("confirmation_method"), source_file, "confirmation_method", warnings),
        "report_date": _safe_text(payload.get("report_date"), source_file, "report_date", warnings),
        "turnaround_time": _safe_text(payload.get("turnaround_time") or payload.get("tat"), source_file, "turnaround_time", warnings),
        "shipping_or_transport": _safe_text(payload.get("shipping_or_transport") or payload.get("transport"), source_file, "shipping_or_transport", warnings),
        "access_or_affordability_notes": _safe_text(payload.get("access_or_affordability_notes") or payload.get("affordability"), source_file, "access_or_affordability_notes", warnings),
    }
    database_versions = payload.get("database_versions") if isinstance(payload.get("database_versions"), dict) else {}
    clean_db = {str(key): str(value) for key, value in database_versions.items() if value is not None}
    claims = _parse_accreditation_claims(source_file, payload, fields["accreditation_scope"], warnings)
    status = _package_verification_state(payload.get("accreditation_status"), has_claim=bool(claims), warnings=warnings, field="accreditation_status")
    scope_status = _package_verification_state(payload.get("accreditation_scope_verification"), has_claim=fields["accreditation_scope"] is not None, warnings=warnings, field="accreditation_scope_verification")
    for prohibited in ("trusted_accreditation_evidence", "nabl_evidence", "iso_15189_evidence"):
        if payload.get(prohibited) not in (None, [], {}):
            warnings.append(f"{prohibited} was package-supplied and cannot enter the trusted evidence channel; it was not persisted as verified evidence.")
    return StructuredLaboratoryReport(
        source_file=source_file,
        report_id=fields["report_id"],
        laboratory_name=fields["laboratory_name"],
        laboratory_reference=fields["laboratory_reference"],
        accreditation_status=status,
        accreditation_scope=fields["accreditation_scope"],
        accreditation_scope_verification=scope_status,
        accreditation_claims=tuple(claims),
        trusted_accreditation_evidence=(),
        assay_or_test_type=fields["assay_or_test_type"],
        platform=fields["platform"],
        genome_build=fields["genome_build"],
        transcript_version=fields["transcript_version"],
        database_versions=clean_db,
        confirmation_method=fields["confirmation_method"],
        report_date=fields["report_date"],
        turnaround_time=fields["turnaround_time"],
        shipping_or_transport=fields["shipping_or_transport"],
        access_or_affordability_notes=fields["access_or_affordability_notes"],
        findings=tuple(findings),
        warnings=tuple(warnings),
    )


def _parse_accreditation_claims(source_file: str, payload: dict[str, Any], fallback_scope: str | None, warnings: list[str]) -> list[SuppliedAccreditationClaim]:
    raw = payload.get("accreditation_claims")
    raw_claims = raw if isinstance(raw, list) else []
    if raw is not None and not isinstance(raw, list):
        warnings.append("accreditation_claims was not a list and was not accepted.")
    if not raw_claims and any(payload.get(key) is not None for key in ("accreditation_status", "accreditation_scope", "accreditation_body", "accreditation_standard", "accreditation_certificate")):
        raw_claims = [{
            "claim_kind": "other",
            "accreditation_body_or_standard": payload.get("accreditation_body") or payload.get("accreditation_standard"),
            "certificate_or_reference_identifier": payload.get("accreditation_certificate"),
            "supplied_scope": fallback_scope,
            "supplied_status_text": payload.get("accreditation_status"),
        }]
    claims: list[SuppliedAccreditationClaim] = []
    for index, item in enumerate(raw_claims[:20]):
        if not isinstance(item, dict):
            warnings.append(f"accreditation_claims[{index}] was not an object and was skipped.")
            continue
        raw_kind = str(item.get("claim_kind") or item.get("standard") or "other").strip().upper().replace(" ", "_")
        kind = "NABL" if raw_kind == "NABL" else "ISO_15189" if raw_kind in {"ISO_15189", "ISO15189"} else "other"
        supplied_status = _text(item.get("supplied_status_text") or item.get("status"))
        state = _package_verification_state(supplied_status, has_claim=True, warnings=warnings, field=f"accreditation_claims[{index}].status")
        if state == VerificationState.NOT_SUPPLIED:
            state = VerificationState.SUPPLIED_BUT_UNVERIFIED
        claims.append(
            SuppliedAccreditationClaim(
                claim_kind=kind,
                accreditation_body_or_standard=_safe_text(item.get("accreditation_body_or_standard") or item.get("body") or item.get("standard"), source_file, f"accreditation_claims[{index}].body", warnings),
                certificate_or_reference_identifier=_safe_text(item.get("certificate_or_reference_identifier") or item.get("certificate") or item.get("reference"), source_file, f"accreditation_claims[{index}].certificate", warnings),
                supplied_scope=_safe_text(item.get("supplied_scope") or item.get("scope") or fallback_scope, source_file, f"accreditation_claims[{index}].scope", warnings),
                supplied_status_text=_safe_text(supplied_status, source_file, f"accreditation_claims[{index}].status", warnings),
                verification_state=state,
                source_hash=canonical_payload_sha256({"file": source_file, "index": index, "claim": item}),
            )
        )
    return claims


def _parse_qc(source_file: str, payload: dict[str, Any]) -> QualityControlSummary:
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {
        str(key): value for key, value in payload.items() if key not in {"sample_id", "warnings", "metrics"} and isinstance(value, (str, int, float, bool))
    }
    clean_metrics: dict[str, str | int | float | bool | None] = {}
    provenance: list[SuppliedAnnotation] = []
    for key, value in sorted(metrics.items()):
        if not isinstance(value, (str, int, float, bool)) and value is not None:
            continue
        safe_value, _ = redact_gateway_text(str(value) if value is not None else None, f"{source_file}.metrics.{key}")
        clean_metrics[str(key)] = safe_value if isinstance(value, str) and safe_value is not None else value
        provenance.append(SuppliedAnnotation(key=str(key), value=str(safe_value if safe_value is not None else value), source_field="qc", source_file=source_file, provenance_hash=canonical_payload_sha256({"file": source_file, "key": key, "value": value})))
    safe_warnings = _safe_text_list(payload.get("warnings", []), source_file, "warnings")
    safe_sample_id, _ = redact_gateway_text(_text(payload.get("sample_id")), f"{source_file}.sample_id")
    return QualityControlSummary(source_file=source_file, sample_id_as_reported=safe_sample_id, metrics=clean_metrics, warnings=tuple(safe_warnings), provenance=tuple(provenance))


def _parse_coverage(source_file: str, payload: dict[str, Any], *, max_records: int) -> CoverageSummary:
    raw_regions = payload.get("poor_regions", payload.get("regions", []))
    if not isinstance(raw_regions, list):
        raw_regions = []
    regions: list[PoorCoverageRegion] = []
    for index, raw_item in enumerate(raw_regions[:max_records]):
        item = raw_item if isinstance(raw_item, dict) else {"gene_or_region": _text(raw_item)}
        regions.append(PoorCoverageRegion(
            region_id=stable_gateway_identifier("poor-region", {"file": source_file, "index": index, "item": item}),
            chromosome=_text(item.get("chromosome") or item.get("chrom")),
            start=_positive_int(item.get("start")),
            end=_positive_int(item.get("end")),
            gene_or_region=_text(item.get("gene_or_region") or item.get("region") or item.get("gene")),
            supplied_coverage=item.get("coverage") if isinstance(item.get("coverage"), (str, int, float)) else None,
            reason=_text(item.get("reason")),
            source_hash=canonical_payload_sha256({"file": source_file, "index": index, "item": item}),
        ))
    raw_metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    metrics = {str(key): value for key, value in raw_metrics.items() if isinstance(value, (str, int, float, bool)) or value is None}
    safe_sample_id, _ = redact_gateway_text(_text(payload.get("sample_id")), f"{source_file}.sample_id")
    return CoverageSummary(
        source_file=source_file,
        sample_id_as_reported=safe_sample_id,
        minimum_coverage_declared=payload.get("minimum_coverage") or payload.get("min_coverage"),
        mean_coverage_declared=payload.get("mean_coverage"),
        poor_regions=tuple(regions),
        metrics=metrics,
        warnings=tuple(_safe_text_list(payload.get("warnings", []), source_file, "warnings")),
    )


def _parse_assay_scope(source_file: str, payload: dict[str, Any]) -> AssayScopeSummary:
    def texts(key: str, alternate: str | None = None) -> tuple[str, ...]:
        value = payload.get(key, payload.get(alternate) if alternate else [])
        values = [value] if isinstance(value, str) else value if isinstance(value, list) else []
        cleaned: list[str] = []
        for item in values:
            safe, _ = redact_gateway_text(_text(item), f"{source_file}.{key}")
            if safe:
                cleaned.append(safe)
        return tuple(cleaned)
    return AssayScopeSummary(
        source_file=source_file,
        reportable_genes=texts("reportable_genes"),
        reportable_transcripts=texts("reportable_transcripts"),
        reportable_regions=texts("reportable_regions", "regions"),
        blind_spots=texts("blind_spots", "limitations"),
        minimum_coverage_requirement=payload.get("minimum_coverage_requirement"),
        poor_region_policy_as_supplied=_redacted_text(payload.get("poor_region_policy"), source_file, "poor_region_policy"),
        cnv_scope=_redacted_text(payload.get("cnv_scope"), source_file, "cnv_scope"),
        mitochondrial_scope=_redacted_text(payload.get("mitochondrial_scope") or payload.get("mt_scope"), source_file, "mitochondrial_scope"),
        repeat_scope=_redacted_text(payload.get("repeat_scope"), source_file, "repeat_scope"),
        mosaic_scope=_redacted_text(payload.get("mosaic_scope"), source_file, "mosaic_scope"),
        mosaic_threshold_as_supplied=payload.get("mosaic_threshold"),
        confirmation_methods=texts("confirmation_methods"),
    )


def _variant_scope(
    chromosome: str,
    reference: str,
    alternate: str,
    info_fields: tuple[SuppliedAnnotation, ...],
) -> tuple[VariantScope, OutOfScopeReasonCode | None, str | None]:
    info = {item.key.upper(): item.value.upper() for item in info_fields}
    chrom_lower = chromosome.lower().removeprefix("chr")
    if chrom_lower in {"m", "mt"}:
        return VariantScope.MITOCHONDRIAL_OUT_OF_SCOPE, OutOfScopeReasonCode.MITOCHONDRIAL_VARIANT, "The supplied chromosome explicitly identifies a mitochondrial record, which is retained outside the v0.36 calling scope."
    svtype = info.get("SVTYPE", "")
    if svtype in {"STR", "REPEAT", "EXPANSION"}:
        return VariantScope.REPEAT_OUT_OF_SCOPE, OutOfScopeReasonCode.EXPLICIT_REPEAT, "The supplied SVTYPE explicitly identifies a repeat/expansion record, which is retained outside scope."
    if info.get("MOSAIC") in {"TRUE", "1", "YES"} or info.get("MOSAIC_STATUS") in {"MOSAIC", "TRUE", "1", "YES"}:
        return VariantScope.MOSAIC_OUT_OF_SCOPE, OutOfScopeReasonCode.EXPLICIT_MOSAIC, "The supplied INFO fields explicitly identify a mosaic record, which is retained outside scope."
    if alternate.startswith("<") and alternate.endswith(">"):
        token = alternate[1:-1].upper()
        if token in {"STR", "REPEAT", "EXPANSION"}:
            return VariantScope.REPEAT_OUT_OF_SCOPE, OutOfScopeReasonCode.EXPLICIT_REPEAT, "The supplied symbolic allele explicitly identifies a repeat/expansion record, which is retained outside scope."
        if token in {"CNV", "CN0", "CN1", "CN2", "CN3", "CN4", "DEL", "DUP"} or svtype in {"CNV", "DEL", "DUP"}:
            return VariantScope.COPY_NUMBER_OUT_OF_SCOPE, OutOfScopeReasonCode.COPY_NUMBER_VARIANT, "The supplied symbolic allele or SVTYPE explicitly identifies a copy-number record, which is retained out of scope."
        if token in {"BND", "TRA", "INV", "INS", "SV"} or svtype:
            return VariantScope.STRUCTURAL_VARIANT_OUT_OF_SCOPE, OutOfScopeReasonCode.STRUCTURAL_VARIANT, "The supplied symbolic allele or SVTYPE explicitly identifies a structural variant, which is retained outside scope."
        return VariantScope.SYMBOLIC_OUT_OF_SCOPE, OutOfScopeReasonCode.SYMBOLIC_ALLELE, "The supplied symbolic allele is unsupported by the bounded SNV/small-indel parser and is retained without a more specific inference."
    if alternate == "*" or "[" in alternate or "]" in alternate or svtype:
        return VariantScope.STRUCTURAL_VARIANT_OUT_OF_SCOPE, OutOfScopeReasonCode.STRUCTURAL_VARIANT, "The supplied breakend, spanning-deletion or explicit SVTYPE record is retained outside the bounded SNV/small-indel scope."
    if len(reference) == 1 and len(alternate) == 1:
        return VariantScope.SNV, None, None
    if max(len(reference), len(alternate)) <= 50:
        return VariantScope.SMALL_INDEL, None, None
    return VariantScope.LARGE_INDEL_OUT_OF_SCOPE, OutOfScopeReasonCode.LARGE_INDEL, "The supplied allele length exceeds the explicit 50-base small-indel boundary and is retained as an oversized indel."


def _package_verification_state(value: Any, *, has_claim: bool, warnings: list[str], field: str) -> VerificationState:
    if value is None:
        return VerificationState.SUPPLIED_BUT_UNVERIFIED if has_claim else VerificationState.NOT_SUPPLIED
    normalized = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"not_applicable", "n/a", "na"}:
        return VerificationState.NOT_APPLICABLE
    if normalized in {"not_supplied", "missing", "none"} and not has_claim:
        return VerificationState.NOT_SUPPLIED
    if normalized not in {"supplied_but_unverified", "unverified"}:
        warnings.append(f"{field} was package-supplied and cannot promote trust; it remains supplied_but_unverified.")
    return VerificationState.SUPPLIED_BUT_UNVERIFIED


def _report_warnings(values: tuple[str, ...], source_file: str) -> list[GatewayIssue]:
    return [_issue("lab_report_warning", value, source_file, GatewayIssueSeverity.WARNING) for value in values]


def _safe_text(value: Any, source_file: str, field: str, warnings: list[str]) -> str | None:
    text = _text(value)
    safe, codes = redact_gateway_text(text, f"{source_file}.{field}")
    if codes:
        warnings.append(f"{field} contained a direct identifier and was redacted before persistence.")
    return safe


def _safe_text_list(value: Any, source_file: str, field: str) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for index, item in enumerate(value):
        safe, _ = redact_gateway_text(_text(item), f"{source_file}.{field}[{index}]")
        if safe:
            cleaned.append(safe)
    return cleaned


def _redacted_text(value: Any, source_file: str, field: str) -> str | None:
    safe, _ = redact_gateway_text(_text(value), f"{source_file}.{field}")
    return safe


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return bounded_excerpt(str(value), max_chars=4000)
    return None


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 1 else None


def _issue(code: str, message: str, path: str, severity: GatewayIssueSeverity = GatewayIssueSeverity.ERROR) -> GatewayIssue:
    return GatewayIssue(code=code, severity=severity, message=message, path=path)


def _record_issue(code: str, message: str, path: str, line_number: int, record_id: str | None = None) -> GatewayIssue:
    return GatewayIssue(code=code, severity=GatewayIssueSeverity.ERROR, message=f"Line {line_number}: {message}", path=path, record_id=record_id)


def _empty_vcf(source_file: str, issue: GatewayIssue) -> VCFParseResult:
    return VCFParseResult(source_file=source_file, issues=(issue,), record_count=0, in_scope_record_count=0, out_of_scope_record_count=0, multiallelic_source_record_count=0)
