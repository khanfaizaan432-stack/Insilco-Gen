from __future__ import annotations

from datetime import datetime, timezone

from app.insilicopop.rag.evidence_models import EvidenceQuery, EvidenceRetrievalResult, RetrievedEvidence, RetrievalPolicy


UNSAFE_EVIDENCE_REQUESTS = {
    "diagnosis": ("diagnos", "patient has", "disease confirmed"),
    "treatment_recommendation": ("treatment", "therapy", "medication", "prescribe"),
    "final_acmg_classification": ("final acmg", "classify pathogenic", "classify benign", "return this result"),
    "caste_community_religion_inference": ("caste", "community", "religion", "religious"),
    "genetic_purity_or_superiority": ("genetic purity", "pure population", "superior", "inferior"),
    "literal_ancestry_inference": ("literal ancestry", "admixture proves ancestry", "ancestry component"),
}


INTERNAL_CORPUS = [
    {
        "source_id": "internal_safe_wording_dictionary",
        "title": "Safe wording examples for PCA and ADMIXTURE",
        "terms": ["pca", "admixture", "safe wording", "population structure"],
        "snippet": "Use cautious wording: PCA shows structure or clustering, and ADMIXTURE components are model components; neither determines identity or literal ancestry.",
    },
    {
        "source_id": "internal_unsafe_claim_terms",
        "title": "Unsafe claim terms",
        "terms": ["unsafe", "claim", "caste", "religion", "purity", "superiority", "diagnosis", "treatment"],
        "snippet": "Unsafe requests include diagnosis, treatment recommendation, caste/community/religion inference, genetic purity or superiority, and identity claims.",
    },
    {
        "source_id": "internal_governance_cautions",
        "title": "Governance caution examples",
        "terms": ["governance", "dua", "consent", "managed access", "cross-border", "export"],
        "snippet": "Governance review should document declared consent/DUA scope, credential model, access terms, export declarations, and human approval requirements.",
    },
    {
        "source_id": "internal_clinical_curation_reminders",
        "title": "Clinical curation safety reminders",
        "terms": ["clinical", "hpo", "variant", "pedigree", "clinvar", "clingen", "gnomad"],
        "snippet": "Clinical genetics research curation may organize HPO, variant, pedigree, and source evidence, but it must not make diagnosis, treatment, or final classification decisions.",
    },
    {
        "source_id": "internal_acmg_suggestion_language",
        "title": "ACMG evidence suggestion safety language",
        "terms": ["acmg", "classification", "candidate evidence", "evidence missing"],
        "snippet": "Safe ACMG wording is limited to candidate evidence present, evidence missing, requires human review, and classification not made.",
    },
    {
        "source_id": "internal_offline_policy_reminders",
        "title": "Offline and hybrid policy reminders",
        "terms": ["offline", "network", "raw genomic", "api", "llm"],
        "snippet": "Raw genomic data must not be sent to external APIs or LLMs; future retrieval adapters must preserve explicit policy controls and provenance.",
    },
]


class LocalEvidenceIndex:
    def __init__(self, corpus: list[dict[str, object]] | None = None) -> None:
        self.corpus = corpus or INTERNAL_CORPUS

    def retrieve(self, query: EvidenceQuery | dict[str, object]) -> EvidenceRetrievalResult:
        evidence_query = query if isinstance(query, EvidenceQuery) else EvidenceQuery(**query)
        text = " ".join([evidence_query.query_text, evidence_query.research_lane, *evidence_query.safety_terms]).lower()
        unsafe_flags = _unsafe_flags(text)
        matches = []
        for source in self.corpus:
            terms = [str(term) for term in source.get("terms", [])]
            matched = [term for term in terms if term.lower() in text]
            if not matched and not unsafe_flags:
                continue
            if matched or any(flag.replace("_", " ") in str(source.get("snippet", "")).lower() for flag in unsafe_flags):
                matches.append(
                    RetrievedEvidence(
                        source_id=str(source["source_id"]),
                        title=str(source["title"]),
                        source_title=str(source["title"]),
                        matched_terms=matched,
                        snippet=str(source["snippet"]),
                        retrieval_method=_retrieval_method(source, unsafe_flags),
                        safety_relevance=_safety_relevance(source, unsafe_flags),
                        evidence_type=str(source.get("source_type", "internal_guidance")),
                        indexed_at=_utc_now(),
                    )
                )
        if unsafe_flags and not any(item.source_id == "internal_unsafe_claim_terms" for item in matches):
            source = next(item for item in self.corpus if item["source_id"] == "internal_unsafe_claim_terms")
            matches.append(
                RetrievedEvidence(
                    source_id=str(source["source_id"]),
                    title=str(source["title"]),
                    source_title=str(source["title"]),
                    matched_terms=unsafe_flags,
                    snippet=str(source["snippet"]),
                    retrieval_method="exact_safety_keyword",
                    safety_relevance="high",
                    evidence_type=str(source.get("source_type", "internal_guidance")),
                    indexed_at=_utc_now(),
                )
            )
        matches.sort(key=_safety_first_sort_key)
        return EvidenceRetrievalResult(
            evidence_query=evidence_query,
            retrieved_evidence=matches,
            retrieval_policy=RetrievalPolicy(),
            unsafe_request_flags=unsafe_flags,
            retrieval_mode="deterministic_keyword",
            retrieval_step_order=["exact_safety_keyword", "local_keyword"],
            caveats=[
                "Local built-in guidance snippets only.",
                "No biological or clinical conclusion was made.",
                "Human review is required.",
            ],
        )


def retrieve_local_evidence(query: EvidenceQuery | dict[str, object]) -> EvidenceRetrievalResult:
    return LocalEvidenceIndex().retrieve(query)


def _unsafe_flags(text: str) -> list[str]:
    flags = []
    for flag, markers in UNSAFE_EVIDENCE_REQUESTS.items():
        if any(marker in text for marker in markers):
            flags.append(flag)
    return flags


def _retrieval_method(source: dict[str, object], unsafe_flags: list[str]) -> str:
    source_id = str(source.get("source_id", ""))
    if unsafe_flags and source_id == "internal_unsafe_claim_terms":
        return "exact_safety_keyword"
    return "local_keyword"


def _safety_relevance(source: dict[str, object], unsafe_flags: list[str]) -> str:
    source_id = str(source.get("source_id", ""))
    if unsafe_flags and source_id == "internal_unsafe_claim_terms":
        return "high"
    return "context"


def _safety_first_sort_key(item: RetrievedEvidence) -> tuple[int, str]:
    priority = 0 if item.retrieval_method == "exact_safety_keyword" else 1
    return priority, item.source_id


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
