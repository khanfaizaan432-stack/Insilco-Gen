from __future__ import annotations

from collections import defaultdict

from app.insilicopop.provenance import make_provenance, source_file
from app.schemas.insilicopop import AuditFinding, ParsedTable


class ADMIXTUREAuditor:
    def run(self, table: ParsedTable | None) -> dict[str, object]:
        findings: list[AuditFinding] = []
        summary: dict[str, object] = {
            "k_values_tested": [],
            "k_values": [],
            "cv_error_by_k": {},
            "cv_errors": {},
            "best_k_by_cv": None,
            "best_k": None,
            "cv_curve": [],
            "q_matrix_shape": None,
            "high_admixture_samples": [],
            "max_component_per_sample": [],
            "missing_sample_order_warning": None,
            "seed_count_by_k": {},
            "narrow_k_sweep_warning": None,
            "missing_seed_replicates_warning": None,
            "recommended_k_range": "K=2-10",
        }
        if table is None:
            return {"summary": summary, "findings": findings}

        columns = {column.lower(): column for column in table.columns}
        src = source_file(table, "admixture")
        k_col = columns.get("k")
        cv_col = columns.get("cv_error") or columns.get("cverror") or columns.get("cross_validation_error")
        seed_col = columns.get("seed") or columns.get("repeat")

        if k_col:
            k_values = sorted({int(row[k_col]) for row in table.rows if str(row.get(k_col, "")).isdigit()})
            summary["k_values_tested"] = k_values
            summary["k_values"] = k_values
            if k_values and max(k_values) <= 3:
                summary["narrow_k_sweep_warning"] = "K sweep is too narrow for Indian fine-scale structure."
                findings.append(
                    AuditFinding(
                        code="admixture_k_sweep_too_narrow",
                        severity="high",
                        message="ADMIXTURE K sweep is narrow for Indian datasets; consider K=2-10.",
                        details={"observed_k": k_values, "recommended": "K=2-10"},
                        provenance=make_provenance(
                            source_file=src,
                            source_section="ADMIXTURE CV table",
                            parser_name="admixture_parser",
                            auditor_name="ADMIXTUREAuditor",
                            field_or_column=k_col,
                            evidence_value=f"K tested: {k_values}",
                            rule_id="ADMIXTURE_K_SWEEP_TOO_NARROW",
                            rule_description="Indian population structure may require broader K sweep and CV comparison.",
                            severity="high",
                        ),
                    )
                )
            if set(k_values).issubset({2, 3}):
                findings.append(
                    AuditFinding(
                        code="admixture_only_low_k_tested",
                        severity="warning",
                        message="Only low K values were tested; Indian populations may show multicomponent and fine-scale endogamous structure.",
                        provenance=make_provenance(
                            source_file=src,
                            source_section="ADMIXTURE CV table",
                            parser_name="admixture_parser",
                            auditor_name="ADMIXTUREAuditor",
                            field_or_column=k_col,
                            evidence_value=k_values,
                            rule_id="ADMIXTURE_ONLY_LOW_K",
                            rule_description="Low K runs alone can encourage over-simple ancestry narratives.",
                            severity="warning",
                        ),
                    )
                )

        if cv_col:
            cv_errors = {
                int(row[k_col]): float(row[cv_col])
                for row in table.rows
                if k_col and str(row.get(k_col, "")).isdigit() and _is_number(row.get(cv_col))
            }
            summary["cv_error_by_k"] = cv_errors
            summary["cv_errors"] = cv_errors
            summary["cv_curve"] = [{"K": key, "cv_error": value} for key, value in sorted(cv_errors.items())]
            if cv_errors:
                best = min(cv_errors, key=cv_errors.get)
                summary["best_k_by_cv"] = best
                summary["best_k"] = best
        elif table.metadata.get("source_type") != "admixture_q":
            findings.append(
                AuditFinding(
                    code="admixture_cv_errors_missing",
                    severity="warning",
                    message="ADMIXTURE cross-validation errors were not provided.",
                    provenance=make_provenance(
                        source_file=src,
                        source_section="ADMIXTURE columns",
                        parser_name="admixture_parser",
                        auditor_name="ADMIXTUREAuditor",
                        field_or_column=None,
                        evidence_value=table.columns,
                        rule_id="ADMIXTURE_CV_ERRORS_MISSING",
                        rule_description="CV errors are needed to compare K values.",
                        severity="warning",
                    ),
                )
            )

        if seed_col and k_col:
            seeds: dict[int, set[str]] = defaultdict(set)
            for row in table.rows:
                if str(row.get(k_col, "")).isdigit():
                    seeds[int(row[k_col])].add(str(row.get(seed_col, "")))
            summary["seed_count_by_k"] = {k: len(values) for k, values in sorted(seeds.items())}
        if not seed_col or any(count <= 1 for count in summary["seed_count_by_k"].values()):
            summary["missing_seed_replicates_warning"] = "Multiple ADMIXTURE seed replicates are missing or insufficient."
            findings.append(
                AuditFinding(
                    code="admixture_multiple_seeds_not_documented",
                    severity="warning",
                    message="ADMIXTURE multiple seeds/repeats are not documented.",
                    provenance=make_provenance(
                        source_file=src,
                        source_section="ADMIXTURE columns",
                        parser_name="admixture_parser",
                        auditor_name="ADMIXTUREAuditor",
                        field_or_column=seed_col,
                        evidence_value=summary["seed_count_by_k"] or "seed column missing",
                        rule_id="ADMIXTURE_SEED_REPLICATES_MISSING",
                        rule_description="Replicate seeds help assess stability of ancestry components.",
                        severity="warning",
                    ),
                )
            )
        q_columns = [column for column in table.columns if column.lower().startswith("q") and _has_numeric(table.rows, column)]
        if q_columns:
            summary["q_matrix_shape"] = table.metadata.get("q_matrix_shape") or [len(table.rows), len(q_columns)]
            high_samples = []
            max_by_sample = []
            sample_missing = "sample_id" not in {column.lower() for column in table.columns}
            for row in table.rows:
                proportions = [float(row[column]) for column in q_columns if _is_number(row.get(column))]
                if not proportions:
                    continue
                max_prop = max(proportions)
                sample_id = row.get("sample_id") or f"row_{row.get('row_index')}"
                item = {
                    "sample_id": sample_id,
                    "max_component": round(max_prop, 4),
                    "row_index": row.get("row_index"),
                    "source_file": row.get("source_file"),
                    "provenance_id": row.get("provenance_id"),
                }
                max_by_sample.append(item)
                if max_prop < 0.8 and sum(1 for value in proportions if value >= 0.2) >= 2:
                    high_samples.append(item)
            summary["max_component_per_sample"] = max_by_sample
            summary["high_admixture_samples"] = high_samples
            if sample_missing:
                summary["missing_sample_order_warning"] = "ADMIXTURE .Q matrix has no sample IDs; provide metadata/sample order to map rows."
                findings.append(
                    AuditFinding(
                        code="admixture_q_sample_order_missing",
                        severity="warning",
                        message="ADMIXTURE Q matrix cannot be matched to sample IDs without sample order metadata.",
                        details={"q_matrix_shape": summary["q_matrix_shape"]},
                        provenance=make_provenance(
                            source_file=src,
                            source_section="ADMIXTURE Q matrix",
                            parser_name="admixture_parser",
                            auditor_name="ADMIXTUREAuditor",
                            field_or_column="sample_id",
                            evidence_value=summary["q_matrix_shape"],
                            table_shape=table.metadata.get("table_shape"),
                            extraction_confidence=0.9,
                            provenance_id="prov_admix_q_sample_order_missing",
                            rule_id="ADMIXTURE_Q_SAMPLE_ORDER_MISSING",
                            rule_description="Headerless Q rows require external sample order to attach ancestry proportions to samples.",
                            severity="warning",
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


def _has_numeric(rows: list[dict[str, object]], column: str) -> bool:
    return any(_is_number(row.get(column)) for row in rows)
