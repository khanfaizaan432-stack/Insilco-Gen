from __future__ import annotations

from typing import Any

from app.insilicopop.parsers.common import parse_whitespace_table, table_from_rows
from app.schemas.insilicopop import ParsedTable


def parse_plink_imiss(source: bytes | str, source_file: str | None = None) -> ParsedTable:
    return _parse_plink_table(source, "plink_imiss", source_file, "individual_missingness")


def parse_plink_lmiss(source: bytes | str, source_file: str | None = None) -> ParsedTable:
    return _parse_plink_table(source, "plink_lmiss", source_file, "variant_missingness")


def parse_plink_het(source: bytes | str, source_file: str | None = None) -> ParsedTable:
    return _parse_plink_table(source, "plink_het", source_file, "heterozygosity")


def parse_plink_hwe(source: bytes | str, source_file: str | None = None) -> ParsedTable:
    return _parse_plink_table(source, "plink_hwe", source_file, "hardy_weinberg")


def parse_plink_genome(source: bytes | str, source_file: str | None = None) -> ParsedTable:
    return _parse_plink_table(source, "plink_genome", source_file, "relatedness")


def parse_plink_prune(source: bytes | str, source_file: str | None = None, kept: bool | None = None) -> ParsedTable:
    text = source.decode("utf-8-sig") if isinstance(source, bytes) else str(source)
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        snp = line.strip()
        if not snp or snp.startswith("#"):
            continue
        rows.append({"SNP": snp, "status": "kept" if kept is not False else "removed"})
    return table_from_rows(
        rows,
        "plink_prune",
        source_file,
        "plink_prune_parser",
        columns=["SNP", "status"],
        metadata={"source_type": "ld_prune", "ld_pruning_documented": True, "variant_count": len(rows)},
    )


def parse_plink_qc_bundle(files: dict[str, bytes | str]) -> dict[str, ParsedTable]:
    parsers = {
        "imiss": parse_plink_imiss,
        "lmiss": parse_plink_lmiss,
        "het": parse_plink_het,
        "hwe": parse_plink_hwe,
        "genome": parse_plink_genome,
        "prune_in": lambda content, filename=None: parse_plink_prune(content, filename, kept=True),
        "prune_out": lambda content, filename=None: parse_plink_prune(content, filename, kept=False),
    }
    parsed: dict[str, ParsedTable] = {}
    for key, content in files.items():
        parser = parsers.get(key)
        if parser:
            parsed[key] = parser(content, key)
    return parsed


def _parse_plink_table(source: bytes | str, name: str, source_file: str | None, source_type: str) -> ParsedTable:
    table = parse_whitespace_table(source, name, source_file)
    table.metadata["source_type"] = source_type
    table.metadata["parser_name"] = f"{name}_parser"
    return table
