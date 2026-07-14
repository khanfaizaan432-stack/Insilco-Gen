from __future__ import annotations

from app.insilicopop.auditors.metadata_auditor import BROAD_INDIAN_LABELS
from app.insilicopop.provenance import make_provenance, source_file
from app.schemas.insilicopop import AuditFinding, MetadataAudit, ParsedTable


class FSTAuditor:
    def run(self, table: ParsedTable | None, metadata: MetadataAudit | None = None) -> dict[str, object]:
        findings: list[AuditFinding] = []
        summary: dict[str, object] = {
            "highest_fst_pairs": [],
            "highest_pairs": [],
            "lowest_fst_pairs": [],
            "lowest_pairs": [],
            "high_fst_windows": [],
            "matrix_shape": None,
            "populations_seen": [],
            "sample_size_caveats": [],
            "overclaim_warnings": [],
        }
        if table is None:
            return {"summary": summary, "findings": findings}
        src = source_file(table, "fst")
        pairs = _extract_pairs(table)
        windows = _extract_windows(table)
        summary["matrix_shape"] = [len(table.rows), max(len(table.columns) - 1, 0)]
        populations = sorted({str(pair["pop1"]) for pair in pairs} | {str(pair["pop2"]) for pair in pairs})
        summary["populations_seen"] = populations
        if pairs:
            ordered = sorted(pairs, key=lambda item: item["fst"])
            summary["lowest_fst_pairs"] = ordered[:5]
            summary["lowest_pairs"] = ordered[:5]
            summary["highest_fst_pairs"] = list(reversed(ordered[-5:]))
            summary["highest_pairs"] = list(reversed(ordered[-5:]))
        if windows:
            summary["high_fst_windows"] = sorted(windows, key=lambda item: item["fst"], reverse=True)[:5]

        broad = [pop for pop in populations if pop.strip().lower() in BROAD_INDIAN_LABELS]
        if broad:
            message = "FST populations include broad labels that may obscure fine-scale endogamous structure."
            summary["overclaim_warnings"].append(message)
            findings.append(
                AuditFinding(
                    code="fst_broad_population_labels",
                    severity="warning",
                    message=message,
                    details={"labels": broad},
                    provenance=make_provenance(
                        source_file=src,
                        source_section="FST population labels",
                        parser_name="fst_parser",
                        auditor_name="FSTAuditor",
                        field_or_column="population",
                        evidence_value=broad,
                        rule_id="FST_BROAD_LABELS",
                        rule_description="Broad population labels can inflate or blur FST interpretation.",
                        severity="warning",
                    ),
                )
            )
        if metadata and metadata.tiny_population_groups:
            summary["sample_size_caveats"].append("Some FST groups have fewer than five metadata samples.")
            findings.append(
                AuditFinding(
                    code="fst_tiny_sample_size_caveat",
                    severity="warning",
                    message="FST interpretation is fragile for tiny population groups.",
                    details={"sample_counts": metadata.tiny_population_groups},
                    provenance=make_provenance(
                        source_file=src,
                        source_section="metadata sample counts",
                        parser_name="metadata_parser",
                        auditor_name="FSTAuditor",
                        field_or_column=metadata.population_column,
                        evidence_value=metadata.tiny_population_groups,
                        rule_id="FST_TINY_GROUPS",
                        rule_description="Pairwise FST estimates are unstable with very small sample sizes.",
                        severity="warning",
                    ),
                )
            )
        findings.append(
            AuditFinding(
                code="fst_context_required",
                severity="info",
                message="Avoid overclaiming population separation from FST without sample-size and community-label context.",
                    provenance=make_provenance(
                        source_file=src,
                        source_section="FST interpretation",
                        parser_name="fst_parser",
                        auditor_name="FSTAuditor",
                        field_or_column="fst",
                        row_index=_row_index(summary["highest_fst_pairs"][:1]),
                        evidence_value=summary["highest_fst_pairs"][:1],
                        evidence_snippet=str(summary["highest_fst_pairs"][:1]),
                        table_shape=table.metadata.get("table_shape"),
                        extraction_confidence=0.95,
                        provenance_id=_provenance_id(summary["highest_fst_pairs"][:1]),
                        rule_id="FST_CONTEXT_REQUIRED",
                        rule_description="FST is a differentiation statistic, not a standalone proof of discrete population identity.",
                        severity="info",
                    ),
            )
        )
        return {"summary": summary, "findings": findings}


