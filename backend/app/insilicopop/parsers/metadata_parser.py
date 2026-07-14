from __future__ import annotations

from app.insilicopop.parsers.common import parse_delimited_table
from app.schemas.insilicopop import ParsedTable


def parse_metadata(source: bytes | str, source_file: str | None = None) -> ParsedTable:
    return parse_delimited_table(source, "metadata", source_file)


def detect_sample_id_column(table: ParsedTable) -> str | None:
    candidates = ["sample_id", "sample", "iid", "id", "individual_id"]
    return _first_matching_column(table.columns, candidates)


def detect_population_column(table: ParsedTable) -> str | None:
    candidates = ["population", "pop", "community", "group", "caste", "tribe", "ethnicity", "relatedness_group"]
    return _first_matching_column(table.columns, candidates)


def detect_language_columns(table: ParsedTable) -> list[str]:
    return [column for column in table.columns if "language" in column.lower()]


def detect_geography_columns(table: ParsedTable) -> list[str]:
    markers = ["region", "state", "district", "geography", "location"]
    return [column for column in table.columns if any(marker in column.lower() for marker in markers)]


def _first_matching_column(columns: list[str], candidates: list[str]) -> str | None:
    lowered = {column.lower(): column for column in columns}
    for candidate in candidates:
        if candidate in lowered:
            return lowered[candidate]
    return None
