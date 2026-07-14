from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from app.insilicopop.auditors.admixture_auditor import ADMIXTUREAuditor
from app.insilicopop.auditors.endogamy_auditor import EndogamyAuditor
from app.insilicopop.auditors.fst_auditor import FSTAuditor
from app.insilicopop.auditors.metadata_auditor import MetadataAuditor
from app.insilicopop.auditors.overclaim_auditor import OverclaimAuditor
from app.insilicopop.auditors.pca_auditor import PCAAuditor
from app.insilicopop.auditors.reliability_auditor import ReliabilityAuditor
from app.insilicopop.auditors.roh_auditor import ROHAuditor
from app.insilicopop.auditors.selection_auditor import SelectionAuditor
from app.insilicopop.memory.compressor import DomainMemoryCompressor
from app.insilicopop.parsers.admixture_parser import parse_admixture, parse_admixture_cv_log, parse_admixture_p_metadata, parse_admixture_q
from app.insilicopop.parsers.fst_parser import parse_fst, parse_windowed_fst
from app.insilicopop.parsers.metadata_parser import parse_metadata
from app.insilicopop.parsers.pca_parser import parse_pca
from app.insilicopop.parsers.plink_parser import (
    parse_plink_genome,
    parse_plink_het,
    parse_plink_hwe,
    parse_plink_imiss,
    parse_plink_lmiss,
    parse_plink_prune,
)
from app.insilicopop.parsers.plink_qc_parser import parse_plink_qc
from app.insilicopop.parsers.roh_parser import parse_plink_hom, parse_roh
from app.insilicopop.parsers.selection_parser import parse_selection
from app.insilicopop.parsers.smartpca_parser import parse_eval, parse_evec, parse_smartpca_log
from app.insilicopop.planner.next_step_planner import NextStepPlanner
from app.insilicopop.reports.audit_report import write_audit_outputs
from app.schemas.insilicopop import AuditFinding, InSilicoPopAuditResponse, ParsedTable
from app.schemas.memory import MemoryCompressRequest


