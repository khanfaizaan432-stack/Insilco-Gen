from __future__ import annotations

from pydantic import BaseModel, Field


class EvidenceQuery(BaseModel):
    query_text: str
    research_lane: str = "population_genetics"
    safety_terms: list[str] = Field(default_factory=list)


class RetrievedEvidence(BaseModel):
    source_id: str
    title: str
    source_title: str | None = None
    matched_terms: list[str] = Field(default_factory=list)
    snippet: str
    retrieval_method: str = "exact_keyword"
    source_type: str = "internal_guidance"
    safety_relevance: str = "context"
    evidence_type: str = "internal_guidance"
    indexed_at: str | None = None
    confidence: float = 1.0
    local_only: bool = True
    external_call_made: bool = False
    raw_data_ingested: bool = False
    human_review_required: bool = True

    def model_post_init(self, __context: object) -> None:
        if self.source_title is None:
            self.source_title = self.title


class RetrievalPolicy(BaseModel):
    network_called: bool = False
    external_llm_called: bool = False
    external_call_made: bool = False
    raw_genomic_data_sent: bool = False
    raw_data_ingested: bool = False
    local_only: bool = True
    human_review_required: bool = True
    advisory_context_only: bool = True
    biological_or_clinical_conclusion_made: bool = False


class EvidenceRetrievalResult(BaseModel):
    evidence_query: EvidenceQuery
    retrieved_evidence: list[RetrievedEvidence] = Field(default_factory=list)
    retrieval_policy: RetrievalPolicy = Field(default_factory=RetrievalPolicy)
    unsafe_request_flags: list[str] = Field(default_factory=list)
    retrieval_mode: str = "deterministic_keyword"
    chroma_available: bool = False
    langchain_available: bool = False
    retrieval_step_order: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


class EvidenceRetrievalBundle(BaseModel):
    query: str | None = None
    goal: str | None = None
    lane: str = "insufficient_inputs"
    selected_lane: str = "insufficient_inputs"
    retrieval_mode: str = "deterministic_keyword_fallback"
    chroma_available: bool = False
    langchain_available: bool = False
    retrieval_step_order: list[str] = Field(default_factory=list)
    snippets_returned: int = 0
    snippets: list[RetrievedEvidence] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    matched_safety_terms: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    local_only: bool = True
    network_called: bool = False
    external_call_made: bool = False
    external_llm_called: bool = False
    external_tools_executed: bool = False
    raw_data_ingested: bool = False
    raw_genomic_files_parsed: bool = False
    human_review_required: bool = True
    biological_or_clinical_conclusion_made: bool = False
    clinical_decision_made: bool = False
    final_acmg_classification_made: bool = False
