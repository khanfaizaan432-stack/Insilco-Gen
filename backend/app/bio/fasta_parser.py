from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import TextIO

from Bio import SeqIO

from app.schemas.project import FastaRecord


def _open_text(source: str | bytes | Path | TextIO) -> tuple[TextIO, bool]:
    if isinstance(source, bytes):
        return StringIO(source.decode("utf-8-sig")), True
    if isinstance(source, Path):
        return source.open("r", encoding="utf-8-sig"), True
    if isinstance(source, str):
        path = Path(source)
        if path.exists():
            return path.open("r", encoding="utf-8-sig"), True
        return StringIO(source), True
    return source, False


def parse_fasta(source: str | bytes | Path | TextIO) -> list[FastaRecord]:
    handle, should_close = _open_text(source)
    try:
        records: list[FastaRecord] = []
        for record in SeqIO.parse(handle, "fasta"):
            records.append(
                FastaRecord(
                    sample_id=str(record.id).strip(),
                    description=str(record.description).strip(),
                    sequence=str(record.seq).strip().upper(),
                )
            )
        return records
    finally:
        if should_close:
            handle.close()

