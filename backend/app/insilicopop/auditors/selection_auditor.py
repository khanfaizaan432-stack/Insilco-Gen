from __future__ import annotations

from app.insilicopop.provenance import make_provenance, source_file
from app.schemas.insilicopop import AuditFinding, ParsedTable


class SelectionAuditor:
    def run(self, table: ParsedTable | None, query: str | None = None) -> dict[str, object]:
        findings: list[AuditFinding] = []
        summary: dict[str, object] = {
            "top_candidate_regions": [],
            "statistic_used": None,
            "statistic": None,
            "threshold_detected": None,
            "multiple_testing_status": "unknown",
            "correction_status": "unknown",
            "demographic_caveat_status": "required",
            "overclaim_warnings": [],
        }
        if table is None:
            return {"summary": summary, "findings": findings}
        src = source_file(table, "selection_scan")
        columns = {column.lower(): column for column in table.columns}
        stat_col = columns.get("statistic") or columns.get("method")
        corrected_col = columns.get("correction_status") or columns.get("multiple_testing_corrected") or columns.get("corrected")
        q_col = columns.get("q_value")
        region_col = columns.get("region") or columns.get("locus") or columns.get("variant")
        chromosome_col = columns.get("chromosome") or columns.get("chrom") or columns.get("chr")
        start_col = columns.get("start")
        end_col = columns.get("end")
        score_col = (
            columns.get("score")
            or columns.get("statistic")
            or columns.get("stat_value")
            or columns.get("ihs")
            or columns.get("xpehh")
            or columns.get("xp_ehh")
            or columns.get("tajimas_d")
            or columns.get("tajima_d")
        )
        p_col = columns.get("p_value") or columns.get("p")
        if stat_col and table.rows:
            summary["statistic_used"] = table.rows[0].get(stat_col)
            summary["statistic"] = table.rows[0].get(stat_col)
        elif table.metadata.get("source_type"):
            summary["statistic_used"] = table.metadata.get("source_type")
            summary["statistic"] = table.metadata.get("source_type")
        if q_col:
            summary["multiple_testing_status"] = "q_value_present"
            summary["correction_status"] = "documented"
            summary["threshold_detected"] = "q_value"
        elif corrected_col:
            values = {str(row.get(corrected_col, "")).lower() for row in table.rows}
            documented = bool(values & {"true", "yes", "1", "bonferroni", "fdr", "q_value"})
            summary["multiple_testing_status"] = "documented" if documented else "not_documented"
            summary["correction_status"] = summary["multiple_testing_status"]
        else:
            summary["multiple_testing_status"] = "not_documented"
            summary["correction_status"] = "not_documented"
        if region_col or (chromosome_col and (start_col or columns.get("position"))):
            position_col = columns.get("position") or columns.get("pos")
            ranked = _rank_candidate_rows(table.rows, score_col, p_col, q_col)
            candidates = []
            for row in ranked[:5]:
                region = row.get(region_col) if region_col else _region(row, chromosome_col, start_col, end_col, position_col)
                candidates.append(
                    {
                        "region": region,
                        "score": row.get(score_col) if score_col else None,
                        "p_value": row.get(p_col) if p_col else None,
                        "q_value": row.get(q_col) if q_col else None,
                        "statistic_type": summary["statistic_used"],
                        "row_index": row.get("row_index"),
                        "source_file": row.get("source_file"),
                        "provenance_id": row.get("provenance_id"),
                    }
                )
            summary["top_candidate_regions"] = candidates
        if summary["multiple_testing_status"] == "not_documented":
            findings.append(
                AuditFinding(
                    code="selection_multiple_testing_missing",
                    severity="high",
                    message="Selection scan does not document multiple-testing correction.",
                    provenance=make_provenance(
                        source_file=src,
                        source_section="selection scan columns",
                        parser_name="selection_parser",
                        auditor_name="SelectionAuditor",
                        field_or_column="q_value/correction_status",
                        evidence_value=table.columns,
                        table_shape=table.metadata.get("table_shape"),
                        extraction_confidence=0.95,
                        provenance_id="prov_selection_correction_missing",
                        rule_id="SELECTION_CORRECTION_MISSING",
                        rule_description="Selection scan candidates need multiple-testing correction before strong claims.",
                        severity="high",
                    ),
                )
            )
        demographic_message = "Selection claims in Indian populations can be confounded by structure, drift, founder effects, and endogamy."
        summary["overclaim_warnings"].append(demographic_message)
        findings.append(
            AuditFinding(
                code="selection_demographic_caveat_required",
                severity="warning",
                message=demographic_message,
                provenance=make_provenance(
                    source_file=src,
                    source_section="selection interpretation",
                    parser_name="selection_parser",
                    auditor_name="SelectionAuditor",
                    field_or_column=stat_col,
                    evidence_value=summary["statistic_used"],
                    row_index=_first_candidate_row(summary["top_candidate_regions"]),
                    evidence_snippet=str(summary["top_candidate_regions"][:1]),
                    table_shape=table.metadata.get("table_shape"),
                    extraction_confidence=0.9,
                    provenance_id=_first_candidate_prov(summary["top_candidate_regions"]),
                    rule_id="SELECTION_DEMOGRAPHIC_CAVEAT",
                    rule_description="Population structure, drift, founder effects, and endogamy can mimic selection signals.",
                    severity="warning",
                ),
            )
        )
        if query and any(pattern in query.lower() for pattern in ["selection is proven", "proves selection"]):
            message = "The query overclaims selection as proven; selection scans require correction and demographic controls."
            summary["overclaim_warnings"].append(message)
            findings.append(
                AuditFinding(
                    code="selection_overclaim_proven",
                    severity="critical",
                    message=message,
                    provenance=make_provenance(
                        source_file=src,
                        source_section="query",
                        parser_name="selection_parser",
                        auditor_name="SelectionAuditor",
                        field_or_column="query",
                        evidence_value=query,
                        rule_id="SELECTION_OVERCLAIM_PROVEN",
                        rule_description="Selection scan statistics alone do not prove selection.",
                        severity="critical",
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


def _rank_candidate_rows(rows: list[dict[str, object]], score_col: str | None, p_col: str | None, q_col: str | None) -> list[dict[str, object]]:
    def key(row: dict[str, object]) -> tuple[int, float]:
        if q_col and _is_number(row.get(q_col)):
            return (2, -float(row.get(q_col)))
        if p_col and _is_number(row.get(p_col)):
            return (1, -float(row.get(p_col)))
        if score_col and _is_number(row.get(score_col)):
            return (0, abs(float(row.get(score_col))))
        return (-1, 0.0)

    return sorted(rows, key=key, reverse=True)


def _region(
    row: dict[str, object],
    chromosome_col: str | None,
    start_col: str | None,
    end_col: str | None,
    position_col: str | None,
) -> str:
    chrom = row.get(chromosome_col) if chromosome_col else "?"
    if start_col and end_col:
        return f"chr{chrom}:{row.get(start_col)}-{row.get(end_col)}"
    if position_col:
        return f"chr{chrom}:{row.get(position_col)}"
    return str(chrom)


def _first_candidate_row(candidates: object) -> int | None:
    if isinstance(candidates, list) and candidates and isinstance(candidates[0], dict):
        value = candidates[0].get("row_index")
        return int(value) if isinstance(value, int) else None
    return None


def _first_candidate_prov(candidates: object) -> str | None:
    if isinstance(candidates, list) and candidates and isinstance(candidates[0], dict):
        value = candidates[0].get("provenance_id")
        return str(value) if value else None
    return None
