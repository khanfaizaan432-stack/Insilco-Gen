from __future__ import annotations

from collections import Counter, defaultdict

from app.schemas.project import DataHealthReport, FastaRecord, LabelRecord, ValidationFinding


def validate_dataset(records: list[FastaRecord], labels: list[LabelRecord]) -> DataHealthReport:
    findings: list[ValidationFinding] = []
    fasta_ids = [record.sample_id for record in records]
    label_ids = [label.sample_id for label in labels]
    id_counts = Counter(fasta_ids)
    label_by_sample = _labels_by_sample(labels)

    duplicate_ids = sorted(sample_id for sample_id, count in id_counts.items() if count > 1)
    if duplicate_ids:
        findings.append(
            ValidationFinding(
                code="duplicate_fasta_ids",
                severity="error",
                message="Duplicate FASTA identifiers were found.",
                details={"sample_ids": duplicate_ids},
            )
        )

    labels_without_fasta = sorted(set(label_ids) - set(fasta_ids))
    if labels_without_fasta:
        findings.append(
            ValidationFinding(
                code="label_sample_id_not_in_fasta",
                severity="error",
                message="Some labels reference sample_id values that do not exist in the FASTA file.",
                details={"sample_ids": labels_without_fasta},
            )
        )

    missing_labels = sorted(set(fasta_ids) - set(label_ids))
    if missing_labels:
        findings.append(
            ValidationFinding(
                code="missing_labels",
                severity="error",
                message="Some FASTA records do not have labels.",
                details={"sample_ids": missing_labels},
            )
        )

    duplicate_label_samples = {
        sample_id: sorted(values)
        for sample_id, values in label_by_sample.items()
        if len(values) > 1
    }
    if duplicate_label_samples:
        findings.append(
            ValidationFinding(
                code="duplicate_or_conflicting_sample_labels",
                severity="error",
                message="Some sample_id values have multiple label rows.",
                details={"labels_by_sample": duplicate_label_samples},
            )
        )

    sequences_to_ids = _sequence_groups(records)
    duplicate_sequences = {
        sequence: sample_ids
        for sequence, sample_ids in sequences_to_ids.items()
        if len(sample_ids) > 1
    }
    if duplicate_sequences:
        findings.append(
            ValidationFinding(
                code="duplicate_biological_sequences",
                severity="warning",
                message="Identical biological sequences occur under multiple FASTA identifiers.",
                details={"sequence_groups": duplicate_sequences},
            )
        )

    conflicting_sequence_labels = _conflicting_labels_for_identical_sequences(
        duplicate_sequences, label_by_sample
    )
    if conflicting_sequence_labels:
        findings.append(
            ValidationFinding(
                code="conflicting_labels_for_identical_sequences",
                severity="error",
                message="Identical biological sequences have conflicting labels.",
                details={"conflicts": conflicting_sequence_labels},
            )
        )

    class_balance = dict(sorted(Counter(label.label for label in labels if label.label).items()))
    findings.append(_class_balance_finding(class_balance))

    return DataHealthReport(
        total_fasta_records=len(records),
        total_labels=len(labels),
        unique_fasta_ids=len(set(fasta_ids)),
        unique_sequences=len(set(record.sequence for record in records)),
        class_balance=class_balance,
        findings=findings,
        passed=not any(finding.severity == "error" for finding in findings),
    )


def _labels_by_sample(labels: list[LabelRecord]) -> dict[str, set[str]]:
    label_by_sample: dict[str, set[str]] = defaultdict(set)
    for label in labels:
        label_by_sample[label.sample_id].add(label.label)
    return label_by_sample


def _sequence_groups(records: list[FastaRecord]) -> dict[str, list[str]]:
    sequences_to_ids: dict[str, list[str]] = defaultdict(list)
    for record in records:
        sequences_to_ids[record.sequence].append(record.sample_id)
    return dict(sequences_to_ids)


def _conflicting_labels_for_identical_sequences(
    duplicate_sequences: dict[str, list[str]],
    label_by_sample: dict[str, set[str]],
) -> list[dict[str, object]]:
    conflicts: list[dict[str, object]] = []
    for sequence, sample_ids in duplicate_sequences.items():
        observed = {
            sample_id: sorted(label_by_sample.get(sample_id, set()))
            for sample_id in sample_ids
            if label_by_sample.get(sample_id)
        }
        labels = {label for sample_labels in observed.values() for label in sample_labels}
        if len(labels) > 1:
            conflicts.append(
                {
                    "sequence": sequence,
                    "sample_ids": sample_ids,
                    "labels_by_sample": observed,
                }
            )
    return conflicts


def _class_balance_finding(class_balance: dict[str, int]) -> ValidationFinding:
    if not class_balance:
        return ValidationFinding(
            code="class_balance",
            severity="warning",
            message="No non-empty labels were available for class balance analysis.",
            details={"class_balance": class_balance},
        )

    counts = list(class_balance.values())
    minority = min(counts)
    majority = max(counts)
    ratio = round(majority / minority, 3) if minority else None
    severity = "warning" if ratio is not None and ratio >= 3 else "info"
    return ValidationFinding(
        code="class_balance",
        severity=severity,
        message="Class balance was computed for the supplied labels.",
        details={"class_balance": class_balance, "majority_minority_ratio": ratio},
    )

