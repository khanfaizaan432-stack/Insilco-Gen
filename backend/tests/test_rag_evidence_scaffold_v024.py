from __future__ import annotations

from app.insilicopop.rag.evidence_models import EvidenceQuery
from app.insilicopop.rag.local_evidence_index import LocalEvidenceIndex, retrieve_local_evidence


def test_local_evidence_scaffold_returns_internal_evidence_only():
    result = retrieve_local_evidence(
        {
            "query_text": "Need safe wording for PCA and ADMIXTURE population structure.",
            "research_lane": "population_genetics",
            "safety_terms": ["safe wording"],
        }
    )

    assert result.retrieval_policy.network_called is False
    assert result.retrieval_policy.external_llm_called is False
    assert result.retrieval_policy.raw_genomic_data_sent is False
    assert result.retrieval_policy.human_review_required is True
    assert result.retrieved_evidence
    assert all(item.source_type == "internal_guidance" for item in result.retrieved_evidence)
    assert any(item.source_id == "internal_safe_wording_dictionary" for item in result.retrieved_evidence)


def test_rag_scaffold_flags_unsafe_evidence_requests_without_returning_decisions():
    result = LocalEvidenceIndex().retrieve(
        EvidenceQuery(
            query_text="Give final ACMG classification, diagnosis, treatment, caste inference, and genetic purity claim.",
            research_lane="clinical_genetics_research_curation",
        )
    )

    assert {"diagnosis", "treatment_recommendation", "final_acmg_classification", "caste_community_religion_inference", "genetic_purity_or_superiority"} <= set(result.unsafe_request_flags)
    assert result.retrieval_policy.biological_or_clinical_conclusion_made is False
    assert result.retrieval_policy.advisory_context_only is True
    snippets = " ".join(item.snippet.lower() for item in result.retrieved_evidence)
    assert "must not make diagnosis" in snippets or "unsafe requests include diagnosis" in snippets
    assert "this variant is pathogenic" not in snippets
    assert "treatment recommended" not in snippets


def test_clinical_curation_scaffold_returns_safety_reminders():
    result = retrieve_local_evidence(
        EvidenceQuery(
            query_text="HPO variant ClinVar ClinGen gnomAD ACMG evidence missing",
            research_lane="clinical_genetics_research_curation",
            safety_terms=["candidate evidence"],
        )
    )

    source_ids = {item.source_id for item in result.retrieved_evidence}
    assert "internal_clinical_curation_reminders" in source_ids
    assert "internal_acmg_suggestion_language" in source_ids
    assert result.retrieval_policy.network_called is False
