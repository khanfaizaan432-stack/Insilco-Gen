from __future__ import annotations

from app.insilicopop.parsers.common import parse_delimited_table


def parse_fst(source: bytes | str, source_file: str | None = None):
    table = parse_delimited_table(source, "fst", source_file)
    columns = {column.lower(): column for column in table.columns}
    if {"chrom", "bin_start", "bin_end"} & set(columns):
        table.metadata["source_type"] = "windowed_fst"
    elif (columns.get("pop1") or columns.get("population1")) and (columns.get("pop2") or columns.get("population2")):
        table.metadata["source_type"] = "fst_long"
    elif table.columns:
        table.metadata["source_type"] = "fst_matrix"
    return table


def parse_windowed_fst(source: bytes | str, source_file: str | None = None):
    table = parse_delimited_table(source, "fst", source_file)
    table.metadata["source_type"] = "windowed_fst"
    return table
