from __future__ import annotations

from collections import defaultdict

from app.insilicopop.provenance import make_provenance, source_file
from app.schemas.insilicopop import AuditFinding, ParsedTable


HIGH_ROH_MB = 50
VERY_HIGH_ROH_MB = 200


class ROHAuditor:
    def run(self, table: ParsedTable | None) -> dict[str, object]:
        findings: list[AuditFinding] = []
        summary: dict[str, object] = {
            "high_roh_samples": [],
            "high_roh_populations": [],
            "roh_summary_by_population": {},
            "roh_summary_by_sample": {},
            "roh_segment_count_by_sample": {},
            "max_roh_segment_by_sample": {},
            "roh_burden": {},
            "founder_effect_flags": [],
            "endogamy_interpretation_warnings": [],
        }
        if table is None:
            findings.append(
                AuditFinding(
                    code="roh_ibd_analysis_recommended",
                    severity="warning",
                    message="ROH/IBD summary is missing; run ROH or IBD analysis for Indian datasets.",
                    provenance=make_provenance(
                        source_file=None,
                        source_section="ROH input",
                        parser_name="roh_parser",
                        auditor_name="ROHAuditor",
                        field_or_column=None,
                        evidence_value="roh_file missing",
                        rule_id="ROH_IBD_NOT_CONSIDERED",
                        rule_description="Endogamy-aware Indian audits should consider ROH or IBD burden.",
                        severity="warning",
                    ),
                )
            )
            return {"summary": summary, "findings": findings}

        src = source_file(table, "roh")
        columns = {column.lower(): column for column in table.columns}
        sample_col = columns.get("sample_id") or columns.get("sample")
        pop_col = columns.get("population") or columns.get("pop") or columns.get("community")
        burden_col = (
            columns.get("total_roh_length_mb")
            or columns.get("total_roh_mb")
            or columns.get("roh_mb")
            or columns.get("mean_roh_mb")
        )
        segment_col = columns.get("roh_segment_mb")
        if burden_col is None and segment_col and sample_col:
            sample_totals: dict[str, float] = defaultdict(float)
            sample_counts: dict[str, int] = defaultdict(int)
            sample_max: dict[str, float] = defaultdict(float)
            sample_rows: dict[str, dict[str, object]] = {}
            for row in table.rows:
                if _is_number(row.get(segment_col)):
                    sample = str(row.get(sample_col))
                    value = float(row.get(segment_col))
                    sample_totals[sample] += value
                    sample_counts[sample] += 1
                    if value >= sample_max[sample]:
                        sample_max[sample] = value
                        sample_rows[sample] = row
            summary["roh_summary_by_sample"] = {sample: round(total, 3) for sample, total in sample_totals.items()}
            summary["roh_segment_count_by_sample"] = dict(sample_counts)
            summary["max_roh_segment_by_sample"] = {sample: round(value, 3) for sample, value in sample_max.items()}
            high_samples = []
            for sample, total in sorted(sample_totals.items()):
                if total > HIGH_ROH_MB:
                    evidence_row = sample_rows.get(sample, {})
                    high_samples.append(
                        {
                            "sample_id": sample,
                            "total_roh_length_mb": round(total, 3),
                            "roh_segment_count": sample_counts[sample],
                            "max_roh_segment_mb": round(sample_max[sample], 3),
                            "row_index": evidence_row.get("row_index"),
                            "source_file": evidence_row.get("source_file"),
                            "provenance_id": evidence_row.get("provenance_id", f"prov_roh_sample_{sample}"),
                        }
                    )
            summary["high_roh_samples"] = high_samples
            if high_samples:
                summary["founder_effect_flags"].append("High ROH burden may indicate endogamy or founder effects.")
                summary["endogamy_interpretation_warnings"].append("High ROH is not automatically disease or diagnosis.")
                first = high_samples[0]
                findings.append(
                    AuditFinding(
                        code="high_roh_sample_burden",
                        severity="high",
                        message="One or more samples have high total ROH burden; this is not a clinical diagnosis.",
                        details={"samples": high_samples},
                        provenance=make_provenance(
                            source_file=src,
                            source_section="ROH segment rows",
                            parser_name="roh_parser",
                            auditor_name="ROHAuditor",
                            field_or_column=segment_col,
                            row_index=first.get("row_index") if isinstance(first.get("row_index"), int) else None,
                            evidence_value=first,
                            evidence_snippet=str(first),
                            table_shape=table.metadata.get("table_shape"),
                            extraction_confidence=0.9,
                            provenance_id=str(first.get("provenance_id")),
                            rule_id="HIGH_ROH_SAMPLE_BURDEN",
                            rule_description="Aggregated PLINK ROH segments exceed the deterministic high-burden threshold.",
                            severity="high",
                        ),
                    )
                )
        if pop_col and burden_col:
            values: dict[str, list[float]] = defaultdict(list)
            high_samples = []
            for row in table.rows:
                if _is_number(row.get(burden_col)):
                    value = float(row.get(burden_col))
                    pop = str(row.get(pop_col))
                    values[pop].append(value)
                    if value > HIGH_ROH_MB:
                        high_samples.append(
                            {
                                "sample_id": row.get(sample_col),
                                "population": pop,
                                "total_roh_length_mb": value,
                                "row_index": row.get("row_index"),
                                "source_file": row.get("source_file"),
                                "provenance_id": row.get("provenance_id"),
                            }
                        )
            burden = {pop: round(sum(nums) / len(nums), 3) for pop, nums in values.items() if nums}
            summary["roh_summary_by_population"] = burden
            summary["roh_burden"] = burden
            summary["high_roh_samples"] = high_samples
            high = sorted(pop for pop, value in burden.items() if value > HIGH_ROH_MB)
            very_high = sorted(pop for pop, value in burden.items() if value > VERY_HIGH_ROH_MB)
            summary["high_roh_populations"] = high
            if high:
                summary["founder_effect_flags"].append("High ROH burden may indicate endogamy or founder effects.")
                summary["endogamy_interpretation_warnings"].append("High ROH is not automatically disease or diagnosis.")
                findings.append(
                    AuditFinding(
                        code="high_roh_burden",
                        severity="high" if not very_high else "critical",
                        message="High ROH burden may indicate endogamy or founder effects; it is not a clinical diagnosis.",
                        details={"populations": high, "very_high_populations": very_high},
                        provenance=make_provenance(
                            source_file=src,
                            source_section="ROH burden",
                            parser_name="roh_parser",
                            auditor_name="ROHAuditor",
                            field_or_column=burden_col,
                            row_index=high_samples[0].get("row_index") if high_samples and isinstance(high_samples[0].get("row_index"), int) else None,
                            evidence_value=burden,
                            evidence_snippet=str(high_samples[:1]),
                            table_shape=table.metadata.get("table_shape"),
                            extraction_confidence=0.9,
                            provenance_id=str(high_samples[0].get("provenance_id")) if high_samples else None,
                            rule_id="HIGH_ROH_BURDEN",
                            rule_description="ROH >100 Mb is flagged as high and >200 Mb as very high for deterministic triage.",
                            severity="high" if not very_high else "critical",
                        ),
                    )
                )
        findings.append(
            AuditFinding(
                code="roh_population_specific_interpretation",
                severity="info",
                message="Interpret ROH burden with population-specific endogamy and founder-effect context.",
                provenance=make_provenance(
                    source_file=src,
                    source_section="ROH interpretation",
                    parser_name="roh_parser",
                    auditor_name="ROHAuditor",
                    field_or_column=burden_col,
                    evidence_value=summary["roh_summary_by_population"],
                    rule_id="ROH_POPULATION_CONTEXT",
                    rule_description="ROH burden should be interpreted using population-specific demographic context.",
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
