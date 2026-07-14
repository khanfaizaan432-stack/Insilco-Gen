from __future__ import annotations

from app.bio.validators import validate_dataset
from app.schemas.project import DataHealthReport, FastaRecord, LabelRecord


class DataCopAgent:
    name = "DataCopAgent"

    def run(self, records: list[FastaRecord], labels: list[LabelRecord]) -> DataHealthReport:
        return validate_dataset(records, labels)

