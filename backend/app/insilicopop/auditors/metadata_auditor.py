from __future__ import annotations

from collections import Counter
from typing import Any

from app.insilicopop.parsers.metadata_parser import (
    detect_geography_columns,
    detect_language_columns,
    detect_population_column,
    detect_sample_id_column,
)
from app.insilicopop.provenance import make_provenance, source_file
from app.schemas.insilicopop import AuditFinding, MetadataAudit, ParsedTable


BROAD_INDIAN_LABELS = {
    "north indian",
    "south indian",
    "east indian",
    "west indian",
    "tribal",
    "caste",
    "urban",
    "rural",
    "indian",
    "general population",
}


class MetadataAuditor:
    def run(self, table: ParsedTable | None) -> MetadataAudit:
        if table is None:
            return MetadataAudit(
                findings=[
                    AuditFinding(
                        code="metadata_missing",
                        severity="warning",
                        message="No metadata file was provided; population-level interpretation is limited.",
                        provenance=make_provenance(
                            source_file=None,
                            source_section="metadata",
                            parser_name="metadata_parser",
                            auditor_name="MetadataAuditor",
                            field_or_column=None,
                            evidence_value="metadata_file missing",
                            rule_id="METADATA_MISSING",
                            rule_description="Population-genetics audits require sample metadata for reliable interpretation.",
                            severity="warning",
                        ),
                    )
                ]
            )

        sample_col = detect_sample_id_column(table)
        pop_col = detect_population_column(table)
        findings: list[AuditFinding] = []
        src = source_file(table, "metadata")

        if sample_col is None:
            findings.append(
                AuditFinding(
                    code="sample_id_column_missing",
                    severity="error",
                    message="Metadata does not contain a recognizable sample_id column.",
                    provenance=make_provenance(
                        source_file=src,
                        source_section="metadata columns",
                        parser_name="metadata_parser",
                        auditor_name="MetadataAuditor",
                        field_or_column=None,
                        evidence_value=table.columns,
                        rule_id="SAMPLE_ID_COLUMN_MISSING",
                        rule_description="Metadata should identify each sample with a stable sample ID column.",
                        severity="critical",
                    ),
                )
            )
            duplicates: list[str] = []
        else:
            sample_ids = [str(row.get(sample_col, "")).strip() for row in table.rows]
            duplicates = sorted(sample for sample, count in Counter(sample_ids).items() if sample and count > 1)
            if duplicates:
                findings.append(
                    AuditFinding(
                        code="duplicate_sample_ids",
                        severity="error",
                        message="Metadata contains duplicate sample IDs.",
                        details={"sample_ids": duplicates},
                        provenance=make_provenance(
                            source_file=src,
                            source_section="metadata rows",
                            parser_name="metadata_parser",
                            auditor_name="MetadataAuditor",
                            field_or_column=sample_col,
                            evidence_value=duplicates,
                            rule_id="DUPLICATE_SAMPLE_IDS",
                            rule_description="Duplicate sample IDs can corrupt per-sample population-genetics interpretation.",
                            severity="critical",
                        ),
                    )
                )

        sample_counts: dict[str, int] = {}
        missing = 0
        tiny: dict[str, int] = {}
        severe_imbalance = False
        broad: list[str] = []
        recommended_fixes: list[str] = []
        if pop_col is None:
            findings.append(
                AuditFinding(
                    code="population_column_missing",
                    severity="error",
                    message="Metadata does not contain a recognizable population/community/group column.",
                    provenance=make_provenance(
                        source_file=src,
                        source_section="metadata columns",
                        parser_name="metadata_parser",
                        auditor_name="MetadataAuditor",
                        field_or_column=None,
                        evidence_value=table.columns,
                        rule_id="POPULATION_COLUMN_MISSING",
                        rule_description="Population labels are required for FST, PCA, ADMIXTURE, and ROH interpretation.",
                        severity="critical",
                    ),
                )
            )
            recommended_fixes.append("Add a population/community/endogamous group column.")
        else:
            populations = [str(row.get(pop_col, "")).strip() for row in table.rows]
            missing = sum(1 for population in populations if not population)
            if missing:
                findings.append(
                    AuditFinding(
                        code="missing_population_labels",
                        severity="error",
                        message="Some samples are missing population/community labels.",
                        details={"missing_count": missing},
                        provenance=make_provenance(
                            source_file=src,
                            source_section="metadata rows",
                            parser_name="metadata_parser",
                            auditor_name="MetadataAuditor",
                            field_or_column=pop_col,
                            evidence_value=f"{missing} missing labels",
                            rule_id="MISSING_POPULATION_LABELS",
                            rule_description="Missing population labels reduce reliability of stratified analyses.",
                            severity="critical",
                        ),
                    )
                )
                recommended_fixes.append("Fill missing population/community labels before interpreting stratified results.")
            sample_counts = dict(sorted(Counter(pop for pop in populations if pop).items()))
            tiny = {pop: count for pop, count in sample_counts.items() if count < 5}
            if tiny:
                findings.append(
                    AuditFinding(
                        code="tiny_population_groups",
                        severity="warning",
                        message="Some population groups have fewer than five samples.",
                        details={"sample_counts": tiny},
                        provenance=make_provenance(
                            source_file=src,
                            source_section="metadata sample counts",
                            parser_name="metadata_parser",
                            auditor_name="MetadataAuditor",
                            field_or_column=pop_col,
                            evidence_value=tiny,
                            rule_id="TINY_POPULATION_GROUPS",
                            rule_description="Tiny population groups make PCA, FST, ADMIXTURE, and ROH summaries unstable.",
                            severity="high",
                        ),
                    )
                )
                recommended_fixes.append("Increase sample size or merge only scientifically justified groups.")
            if sample_counts:
                counts = list(sample_counts.values())
                if max(counts) / max(min(counts), 1) >= 5:
                    severe_imbalance = True
                    findings.append(
                        AuditFinding(
                            code="severe_population_imbalance",
                            severity="warning",
                            message="Population sample sizes are severely imbalanced.",
                            details={"sample_counts": sample_counts},
                            provenance=make_provenance(
                                source_file=src,
                                source_section="metadata sample counts",
                                parser_name="metadata_parser",
                                auditor_name="MetadataAuditor",
                                field_or_column=pop_col,
                                evidence_value=sample_counts,
                                rule_id="SEVERE_POPULATION_IMBALANCE",
                                rule_description="Severe imbalance can distort population comparisons and visual clustering.",
                                severity="high",
                            ),
                        )
                    )
                    recommended_fixes.append("Balance comparison groups or report imbalance caveats.")
            broad = sorted({pop for pop in sample_counts if _is_broad_indian_label(pop)})
            if broad:
                findings.append(
                    AuditFinding(
                        code="broad_indian_population_labels",
                        severity="warning",
                        message="Broad labels can obscure Indian fine-scale endogamous structure.",
                        details={"labels": broad},
                        provenance=make_provenance(
                            source_file=src,
                            source_section="metadata population labels",
                            parser_name="metadata_parser",
                            auditor_name="MetadataAuditor",
                            field_or_column=pop_col,
                            evidence_value=broad,
                            rule_id="BROAD_INDIAN_LABELS",
                            rule_description="Broad geography/language/social labels may be insufficient for Indian fine-scale endogamous structure.",
                            severity="high",
                        ),
                    )
                )
                recommended_fixes.append("Add finer-grained community/endogamous group labels where ethically and scientifically appropriate.")

        return MetadataAudit(
            sample_id_column=sample_col,
            population_column=pop_col,
            language_columns=detect_language_columns(table),
            geography_columns=detect_geography_columns(table),
            sample_counts=sample_counts,
            sample_count=len(table.rows),
            population_count=len(sample_counts),
            samples_per_population=sample_counts,
            missing_population_labels=missing,
            duplicate_sample_ids=duplicates,
            tiny_population_groups=tiny,
            severe_imbalance=severe_imbalance,
            broad_label_warnings=broad,
            recommended_metadata_fixes=recommended_fixes,
            findings=findings,
        )


def _is_broad_indian_label(label: Any) -> bool:
    normalized = str(label).strip().lower()
    return normalized in BROAD_INDIAN_LABELS
