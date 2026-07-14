from __future__ import annotations

from typing import Any

from app.insilicopop.provenance import make_provenance
from app.schemas.insilicopop import AuditFinding


PENALTIES = {
    "population_column_missing": 18,
    "missing_population_labels": 15,
    "tiny_population_groups": 10,
    "severe_population_imbalance": 10,
    "broad_indian_population_labels": 10,
    "pca_ld_pruning_not_documented": 10,
    "pca_relatedness_removal_not_documented": 10,
    "roh_ibd_analysis_recommended": 12,
    "high_roh_burden": 10,
    "admixture_k_sweep_too_narrow": 10,
    "admixture_cv_errors_missing": 10,
    "admixture_multiple_seeds_not_documented": 8,
    "fst_tiny_sample_size_caveat": 8,
    "selection_multiple_testing_missing": 12,
    "selection_demographic_caveat_required": 6,
    "selection_overclaim_proven": 15,
}


class ReliabilityAuditor:
    def score(self, findings: list[AuditFinding]) -> int:
        return int(self.evaluate(findings)["score"])

    def evaluate(self, findings: list[AuditFinding]) -> dict[str, Any]:
        score = 100
        penalties = []
        for finding in findings:
            points = PENALTIES.get(finding.code, 5 if finding.severity in {"error", "critical"} else 0)
            if finding.code.startswith("overclaim_"):
                points = max(points, 15 if finding.severity == "critical" else 8)
            if points:
                score -= points
                penalties.append(
                    {
                        "rule_id": finding.provenance.rule_id if finding.provenance else finding.code.upper(),
                        "points": -points,
                        "reason": finding.message,
                        "provenance": (
                            finding.provenance.model_dump()
                            if finding.provenance
                            else make_provenance(
                                source_file="unknown",
                                source_section="reliability",
                                parser_name="unknown",
                                auditor_name="ReliabilityAuditor",
                                field_or_column=None,
                                evidence_value=finding.code,
                                rule_id=finding.code.upper(),
                                rule_description="Reliability penalty generated from audit finding.",
                                severity="warning",
                            ).model_dump()
                        ),
                    }
                )
        clamped = max(0, min(100, score))
        positive_factors = _positive_factors(findings)
        return {
            "score": clamped,
            "penalties": penalties,
            "positive_factors": positive_factors,
            "score_band": _band(clamped),
            "summary": _summary(clamped, penalties),
        }


def _band(score: int) -> str:
    if score < 50:
        return "low"
    if score < 75:
        return "moderate"
    return "strong"


def _summary(score: int, penalties: list[dict[str, Any]]) -> str:
    if not penalties:
        return "No deterministic reliability penalties were applied."
    return f"Reliability score is {score}/100 after {len(penalties)} evidence-backed penalty rules."


def _positive_factors(findings: list[AuditFinding]) -> list[str]:
    codes = {finding.code for finding in findings}
    positives = []
    if "admixture_cv_errors_missing" not in codes:
        positives.append("ADMIXTURE CV information is available or not applicable.")
    if "missing_population_labels" not in codes and "population_column_missing" not in codes:
        positives.append("Population labels are present for supplied metadata.")
    if "selection_multiple_testing_missing" not in codes:
        positives.append("No missing selection correction warning was triggered.")
    return positives
