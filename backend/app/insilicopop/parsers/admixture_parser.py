from __future__ import annotations

import re
from typing import Any

from app.insilicopop.parsers.common import _read_text, parse_delimited_table, parse_whitespace_table, table_from_rows
from app.schemas.insilicopop import ParsedTable


def parse_admixture(source: bytes | str, source_file: str | None = None) -> ParsedTable:
    filename = (source_file or "").lower()
    text = _read_text(source)
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if "cv error" in text.lower() or filename.endswith(".cv"):
        return parse_admixture_cv_log(source, source_file)
    if filename.endswith(".q") or _looks_like_q_matrix(first):
        return parse_admixture_q(source, source_file)
    if filename.endswith(".p"):
        return parse_admixture_p_metadata(source, source_file)
    return parse_delimited_table(source, "admixture", source_file)


def parse_admixture_cv_log(source: bytes | str, source_file: str | None = None) -> ParsedTable:
    text = _read_text(source)
    rows: list[dict[str, Any]] = []
    pattern = re.compile(r"CV\s+error\s*\(K\s*=\s*(\d+)\)\s*:\s*([0-9.eE+-]+)", re.IGNORECASE)
    for line_number, line in enumerate(text.splitlines(), start=1):
        match = pattern.search(line)
        if match:
            rows.append(
                {
                    "K": int(match.group(1)),
                    "cv_error": float(match.group(2)),
                    "line_number": line_number,
                    "evidence_value": line.strip(),
                    "provenance_id": f"prov_admix_k{int(match.group(1))}_cv",
                }
            )
    return table_from_rows(
        rows,
        "admixture",
        source_file,
        "admixture_cv_parser",
        columns=["K", "cv_error"],
        metadata={"source_type": "admixture_cv_log", "raw_text": text},
    )


def parse_admixture_q(
    source: bytes | str,
    source_file: str | None = None,
    sample_ids: list[str] | None = None,
) -> ParsedTable:
    text = _read_text(source)
    value_rows: list[list[float]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        value_rows.append([float(value) for value in stripped.split()])
    component_count = max((len(row) for row in value_rows), default=0)
    component_columns = [f"Q{i + 1}" for i in range(component_count)]
    rows: list[dict[str, Any]] = []
    for row_index, values in enumerate(value_rows):
        out = {component_columns[index]: value for index, value in enumerate(values)}
        if sample_ids and row_index < len(sample_ids):
            out["sample_id"] = sample_ids[row_index]
        out["provenance_id"] = f"prov_admix_q_row_{row_index:03d}"
        rows.append(out)
    metadata = {
        "source_type": "admixture_q",
        "q_matrix_shape": [len(rows), len(component_columns)],
        "sample_order_documented": bool(sample_ids),
    }
    return table_from_rows(rows, "admixture", source_file, "admixture_q_parser", columns=(["sample_id"] if sample_ids else []) + component_columns, metadata=metadata)


def parse_admixture_p_metadata(source: bytes | str, source_file: str | None = None) -> ParsedTable:
    table = parse_whitespace_table(source, "admixture", source_file)
    table.metadata.update(
        {
            "source_type": "admixture_p",
            "component_count": len(table.columns),
            "marker_count": len(table.rows),
            "note": "Allele-frequency matrix metadata only; deep allele-frequency audit is not implemented.",
        }
    )
    return table


def _looks_like_q_matrix(first_line: str) -> bool:
    if not first_line:
        return False
    parts = first_line.split()
    if len(parts) < 2:
        return False
    try:
        values = [float(part) for part in parts]
    except ValueError:
        return False
    return all(0 <= value <= 1 for value in values)
