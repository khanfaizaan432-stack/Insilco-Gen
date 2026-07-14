from __future__ import annotations

from app.insilicopop.provenance import make_provenance, source_file
from app.schemas.insilicopop import AuditFinding, ParsedTable


class EndogamyAuditor:
    def run(self, roh_table: ParsedTable | None) -> list[AuditFinding]:
        src = source_file(roh_table, "not_provided")
        findings = [
            AuditFinding(
                code="endogamy_context_required",
                severity="warning",
                message="Indian datasets should not be assumed outbred; endogamy and founder effects can inflate relatedness and homozygosity.",
                provenance=make_provenance(
                    source_file=src,
                    source_section="study design",
                    parser_name="metadata_parser",
                    auditor_name="EndogamyAuditor",
                    field_or_column=None,
                    evidence_value="Indian population audit",
                    rule_id="ENDOGAMY_CONTEXT_REQUIRED",
                    rule_description="Indian population structure often requires endogamy-aware interpretation.",
                    severity="warning",
                ),
            )
        ]
        if roh_table is None:
            findings.append(
                AuditFinding(
                    code="roh_ibd_analysis_recommended",
                    severity="warning",
                    message="No ROH/IBD summary was provided; run ROH or IBD analysis before interpreting fine-scale Indian structure.",
                    provenance=make_provenance(
                        source_file=None,
                        source_section="ROH input",
                        parser_name="roh_parser",
                        auditor_name="EndogamyAuditor",
                        field_or_column=None,
                        evidence_value="roh_file missing",
                        rule_id="ROH_IBD_NOT_CONSIDERED",
                        rule_description="ROH/IBD analysis helps distinguish fine-scale structure from relatedness/endogamy.",
                        severity="warning",
                    ),
                )
            )
        return findings

