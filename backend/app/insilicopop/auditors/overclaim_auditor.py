from __future__ import annotations

from app.insilicopop.provenance import make_provenance
from app.schemas.insilicopop import AuditFinding


RISKY_PATTERNS = {
    "ani_asi_only": ["only ani/asi", "explained by ani/asi", "only ani and asi"],
    "selection_proven": ["selection is proven", "proves selection", "definitely selected"],
    "all_indians_disease": ["all indians", "disease risk applies"],
    "population_language_geography": ["population = language", "population = geography"],
    "roh_means_disease": ["high roh means disease", "roh proves disease"],
    "clinical_claim": ["diagnosis", "clinical recommendation", "genetic counseling"],
}


class OverclaimAuditor:
    def run(self, query: str | None) -> list[AuditFinding]:
        if not query:
            return []
        lowered = query.lower()
        findings: list[AuditFinding] = []
        for code, patterns in RISKY_PATTERNS.items():
            if any(pattern in lowered for pattern in patterns):
                severity = "critical" if code in {"selection_proven", "clinical_claim"} else "high"
                findings.append(
                    AuditFinding(
                        code=f"overclaim_{code}",
                        severity=severity,
                        message="Query contains a risky interpretation claim that should be softened or caveated.",
                        provenance=make_provenance(
                            source_file="query",
                            source_section="query",
                            parser_name="query_parser",
                            auditor_name="OverclaimAuditor",
                            field_or_column="query",
                            evidence_value=query,
                            rule_id=f"OVERCLAIM_{code.upper()}",
                            rule_description="Population-genetics audit text must avoid unsupported ancestry, selection, disease, or clinical claims.",
                            severity=severity,
                        ),
                    )
                )
        return findings