class InSilicoPopAuditService:
    def __init__(self, generated_root: Path | None = None) -> None:
        self.generated_root = generated_root or Path(__file__).resolve().parents[1] / "generated"

    def run(
        self,
        query: str | None,
        uploads: dict[str, bytes | dict[str, bytes | str] | None],
        memory_mode: str = "verbose",
        include_memory_provenance: bool = False,
    ) -> InSilicoPopAuditResponse:
        run_id = uuid4().hex[:12]
        tables = self._parse_uploads(uploads)

        metadata_audit = MetadataAuditor().run(tables.get("metadata"))
        pca_audit = PCAAuditor().run(tables.get("pca"), metadata_audit)
        admixture_audit = ADMIXTUREAuditor().run(tables.get("admixture"))
        fst_audit = FSTAuditor().run(tables.get("fst"), metadata_audit)
        roh_audit = ROHAuditor().run(tables.get("roh"))
        selection_audit = SelectionAuditor().run(tables.get("selection_scan"), query)
        overclaim_findings = OverclaimAuditor().run(query)

        findings: list[AuditFinding] = []
        findings.extend(metadata_audit.findings)
        findings.extend(EndogamyAuditor().run(tables.get("roh")))
        for result in [pca_audit, admixture_audit, fst_audit, roh_audit, selection_audit]:
            findings.extend(result["findings"])
        findings.extend(overclaim_findings)

        reliability = ReliabilityAuditor().evaluate(findings)
        reliability_score = int(reliability["score"])
        audits = {
            "metadata": {"summary": metadata_audit.model_dump(), "findings": metadata_audit.findings},
            "pca": pca_audit,
            "admixture": admixture_audit,
            "fst": fst_audit,
            "roh": roh_audit,
            "selection_scan": selection_audit,
        }
        memory = self._build_memory(tables, findings, audits, memory_mode, include_memory_provenance)
        plan = NextStepPlanner().plan(findings)
        audit_report = {
            "project": "InSilicoPop",
            "scope": "local-first population genetics reliability audit; not clinical diagnosis or genetic counseling",
            "query": query,
            "metadata": metadata_audit.model_dump(),
            "pca": pca_audit,
            "admixture": admixture_audit,
            "fst": fst_audit,
            "roh": roh_audit,
            "selection": selection_audit,
            "overclaim": {"findings": [finding.model_dump() for finding in overclaim_findings]},
            "reliability": reliability,
            "risk_flags": [finding.model_dump() for finding in findings],
            "reliability_score": reliability_score,
        }
        generated_files = write_audit_outputs(
            self.generated_root / run_id,
            audit_report,
            memory,
            plan,
            reliability_score,
            findings,
        )
        return InSilicoPopAuditResponse(
            run_id=run_id,
            query=query,
            reliability_score=reliability_score,
            risk_flags=findings,
            audit_report=audit_report,
            compressed_memory=memory,
            next_analysis_plan=plan,
            generated_files=generated_files,
        )

    def _parse_uploads(self, uploads: dict[str, bytes | dict[str, bytes | str] | None]) -> dict[str, ParsedTable]:
        parsers = {
            "metadata": parse_metadata,
            "pca": parse_pca,
            "admixture": parse_admixture,
            "fst": parse_fst,
            "roh": parse_roh,
            "plink_qc": parse_plink_qc,
            "selection_scan": parse_selection,
        }
        parsed: dict[str, ParsedTable] = {}
        for name, parser in parsers.items():
            upload = uploads.get(name)
            content: bytes | None
            filename: str | None
            if isinstance(upload, dict):
                content = upload.get("content") if isinstance(upload.get("content"), bytes) else None
                filename = str(upload.get("filename") or name)
            else:
                content = upload if isinstance(upload, bytes) else None
                filename = name
            if content:
                parsed[name] = parser(content, filename)
        sample_ids = _sample_ids(parsed.get("metadata"))
        native_specs = {
            "plink_imiss": parse_plink_imiss,
            "plink_lmiss": parse_plink_lmiss,
            "plink_het": parse_plink_het,
            "plink_hwe": parse_plink_hwe,
            "plink_genome": parse_plink_genome,
            "plink_prune_in": lambda content, filename=None: parse_plink_prune(content, filename, kept=True),
            "plink_prune_out": lambda content, filename=None: parse_plink_prune(content, filename, kept=False),
            "admixture_cv": parse_admixture_cv_log,
            "admixture_q": lambda content, filename=None: parse_admixture_q(content, filename, sample_ids=sample_ids),
            "admixture_p": parse_admixture_p_metadata,
            "smartpca_evec": parse_evec,
            "smartpca_eval": parse_eval,
            "smartpca_log": parse_smartpca_log,
            "windowed_fst": parse_windowed_fst,
            "plink_hom": parse_plink_hom,
        }
        native_parsed: dict[str, ParsedTable] = {}
        for name, parser in native_specs.items():
            content, filename = _content_and_filename(uploads.get(name), name)
            if content:
                native_parsed[name] = parser(content, filename)
        parsed.update({name: table for name, table in native_parsed.items() if name.startswith("plink_")})
        admixture_table = _merge_tables(
            [table for table in [parsed.get("admixture"), native_parsed.get("admixture_cv"), native_parsed.get("admixture_q"), native_parsed.get("admixture_p")] if table],
            fallback_name="admixture",
        ) or parsed.get("admixture")
        if admixture_table:
            parsed["admixture"] = admixture_table
        pca_table = _merge_tables(
            [table for table in [parsed.get("pca"), native_parsed.get("smartpca_evec"), native_parsed.get("smartpca_eval"), native_parsed.get("smartpca_log")] if table],
            fallback_name="pca",
        ) or parsed.get("pca")
        if pca_table:
            parsed["pca"] = pca_table
        fst_table = _merge_tables(
            [table for table in [parsed.get("fst"), native_parsed.get("windowed_fst")] if table],
            fallback_name="fst",
        ) or parsed.get("fst")
        if fst_table:
            parsed["fst"] = fst_table
        if native_parsed.get("plink_hom"):
            roh_table = _merge_tables([table for table in [parsed.get("roh"), native_parsed.get("plink_hom")] if table], fallback_name="roh") or parsed.get("roh")
            if roh_table:
                parsed["roh"] = roh_table
        return parsed

    def _build_memory(
        self,
        tables: dict[str, ParsedTable],
        findings: list[AuditFinding],
        audits: dict[str, dict[str, object]] | None = None,
        memory_mode: str = "verbose",
        include_memory_provenance: bool = False,
    ) -> dict[str, Any]:
        compressor = DomainMemoryCompressor()
        compressed_tools: dict[str, Any] = {}
        tool_map = {
            "metadata": "metadata",
            "pca": "pca",
            "admixture": "admixture",
            "fst": "fst",
            "roh": "roh",
            "selection_scan": "selection_scan",
            "plink_qc": "plink_qc",
            "plink_imiss": "plink_qc",
            "plink_lmiss": "plink_qc",
            "plink_het": "plink_qc",
            "plink_hwe": "plink_qc",
            "plink_genome": "plink_qc",
            "plink_prune_in": "plink_qc",
            "plink_prune_out": "plink_qc",
            "plink_hom": "roh",
        }
        for table_name, tool_name in tool_map.items():
            if table_name in tables:
                audit = (audits or {}).get(table_name, {})
                response = compressor.compress(
                    MemoryCompressRequest(
                        tool_name=tool_name,
                        step_name=f"{table_name}_audit",
                        raw_output={
                            "summary": audit.get("summary", {}),
                            "findings": [
                                finding.model_dump()
                                for finding in audit.get("findings", [])
                                if isinstance(finding, AuditFinding)
                            ],
                            "rows": tables[table_name].rows,
                            "columns": tables[table_name].columns,
                            "metadata": tables[table_name].metadata,
                        },
                        memory_mode=memory_mode,
                        include_provenance=include_memory_provenance,
                    )
                )
                compressed_tools[table_name] = response.model_dump()
        return {
            "domain": "Indian population genetics",
            "safety_note": "Research audit memory only; not clinical diagnosis or genetic counseling.",
            "tools": compressed_tools,
            "risk_flags": [finding.code for finding in findings],
        }


