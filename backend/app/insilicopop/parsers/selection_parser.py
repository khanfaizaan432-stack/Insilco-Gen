from __future__ import annotations

from app.insilicopop.parsers.common import parse_delimited_table
from app.schemas.insilicopop import ParsedTable


def parse_selection(source: bytes | str, source_file: str | None = None) -> ParsedTable:
    table = parse_delimited_table(source, "selection_scan", source_file)
    filename = (source_file or "").lower()
    columns = {column.lower(): column for column in table.columns}
    if "ihs" in filename or "ihs" in columns:
        table.metadata["source_type"] = "ihs"
    elif "xpehh" in filename or "xp_ehh" in columns or "xp-ehh" in filename:
        table.metadata["source_type"] = "xpehh"
    elif "tajima" in filename or "tajimas_d" in columns or "tajima_d" in columns:
        table.metadata["source_type"] = "tajimas_d"
    else:
        table.metadata["source_type"] = "generic_selection_scan"
    return table
