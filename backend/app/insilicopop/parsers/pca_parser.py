from app.insilicopop.parsers.common import parse_delimited_table


def parse_pca(source: bytes | str, source_file: str | None = None):
    return parse_delimited_table(source, "pca", source_file)