def capabilities() -> dict[str, object]:
    return {
        "project": "InSilicoPop",
        "local_first": True,
        "clinical_use": False,
        "supported_audits": [
            "Indian population metadata checks",
            "endogamy-aware sample-size warnings",
            "PCA readiness audit",
            "ADMIXTURE K/seed audit",
            "FST reliability audit",
            "ROH/founder-effect audit",
            "selection scan overclaim audit",
            "domain-aware memory compression",
        ],
    }


def _content_and_filename(upload: bytes | dict[str, bytes | str] | None, fallback: str) -> tuple[bytes | None, str]:
    if isinstance(upload, dict):
        content = upload.get("content") if isinstance(upload.get("content"), bytes) else None
        return content, str(upload.get("filename") or fallback)
    return (upload if isinstance(upload, bytes) else None), fallback


def _sample_ids(table: ParsedTable | None) -> list[str] | None:
    if table is None:
        return None
    columns = {column.lower(): column for column in table.columns}
    sample_col = columns.get("sample_id") or columns.get("sample") or columns.get("iid")
    if not sample_col:
        return None
    return [str(row.get(sample_col)) for row in table.rows if row.get(sample_col) not in (None, "")]


def _merge_tables(tables: list[ParsedTable], fallback_name: str) -> ParsedTable | None:
    if not tables:
        return None
    if len(tables) == 1:
        return tables[0]
    columns: list[str] = []
    rows: list[dict[str, Any]] = []
    metadata: dict[str, Any] = {"source_file": "+".join(str(table.metadata.get("source_file", table.name)) for table in tables), "parser_name": f"{fallback_name}_merged_parser"}
    for table in tables:
        for column in table.columns:
            if column not in columns:
                columns.append(column)
        for row in table.rows:
            merged_row = dict(row)
            merged_row.setdefault("source_type", table.metadata.get("source_type", table.name))
            rows.append(merged_row)
        for key, value in table.metadata.items():
            if key in {"source_file", "parser_name"}:
                continue
            if key not in metadata or metadata.get(key) in (None, "", [], {}):
                metadata[key] = value
            elif key == "eigenvalues" and isinstance(value, list):
                metadata[key] = value
            elif key in {"ld_pruning_documented", "relatedness_removal_documented"}:
                metadata[key] = bool(metadata.get(key)) or bool(value)
    metadata["source_types"] = [str(table.metadata.get("source_type", table.name)) for table in tables]
    metadata["table_shape"] = [len(rows), len(columns)]
    return ParsedTable(name=fallback_name, columns=columns, rows=rows, metadata=metadata)
