from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from typing import Any

from app.insilicopop.rag.evidence_ingestion import EvidenceSourceDocument, guidance_document_from_corpus_item
from app.insilicopop.rag.evidence_models import EvidenceQuery, RetrievedEvidence
from app.insilicopop.rag.local_evidence_index import INTERNAL_CORPUS


@dataclass
class ChromaAvailability:
    available: bool
    reason: str


@dataclass
class LocalChromaEvidenceStore:
    collection_name: str = "insilicopop_local_guidance"
    documents: list[EvidenceSourceDocument] = field(default_factory=list)
    client: Any | None = None
    collection: Any | None = None

    def __post_init__(self) -> None:
        if not self.documents:
            self.documents = [guidance_document_from_corpus_item(item) for item in INTERNAL_CORPUS]
        self.availability = chroma_availability()
        if self.client is not None:
            self._try_initialize_local_collection()

    @property
    def available(self) -> bool:
        return bool(self.collection)

    def add_document(self, document: EvidenceSourceDocument) -> None:
        if document.raw_data_ingested:
            raise ValueError("Raw genomic data cannot be ingested into the local evidence store.")
        if not document.allowlisted:
            raise ValueError("Only allowlisted guidance documents can be ingested.")
        self.documents.append(document)
        if self.collection:
            self._add_to_collection(document)

    def retrieve(self, query: EvidenceQuery, *, limit: int = 3) -> list[RetrievedEvidence]:
        if not self.collection:
            return []
        results = self.collection.query(query_texts=[query.query_text], n_results=limit)
        ids = (results.get("ids") or [[]])[0]
        documents = (results.get("documents") or [[]])[0]
        metadatas = (results.get("metadatas") or [[]])[0]
        matches: list[RetrievedEvidence] = []
        for source_id, snippet, metadata in zip(ids, documents, metadatas, strict=False):
            metadata = metadata or {}
            matches.append(
                RetrievedEvidence(
                    source_id=str(source_id),
                    title=str(metadata.get("title", source_id)),
                    source_title=str(metadata.get("title", source_id)),
                    snippet=str(snippet),
                    matched_terms=[],
                    retrieval_method="local_chroma_vector",
                    source_type=str(metadata.get("evidence_type", "local_guidance")),
                    evidence_type=str(metadata.get("evidence_type", "local_guidance")),
                    safety_relevance="context",
                    confidence=0.5,
                )
            )
        return matches

    def _try_initialize_local_collection(self) -> None:
        try:
            self.collection = self.client.get_or_create_collection(self.collection_name)
            for document in self.documents:
                self._add_to_collection(document)
        except Exception as exc:  # pragma: no cover - depends on optional package internals
            self.availability = ChromaAvailability(False, f"chroma unavailable: {exc.__class__.__name__}")
            self.client = None
            self.collection = None

    def _add_to_collection(self, document: EvidenceSourceDocument) -> None:
        self.collection.upsert(
            ids=[document.source_id],
            documents=[document.text],
            metadatas=[
                {
                    "title": document.title,
                    "evidence_type": document.evidence_type,
                    "local_only": document.local_only,
                    "external_call_made": document.external_call_made,
                    "raw_data_ingested": document.raw_data_ingested,
                }
            ],
        )


def chroma_availability() -> ChromaAvailability:
    if importlib.util.find_spec("chromadb") is None:
        return ChromaAvailability(False, "chromadb is not installed; deterministic keyword fallback is active")
    return ChromaAvailability(True, "chromadb is importable for local-only use")
