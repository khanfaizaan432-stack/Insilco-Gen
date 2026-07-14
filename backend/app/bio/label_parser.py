from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import TextIO

import pandas as pd

from app.schemas.project import LabelRecord


REQUIRED_LABEL_COLUMNS = {"sample_id", "label"}


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


def parse_labels(source: str | bytes | Path | TextIO) -> list[LabelRecord]:
    handle, should_close = _open_text(source)
    try:
        frame = pd.read_csv(handle, dtype=str).fillna("")
    finally:
        if should_close:
            handle.close()

    missing_columns = REQUIRED_LABEL_COLUMNS - set(frame.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"labels.csv is missing required column(s): {missing}")

    labels: list[LabelRecord] = []
    for row in frame.to_dict(orient="records"):
        sample_id = str(row["sample_id"]).strip()
        label = str(row["label"]).strip()
        if sample_id:
            labels.append(LabelRecord(sample_id=sample_id, label=label))
    return labels

