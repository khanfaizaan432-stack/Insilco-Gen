from __future__ import annotations

import re
from typing import Any

from app.insilicopop.parsers.common import _read_text, table_from_rows
from app.schemas.insilicopop import ParsedTable


def parse_evec(source: bytes | str, source_file: str | None = None) -> ParsedTable:
    text = _read_text(source)
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) < 3:
            continue
        row: dict[str, Any] = {"sample_id": parts[0], "line_number": line_number, "provenance_id": f"prov_pca_evec_{parts[0]}"}
        pc_values = parts[1:-1]
        for index, value in enumerate(pc_values, start=1):
            row[f"PC{index}"] = float(value)
        row["population"] = parts[-1]
        rows.append(row)
    pc_columns = [f"PC{i}" for i in range(1, max((len(row) - 3 for row in rows), default=0) + 1)]
    return table_from_rows(
        rows,
        "pca",
        source_file,
        "smartpca_evec_parser",
        columns=["sample_id", *pc_columns, "population"],
        metadata={"source_type": "smartpca_evec", "population_labels_present": bool(rows and rows[0].get("population"))},
    )


def parse_eval(source: bytes | str, source_file: str | None = None) -> ParsedTable:
    text = _read_text(source)
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for value in stripped.split():
            rows.append({"component": len(rows) + 1, "eigenvalue": float(value), "line_number": line_number})
    total = sum(float(row["eigenvalue"]) for row in rows)
    for row in rows:
        row["variance_explained"] = round(float(row["eigenvalue"]) / total, 6) if total else 0
    return table_from_rows(
        rows,
        "pca",
        source_file,
        "smartpca_eval_parser",
        columns=["component", "eigenvalue", "variance_explained"],
        metadata={"source_type": "smartpca_eval", "eigenvalues": [row["eigenvalue"] for row in rows]},
    )


def parse_smartpca_log(source: bytes | str, source_file: str | None = None) -> ParsedTable:
    text = _read_text(source)
    lowered = text.lower()
    rows: list[dict[str, Any]] = []
    hints = {
        "ld_pruning_documented": bool(re.search(r"ld[-\s_]?prun|prune|indep-pairwise", lowered)),
        "relatedness_removal_documented": bool(re.search(r"related|king|pi_hat|remove.*relative", lowered)),
    }
    for key, value in hints.items():
        rows.append({"metric": key, "value": value})
    return table_from_rows(
        rows,
        "pca",
        source_file,
        "smartpca_log_parser",
        columns=["metric", "value"],
        metadata={"source_type": "smartpca_log", "raw_text": text, **hints},
    )
