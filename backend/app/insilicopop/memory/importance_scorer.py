from __future__ import annotations

from app.schemas.memory import ImportanceScore


HIGH_IMPORTANCE_TERMS = {
    "ld pruning": 0.95,
    "tiny population": 0.9,
    "high roh": 0.92,
    "highest fst": 0.88,
    "cv error": 0.86,
    "selection candidate": 0.9,
    "multiple-testing": 0.9,
    "overclaim": 0.86,
    "best admixture k": 0.88,
    "duplicate sample": 0.91,
}


class ImportanceScorer:
    def score_facts(self, facts: list[str]) -> list[ImportanceScore]:
        scores: list[ImportanceScore] = []
        for fact in facts:
            lowered = fact.lower()
            matched = next((term for term in HIGH_IMPORTANCE_TERMS if term in lowered), None)
            score = HIGH_IMPORTANCE_TERMS[matched] if matched else 0.55
            scores.append(
                ImportanceScore(
                    item=fact,
                    score=score,
                    reason=matched or "domain-relevant retained fact",
                )
            )
        return scores
