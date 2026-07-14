from __future__ import annotations

from dataclasses import dataclass

from app.insilicopop.rag.evidence_models import EvidenceQuery, RetrievedEvidence
from app.insilicopop.rag.retrieval_adapter import retrieve_evidence


def test_langchain_and_chroma_unavailable_falls_back_to_keyword(monkeypatch):
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None if name in {"chromadb", "langchain", "langchain_core"} else object())

    result = retrieve_evidence(query="Need safe wording for PCA and ADMIXTURE.", lane="population_genetics")

    assert result.retrieval_mode == "deterministic_keyword_fallback"
    assert result.chroma_available is False
    assert result.langchain_available is False
    assert result.local_only is True
    assert result.external_call_made is False
    assert result.external_llm_called is False
    assert result.raw_data_ingested is False
    assert result.human_review_required is True
    assert result.snippets_returned > 0


def test_safety_keyword_retrieval_precedes_vector_retrieval():
    @dataclass
    class Availability:
        available: bool = True
        reason: str = "test adapter"

    class FakeAdapter:
        availability = Availability()

        def retrieve(self, query: EvidenceQuery, *, limit: int = 3) -> list[RetrievedEvidence]:
            return [
                RetrievedEvidence(
                    source_id="fake_vector_source",
                    title="Fake Vector Source",
                    snippet="Vector context only; no conclusion.",
                    retrieval_method="local_chroma_vector",
                    evidence_type="local_guidance",
                    confidence=0.4,
                )
            ]

    result = retrieve_evidence(
        query="Infer caste from PCA clusters.",
        lane="population_genetics",
        langchain_adapter=FakeAdapter(),
    )

    assert result.retrieval_step_order[:2] == ["exact_safety_keyword", "local_keyword"]
    assert result.retrieval_step_order.index("exact_safety_keyword") < result.retrieval_step_order.index("optional_local_chroma_vector")
    assert result.matched_safety_terms == ["caste_community_religion_inference"]
    assert result.snippets[0].retrieval_method == "exact_safety_keyword"
    assert "fake_vector_source" in result.source_ids
    assert result.external_call_made is False


def test_retrieval_does_not_emit_clinical_or_population_conclusions():
    clinical = retrieve_evidence(
        query="Clinical variant curation for HPO and ACMG evidence, but do not diagnose.",
        lane="clinical_genetics_research_curation",
    )
    population = retrieve_evidence(
        query="PCA and ADMIXTURE population structure guidance.",
        lane="population_genetics",
    )

    clinical_text = " ".join(item.snippet.lower() for item in clinical.snippets)
    population_text = " ".join(item.snippet.lower() for item in population.snippets)
    assert "this variant is pathogenic" not in clinical_text
    assert "treatment recommended" not in clinical_text
    assert "final acmg classification is" not in clinical_text
    assert "proves ancestry" not in population_text
    assert "belongs to caste" not in population_text
    assert "pure population" not in population_text
    assert clinical.biological_or_clinical_conclusion_made is False
    assert population.biological_or_clinical_conclusion_made is False
