from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd

from app.schemas.insilicopop import ParsedTable


def parse_delimited_table(source: bytes | str | Path, name: str, source_file: str | None = None) -> ParsedTable:
    text = _read_text(source)
    first_line = _first_data_line(text)
    delimiter = "\t" if "\t" in first_line else ","
    frame = pd.read_csv(StringIO(text), sep=delimiter, dtype=str, comment="#").fillna("")
    return table_from_frame(frame, name, source_file, f"{name}_parser", text=text)


def parse_whitespace_table(source: bytes | str | Path, name: str, source_file: str | None = None) -> ParsedTable:
    text = _read_text(source)
    frame = pd.read_csv(StringIO(text), sep=r"\s+", dtype=str, comment="#", engine="python").fillna("")
    return table_from_frame(frame, name, source_file, f"{name}_parser", text=text)


def parse_key_value_text(source: bytes | str | Path, name: str, source_file: str | None = None) -> ParsedTable:
    text = _read_text(source)
    rows: list[dict[str, Any]] = []
    logical_index = 0
    table_source = source_file or name
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" in stripped:
            key, value = stripped.split(":", 1)
        elif "=" in stripped:
            key, value = stripped.split("=", 1)
        else:
            key, value = "line", stripped
        rows.append(
            _with_row_provenance(
                {"metric": key.strip(), "value": _clean(value)},
                name=name,
                parser_name=f"{name}_parser",
                source_file=table_source,
                row_index=logical_index,
                line_number=logical_index + 1,
                evidence_snippet=stripped,
            )
        )
        logical_index += 1
    return ParsedTable(
        name=name,
        columns=["metric", "value", "row_index", "source_file"],
        rows=rows,
        metadata={
            "raw_text": text,
            "source_file": table_source,
            "parser_name": f"{name}_parser",
            "table_shape": [len(rows), 2],
        },
    )


def table_from_rows(
    rows: list[dict[str, Any]],
    name: str,
    source_file: str | None,
    parser_name: str,
    *,
    columns: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ParsedTable:
    table_source = source_file or name
    base_columns = columns or _columns_from_rows(rows)
    enriched = [
        _with_row_provenance(
            row,
            name=name,
            parser_name=parser_name,
            source_file=table_source,
            row_index=index,
            line_number=row.get("line_number") if isinstance(row.get("line_number"), int) else index + 1,
            evidence_snippet=_snippet(row, base_columns),
        )
        for index, row in enumerate(rows)
    ]
    all_columns = _columns_from_rows(enriched, preferred=base_columns + ["row_index", "source_file"])
    meta = {
        "source_file": table_source,
        "parser_name": parser_name,
        "table_shape": [len(enriched), len(base_columns)],
    }
    meta.update(metadata or {})
    return ParsedTable(name=name, columns=all_columns, rows=enriched, metadata=meta)


def table_from_frame(
    frame: pd.DataFrame,
    name: str,
    source_file: str | None,
    parser_name: str,
    *,
    text: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ParsedTable:
    columns = [str(column) for column in frame.columns]
    rows = [{str(key): _clean(value) for key, value in row.items()} for row in frame.to_dict("records")]
    table = table_from_rows(rows, name, source_file, parser_name, columns=columns, metadata=metadata)
    if text is not None:
        table.metadata["raw_text"] = text
    return table


def _read_text(source: bytes | str | Path) -> str:
    if isinstance(source, bytes):
        return source.decode("utf-8-sig")
    if isinstance(source, Path):
        return source.read_text(encoding="utf-8-sig")
    if "\n" not in str(source) and "\r" not in str(source):
        path = Path(source)
        if path.exists():
            return path.read_text(encoding="utf-8-sig")
    return str(source)


def _first_data_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return ""


def _with_row_provenance(
    row: dict[str, Any],
    *,
    name: str,
    parser_name: str,
    source_file: str,
    row_index: int,
    line_number: int | None,
    evidence_snippet: str,
) -> dict[str, Any]:
    enriched = dict(row)
    enriched.setdefault("row_index", row_index)
    enriched.setdefault("source_file", source_file)
    if line_number is not None:
        enriched.setdefault("line_number", line_number)
    enriched.setdefault(
        "provenance_id",
        f"prov_{name}_row_{row_index:03d}",
    )
    enriched.setdefault(
        "_provenance",
        {
            "source_file": source_file,
            "row_index": row_index,
            "line_number": line_number,
            "parser_name": parser_name,
            "evidence_snippet": evidence_snippet,
            "extraction_confidence": 1.0,
            "provenance_id": enriched["provenance_id"],
        },
    )
    return enriched


def _snippet(row: dict[str, Any], columns: list[str]) -> str:
    values = [str(row.get(column, "")) for column in columns[:8]]
    return " ".join(value for value in values if value != "")


def _columns_from_rows(rows: list[dict[str, Any]], preferred: list[str] | None = None) -> list[str]:
    columns: list[str] = []
    for column in preferred or []:
        if column not in columns:
            columns.append(column)
    for row in rows:
        for column in row:
            if column.startswith("_"):
                continue
            if column not in columns:
                columns.append(column)
    return columns


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        return _maybe_number(stripped)
    return value


def _maybe_number(value: str) -> Any:
    if value == "":
        return ""
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value
