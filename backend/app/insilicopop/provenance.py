from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


ProvenanceSeverity = Literal["info", "warning", "high", "critical"]


class Provenance(BaseModel):
    source_file: str = "not_provided"
    source_section: str = "unknown"
    parser_name: str = "unknown"
    auditor_name: str = "unknown"
    field_or_column: str | None = None
    row_index: int | None = None
    line_number: int | None = None
    column_name: str | None = None
    evidence_value: Any = None
    evidence_snippet: str | None = None
    table_shape: list[int] | None = None
    extraction_confidence: float | None = None
    provenance_id: str | None = None
    rule_id: str
    rule_description: str
    severity: ProvenanceSeverity = "info"


def make_provenance(
    *,
    source_file: str | None,
    source_section: str,
    parser_name: str,
    auditor_name: str,
    field_or_column: str | None,
    row_index: int | None = None,
    line_number: int | None = None,
    column_name: str | None = None,
    evidence_value: Any,
    evidence_snippet: str | None = None,
    table_shape: list[int] | None = None,
    extraction_confidence: float | None = None,
    provenance_id: str | None = None,
    rule_id: str,
    rule_description: str,
    severity: ProvenanceSeverity,
) -> Provenance:
    return Provenance(
        source_file=source_file or "not_provided",
        source_section=source_section,
        parser_name=parser_name,
        auditor_name=auditor_name,
        field_or_column=field_or_column,
        row_index=row_index,
        line_number=line_number,
        column_name=column_name or field_or_column,
        evidence_value=evidence_value,
        evidence_snippet=evidence_snippet,
        table_shape=table_shape,
        extraction_confidence=extraction_confidence,
        provenance_id=provenance_id,
        rule_id=rule_id,
        rule_description=rule_description,
        severity=severity,
    )


def source_file(table: Any, fallback: str = "not_provided") -> str:
    if table is None:
        return fallback
    metadata = getattr(table, "metadata", {}) or {}
    return str(metadata.get("source_file") or fallback)


def compact_row_provenance_id(prefix: str, row: dict[str, Any], fallback_index: int | None = None) -> str:
    sample = row.get("sample_id") or row.get("IID") or row.get("iid")
    if sample not in (None, ""):
        safe = "".join(ch if str(ch).isalnum() else "_" for ch in str(sample)).strip("_")
        return f"prov_{prefix}_sample_{safe}"
    index = row.get("row_index", fallback_index)
    try:
        numeric = int(index)
    except (TypeError, ValueError):
        return f"prov_{prefix}_row_unknown"
    return f"prov_{prefix}_row_{numeric:03d}"
