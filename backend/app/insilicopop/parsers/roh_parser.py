from __future__ import annotations

from collections import defaultdict

from app.insilicopop.parsers.common import parse_delimited_table, parse_whitespace_table
from app.schemas.insilicopop import ParsedTable


def parse_roh(source: bytes | str, source_file: str | None = None) -> ParsedTable:
    filename = (source_file or "").lower()
    if filename.endswith(".hom") or filename.endswith(".hom.indiv"):
        return parse_plink_hom(source, source_file)
    return parse_delimited_table(source, "roh", source_file)


def parse_plink_hom(source: bytes | str, source_file: str | None = None) -> ParsedTable:
    table = parse_whitespace_table(source, "roh", source_file)
    table.metadata["source_type"] = "plink_hom"
    columns = {column.lower(): column for column in table.columns}
    iid_col = columns.get("iid") or columns.get("sample_id") or columns.get("sample")
    kb_col = columns.get("kb")
    per_sample: dict[str, dict[str, float | int]] = defaultdict(lambda: {"total_roh_length_mb": 0.0, "roh_segment_count": 0, "max_roh_segment_mb": 0.0})
    if iid_col and kb_col:
        for row in table.rows:
            try:
                mb = float(row.get(kb_col, 0)) / 1000.0
            except (TypeError, ValueError):
                continue
            sample_id = str(row.get(iid_col))
            per_sample[sample_id]["total_roh_length_mb"] = round(float(per_sample[sample_id]["total_roh_length_mb"]) + mb, 3)
            per_sample[sample_id]["roh_segment_count"] = int(per_sample[sample_id]["roh_segment_count"]) + 1
            per_sample[sample_id]["max_roh_segment_mb"] = max(float(per_sample[sample_id]["max_roh_segment_mb"]), round(mb, 3))
            row["sample_id"] = sample_id
            row["roh_segment_mb"] = round(mb, 3)
    for column in ["sample_id", "roh_segment_mb"]:
        if column not in table.columns:
            table.columns.append(column)
    table.metadata["roh_summary_by_sample"] = dict(per_sample)
    return table
