from app.insilicopop.parsers.common import parse_delimited_table, parse_key_value_text


def parse_plink_qc(source: bytes | str, source_file: str | None = None):
    text = source.decode("utf-8-sig") if isinstance(source, bytes) else str(source)
    first_line = text.splitlines()[0] if text.splitlines() else ""
    if "," in first_line or "\t" in first_line:
        return parse_delimited_table(source, "plink_qc", source_file)
    return parse_key_value_text(source, "plink_qc", source_file)
