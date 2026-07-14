from __future__ import annotations

from typing import Any


def as_rows(raw_output: Any) -> list[dict[str, Any]]:
    if isinstance(raw_output, dict):
        if isinstance(raw_output.get("rows"), list):
            return [row for row in raw_output["rows"] if isinstance(row, dict)]
        return [raw_output]
    if isinstance(raw_output, list):
        return [row for row in raw_output if isinstance(row, dict)]
    return []


def as_text(raw_output: Any) -> str:
    if isinstance(raw_output, str):
        return raw_output
    return str(raw_output)


def find_column(row: dict[str, Any], candidates: list[str]) -> str | None:
    lowered = {str(key).lower(): str(key) for key in row}
    for candidate in candidates:
        if candidate in lowered:
            return lowered[candidate]
    return None

