from __future__ import annotations

from app.insilicopop.provenance import make_provenance, source_file
from app.schemas.insilicopop import AuditFinding, MetadataAudit, ParsedTable


class PCAAuditor:
    def run(self, table: ParsedTable | None, metadata: MetadataAudit | None) -> dict[str, object]:
        findings: list[AuditFinding] = []
        summary: dict[str, object] = {
            "parsed_pc_columns": [],
            "eigenvalues": [],
            "variance_explained_summary": {},
            "outlier_samples": [],
            "population_labels": [],
            "population_separation_hint": "not_assessed",
            "ld_pruning_documented": "unknown",
            "relatedness_removal_documented": "unknown",
            "warnings": [],
        }
        if table is None:
            return {"summary": summary, "findings": findings}

        columns = {column.lower(): column for column in table.columns}
        src = source_file(table, "pca")
        summary["parsed_pc_columns"] = [
            column for column in table.columns if column.lower().startswith("pc") and "variance" not in column.lower()
        ]
        summary["eigenvalues"] = table.metadata.get("eigenvalues", [])
        if not summary["eigenvalues"]:
            eigen_col = columns.get("eigenvalue")
            if eigen_col:
                summary["eigenvalues"] = [row.get(eigen_col) for row in table.rows if row.get(eigen_col) not in (None, "")]
        if summary["eigenvalues"] and not summary["variance_explained_summary"]:
            eigenvalues = [float(value) for value in summary["eigenvalues"] if _is_number(value)]
            total = sum(eigenvalues)
            if total:
                summary["variance_explained_summary"] = {
                    f"PC{index}": round(value / total, 6) for index, value in enumerate(eigenvalues[:10], start=1)
                }
        pop_col = columns.get("population") or columns.get("pop")
        if pop_col:
            summary["population_labels"] = sorted({str(row.get(pop_col)) for row in table.rows if row.get(pop_col) not in (None, "")})
        summary["population_separation_hint"] = "population column present" if "population" in columns else "population column missing"

        ld_from_metadata = table.metadata.get("ld_pruning_documented")
        if ld_from_metadata is True:
            summary["ld_pruning_documented"] = True
        if "relatedness_removed" not in columns and "relatedness" not in columns and table.metadata.get("relatedness_removal_documented") is not True:
            relatedness_missing = True
        else:
            relatedness_missing = False

        if "ld_pruned" not in columns and "ld_pruning" not in columns and ld_from_metadata is not True:
            finding = AuditFinding(
                code="pca_ld_pruning_not_documented",
                severity="high",
                message="PCA input does not document LD pruning status.",
                provenance=make_provenance(
                    source_file=src,
                    source_section="PCA columns",
                    parser_name="pca_parser",
                    auditor_name="PCAAuditor",
                    field_or_column=None,
                    evidence_value=table.columns,
                    rule_id="PCA_LD_PRUNING_UNKNOWN",
                    rule_description="PCA should document LD pruning because LD can distort axes.",
                    severity="high",
                ),
            )
            findings.append(finding)
            summary["warnings"].append(finding.message)
        else:
            summary["ld_pruning_documented"] = True

        if relatedness_missing:
            finding = AuditFinding(
                code="pca_relatedness_removal_not_documented",
                severity="warning",
                message="PCA input does not document relatedness removal.",
                provenance=make_provenance(
                    source_file=src,
                    source_section="PCA columns",
                    parser_name="pca_parser",
                    auditor_name="PCAAuditor",
                    field_or_column=None,
                    evidence_value=table.columns,
                    rule_id="PCA_RELATEDNESS_UNKNOWN",
                    rule_description="Relatedness can inflate fine-scale PCA clustering in endogamous datasets.",
                    severity="warning",
                ),
            )
            findings.append(finding)
            summary["warnings"].append(finding.message)
        else:
            summary["relatedness_removal_documented"] = True

        for key, column in columns.items():
            if ((key.startswith("pc") and "variance" in key) or key == "explained_variance") and table.rows:
                summary["variance_explained_summary"][column] = table.rows[0].get(column)

        outlier_col = columns.get("outlier") or columns.get("is_outlier")
        sample_col = columns.get("sample_id") or columns.get("sample")
        if outlier_col and sample_col:
            summary["outlier_samples"] = [
                row.get(sample_col)
                for row in table.rows
                if str(row.get(outlier_col, "")).lower() in {"true", "1", "yes", "outlier"}
            ]
            if summary["outlier_samples"]:
                findings.append(
                    AuditFinding(
                        code="pca_outliers_detected",
                        severity="warning",
                        message="PCA outlier samples were flagged and retained for downstream review.",
                        details={"sample_ids": summary["outlier_samples"]},
                        provenance=make_provenance(
                            source_file=src,
                            source_section="PCA rows",
                            parser_name="pca_parser",
                            auditor_name="PCAAuditor",
                            field_or_column=outlier_col,
                            evidence_value=summary["outlier_samples"],
                            rule_id="PCA_OUTLIERS_RETAIN",
                            rule_description="Outliers can drive apparent structure and should be retained in memory.",
                            severity="warning",
                        ),
                    )
                )

        if metadata and metadata.sample_counts and any(count < 5 for count in metadata.sample_counts.values()):
            findings.append(
                AuditFinding(
                    code="pca_tiny_group_interpretation_risk",
                    severity="warning",
                    message="PCA interpretation is fragile for groups with very small sample sizes.",
                    provenance=make_provenance(
                        source_file=src,
                        source_section="metadata sample counts",
                        parser_name="metadata_parser",
                        auditor_name="PCAAuditor",
                        field_or_column=metadata.population_column,
                        evidence_value=metadata.sample_counts,
                        rule_id="PCA_TINY_GROUP_RISK",
                        rule_description="Small groups can create unstable visual cluster interpretations.",
                        severity="warning",
                    ),
                )
            )

        findings.append(
            AuditFinding(
                code="pca_india_endogamy_context",
                severity="info",
                message="Do not interpret PCA clusters purely by geography or language without endogamy/community context.",
                provenance=make_provenance(
                    source_file=src,
                    source_section="PCA interpretation",
                    parser_name="pca_parser",
                    auditor_name="PCAAuditor",
                    field_or_column="population",
                    evidence_value=summary["population_separation_hint"],
                    rule_id="PCA_ENDOGAMY_CONTEXT",
                    rule_description="Indian PCA interpretation needs fine-scale community and endogamy context.",
                    severity="info",
                ),
            )
        )
        return {"summary": summary, "findings": findings}


def _is_number(value: object) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False