def _extract_pairs(table: ParsedTable) -> list[dict[str, object]]:
    columns = {column.lower(): column for column in table.columns}
    pop1 = columns.get("pop1") or columns.get("population1")
    pop2 = columns.get("pop2") or columns.get("population2")
    fst = columns.get("fst") or columns.get("pairwise_fst")
    if pop1 and pop2 and fst:
        return [
            {
                "pop1": row.get(pop1),
                "pop2": row.get(pop2),
                "fst": float(row.get(fst)),
                "row_index": row.get("row_index"),
                "source_file": row.get("source_file"),
                "column_name": fst,
                "evidence_value": row.get(fst),
                "provenance_id": row.get("provenance_id", f"prov_fst_row_{int(row.get('row_index', 0)):03d}"),
            }
            for row in table.rows
            if _is_number(row.get(fst))
        ]

    first_col = table.columns[0] if table.columns else None
    pairs: list[dict[str, object]] = []
    if first_col:
        for row in table.rows:
            row_pop = str(row.get(first_col))
            for column in table.columns[1:]:
                if column in _HELPER_COLUMNS:
                    continue
                if column != row_pop and _is_number(row.get(column)):
                    pair = tuple(sorted([row_pop, str(column)]))
                    if pair[0] != pair[1]:
                        pairs.append(
                            {
                                "pop1": pair[0],
                                "pop2": pair[1],
                                "fst": float(row[column]),
                                "row_index": row.get("row_index"),
                                "source_file": row.get("source_file"),
                                "column_name": column,
                                "evidence_value": row.get(column),
                                "provenance_id": row.get("provenance_id", f"prov_fst_row_{int(row.get('row_index', 0)):03d}"),
                            }
                        )
    seen = set()
    unique = []
    for pair in pairs:
        key = (pair["pop1"], pair["pop2"])
        if key not in seen:
            seen.add(key)
            unique.append(pair)
    return unique


def _extract_windows(table: ParsedTable) -> list[dict[str, object]]:
    columns = {column.lower(): column for column in table.columns}
    chrom = columns.get("chrom") or columns.get("chromosome") or columns.get("chr")
    start = columns.get("bin_start") or columns.get("start")
    end = columns.get("bin_end") or columns.get("end")
    fst_col = columns.get("weighted_fst") or columns.get("mean_fst") or columns.get("fst")
    if not (chrom and start and end and fst_col):
        return []
    return [
        {
            "region": f"{row.get(chrom)}:{row.get(start)}-{row.get(end)}",
            "fst": float(row.get(fst_col)),
            "row_index": row.get("row_index"),
            "source_file": row.get("source_file"),
            "column_name": fst_col,
            "evidence_value": row.get(fst_col),
            "provenance_id": row.get("provenance_id", f"prov_fst_row_{int(row.get('row_index', 0)):03d}"),
        }
        for row in table.rows
        if _is_number(row.get(fst_col))
    ]


_HELPER_COLUMNS = {"row_index", "source_file", "line_number", "provenance_id", "source_type", "evidence_value"}


def _row_index(items: object) -> int | None:
    if isinstance(items, list) and items and isinstance(items[0], dict):
        value = items[0].get("row_index")
        return int(value) if isinstance(value, int) else None
    return None


def _provenance_id(items: object) -> str | None:
    if isinstance(items, list) and items and isinstance(items[0], dict):
        value = items[0].get("provenance_id")
        return str(value) if value else None
    return None


def _is_number(value: object) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False
