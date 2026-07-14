from __future__ import annotations

import importlib.util
from dataclasses import dataclass

from app.insilicopop.rag.chroma_store import LocalChromaEvidenceStore, chroma_availability
from app.insilicopop.rag.evidence_models import EvidenceQuery, EvidenceRetrievalBundle, RetrievedEvidence
from app.insilicopop.rag.local_evidence_index import retrieve_local_evidence


@dataclass
class LangChainAvailability:
    available: bool
    reason: str


class LangChainRetrievalAdapter:
    def __init__(self, chroma_store: LocalChromaEvidenceStore | None = None) -> None:
        self.chroma_store = chroma_store or LocalChromaEvidenceStore()
        self.availability = langchain_availability()

    @property
    def available(self) -> bool:
        return self.availability.available and self.chroma_store.available

    def retrieve(self, query: EvidenceQuery, *, limit: int = 3) -> list[RetrievedEvidence]:
        if not self.available:
            return []
        return self.chroma_store.retrieve(query, limit=limit)


def retrieve_evidence(
    *,
    query: str | None,
    lane: str,
    safety_terms: list[str] | None = None,
    chroma_store: LocalChromaEvidenceStore | None = None,
    langchain_adapter: LangChainRetrievalAdapter | None = None,
    use_vector: bool = True,
) -> EvidenceRetrievalBundle:
    evidence_query = EvidenceQuery(
        query_text=query or "",
        research_lane=lane,
        safety_terms=safety_terms or [],
    )
    local_result = retrieve_local_evidence(evidence_query)
    chroma_status = chroma_availability()
    adapter = langchain_adapter or LangChainRetrievalAdapter(chroma_store=chroma_store)
    vector_matches = adapter.retrieve(evidence_query) if use_vector else []
    merged = _merge_evidence([*local_result.retrieved_evidence, *vector_matches])
    source_ids = [item.source_id for item in merged]
    warnings = [
        "Local evidence retrieval only; no external database or API call was made.",
        "Retrieved snippets are source-grounded context only and do not make biological or clinical conclusions.",
        "Human review is required before relying on any retrieved guidance.",
    ]
    if not chroma_status.available:
        warnings.append(chroma_status.reason)
    if not adapter.availability.available:
        warnings.append(adapter.availability.reason)
    retrieval_mode = "deterministic_keyword_fallback"
    if vector_matches:
        retrieval_mode = "deterministic_keyword_plus_local_vector"
    return EvidenceRetrievalBundle(
        query=query,
        goal=query,
        lane=lane,
        selected_lane=lane,
        retrieval_mode=retrieval_mode,
        chroma_available=chroma_status.available,
        langchain_available=adapter.availability.available,
        retrieval_step_order=[
            "exact_safety_keyword",
            "local_keyword",
            "optional_local_chroma_vector",
            "merge_deduplicate",
        ],
        snippets_returned=len(merged),
        snippets=merged,
        source_ids=source_ids,
        matched_safety_terms=local_result.unsafe_request_flags,
        warnings=_unique(warnings),
        caveats=_unique([*local_result.caveats, "Optional Chroma/LangChain retrieval is local-only and disabled when dependencies are unavailable."]),
    )


def langchain_availability() -> LangChainAvailability:
    candidates = ("langchain", "langchain_core")
    if not any(importlib.util.find_spec(name) is not None for name in candidates):
        return LangChainAvailability(False, "LangChain is not installed; deterministic keyword fallback is active")
    return LangChainAvailability(True, "LangChain is importable for local adapter use")


def _merge_evidence(items: list[RetrievedEvidence]) -> list[RetrievedEvidence]:
    merged: dict[tuple[str, str], RetrievedEvidence] = {}
    for item in items:
        key = (item.source_id, item.snippet)
        if key not in merged:
            merged[key] = item
            continue
        existing = merged[key]
        existing.matched_terms = _unique([*existing.matched_terms, *item.matched_terms])
        if existing.retrieval_method != "exact_safety_keyword" and item.retrieval_method == "exact_safety_keyword":
            existing.retrieval_method = item.retrieval_method
            existing.safety_relevance = item.safety_relevance
    return sorted(merged.values(), key=_sort_key)


def _sort_key(item: RetrievedEvidence) -> tuple[int, str]:
    priority = {
        "exact_safety_keyword": 0,
        "local_keyword": 1,
        "local_chroma_vector": 2,
    }.get(item.retrieval_method, 3)
    return priority, item.source_id


def _unique(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result
