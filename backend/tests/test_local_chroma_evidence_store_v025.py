from __future__ import annotations

from pathlib import Path

import pytest

from app.insilicopop.rag.chroma_store import LocalChromaEvidenceStore
from app.insilicopop.rag.evidence_ingestion import build_guidance_document_from_text, validate_guidance_path
from app.insilicopop.rag.evidence_models import EvidenceQuery


def test_chroma_store_is_optional_and_local_only_by_default(monkeypatch):
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None if name == "chromadb" else object())

    store = LocalChromaEvidenceStore()

    assert store.availability.available is False
    assert store.available is False
    assert store.retrieve(EvidenceQuery(query_text="PCA safe wording", research_lane="population_genetics")) == []
    assert all(document.local_only is True for document in store.documents)
    assert all(document.external_call_made is False for document in store.documents)
    assert all(document.raw_data_ingested is False for document in store.documents)


def test_raw_genomic_files_are_not_ingested_into_evidence_store(tmp_path: Path):
    raw_path = tmp_path / "cohort.vcf.gz"

    with pytest.raises(ValueError, match="Raw genomic files"):
        validate_guidance_path(raw_path)

    with pytest.raises(ValueError, match="Raw genomic files"):
        build_guidance_document_from_text(
            source_id="raw_vcf",
            title="Raw VCF",
            text="not actually read",
            source_path=raw_path,
        )


def test_allowlisted_guidance_document_can_be_registered(tmp_path: Path):
    guidance_path = tmp_path / "safe_guidance.md"
    document = build_guidance_document_from_text(
        source_id="safe_guidance",
        title="Safe Guidance",
        text="Use source-grounded snippets only; human review is required.",
        source_path=guidance_path,
    )
    store = LocalChromaEvidenceStore(documents=[])
    store.add_document(document)

    assert document in store.documents
    assert document.local_only is True
    assert document.external_call_made is False
    assert document.raw_data_ingested is False
