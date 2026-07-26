from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


TEST_STRATEGY_SCHEMA_VERSION = "0.31.3"
TEST_STRATEGY_ALGORITHM_VERSION = "insilicopop-staged-test-strategy-0.31.3"
TEST_STRATEGY_CATALOGUE_VERSION = "insilicopop-bounded-test-catalogue-0.31.3"
TEST_STRATEGY_RULE_SPEC_VERSION = "insilicopop-test-strategy-rules-0.31.3"
LOCAL_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"


class FrozenStrategyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)


class TestClass(str, Enum):
    NO_GENOMIC_TEST_YET = "no_genomic_test_yet"
    OBTAIN_OR_REVIEW_EXISTING_REPORT = "obtain_or_review_existing_report"
    ADDITIONAL_CLINICAL_ASSESSMENT = "additional_clinical_assessment"
    NON_GENETIC_INVESTIGATION_FIRST = "non_genetic_investigation_first"
    BIOCHEMICAL_OR_METABOLIC_INVESTIGATION = "biochemical_or_metabolic_investigation"
    KNOWN_FAMILIAL_VARIANT_TESTING = "known_familial_variant_testing"
    SINGLE_GENE_TESTING = "single_gene_testing"
    DELETION_DUPLICATION_ANALYSIS = "deletion_duplication_analysis"
    REPEAT_EXPANSION_TESTING = "repeat_expansion_testing"
    KARYOTYPE = "karyotype"
    CHROMOSOMAL_MICROARRAY = "chromosomal_microarray"
    FOCUSED_MULTIGENE_PANEL = "focused_multigene_panel"
    MITOCHONDRIAL_TESTING = "mitochondrial_testing"
    SINGLETON_WES = "singleton_wes"
    TRIO_WES = "trio_wes"
    WGS = "wgs"
    SPECIALIST_REVIEW = "specialist_review"
    MULTIDISCIPLINARY_REVIEW = "multidisciplinary_review"


class StrategyMechanism(str, Enum):
    EXISTING_REPORT_REVIEW = "existing_report_review"
    ADDITIONAL_CLINICAL_ASSESSMENT = "additional_clinical_assessment"
    NON_GENETIC_INVESTIGATION = "non_genetic_investigation"
    BIOCHEMICAL_OR_METABOLIC = "biochemical_or_metabolic"
    KNOWN_FAMILIAL_VARIANT = "known_familial_variant"
    SINGLE_GENE = "single_gene"
    INTRAGENIC_COPY_NUMBER = "intragenic_copy_number"
    REPEAT_EXPANSION = "repeat_expansion"
    CHROMOSOMAL_REARRANGEMENT = "chromosomal_rearrangement"
    GENOME_WIDE_COPY_NUMBER = "genome_wide_copy_number"
    FOCUSED_MULTIGENE = "focused_multigene"
    MITOCHONDRIAL = "mitochondrial"
    EXOME_SCOPE = "exome_scope"
    GENOME_SCOPE = "genome_scope"
    SPECIALIST_REVIEW = "specialist_review"
    MULTIDISCIPLINARY_REVIEW = "multidisciplinary_review"
    OTHER = "other"


class StrategyRuleReviewState(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    NEEDS_REVISION = "needs_revision"


class StrategyWorkspaceStatus(str, Enum):
    PROPOSED_OPTIONS_FOR_REVIEW = "proposed_options_for_review"
    DEFERRED_PENDING_PREREQUISITES = "deferred_pending_prerequisites"
    REQUIRES_RULE_REVIEW = "requires_rule_review"
    AWAITING_HUMAN_REVIEW = "awaiting_human_review"


class StrategyFeasibilityStatus(str, Enum):
    REVIEWABLE = "reviewable"
    CONSTRAINED = "constrained"
    DEFERRED_PENDING_PREREQUISITES = "deferred_pending_prerequisites"
    UNKNOWN = "unknown"


class FamilySampleMode(str, Enum):
    NONE_REQUIRED = "none_required"
    OPTIONAL = "optional"
    TRIO_REQUIRED = "trio_required"
    AFFECTED_RELATIVE_REPORT_OR_SAMPLE = "affected_relative_report_or_sample"


class StrategyFactReference(FrozenStrategyModel):
    fact_id: str = Field(min_length=1, max_length=80, pattern=LOCAL_ID_PATTERN)
    fact_summary_exact: str = Field(min_length=1, max_length=600)
    source_path: str = Field(min_length=1, max_length=300)
    source_record_ids: list[str] = Field(min_length=1, max_length=30)
    provenance_source_ids: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("source_record_ids", "provenance_source_ids", mode="before")
    @classmethod
    def canonicalize_identifiers(cls, value):
        return sorted(set(value or []))


class StrategyRuleInput(FrozenStrategyModel):
    rule_input_id: str = Field(min_length=1, max_length=80, pattern=LOCAL_ID_PATTERN)
    mechanism: StrategyMechanism
    rationale_exact: str = Field(min_length=1, max_length=600)
    review_state: StrategyRuleReviewState = StrategyRuleReviewState.PENDING
    trigger_facts: list[StrategyFactReference] = Field(min_length=1, max_length=30)
    other_mechanism_exact: str | None = Field(default=None, max_length=240)

    @model_validator(mode="after")
    def preserve_other_mechanism(self):
        if self.mechanism == StrategyMechanism.OTHER and not self.other_mechanism_exact:
            raise ValueError("other mechanism inputs require other_mechanism_exact")
        if self.mechanism != StrategyMechanism.OTHER and self.other_mechanism_exact:
            raise ValueError("other_mechanism_exact is only valid for mechanism=other")
        return self


class TestStrategyWorkspaceRequest(FrozenStrategyModel):
    schema_version: Literal["0.31.3"] = TEST_STRATEGY_SCHEMA_VERSION
    rule_inputs: list[StrategyRuleInput] = Field(default_factory=list, max_length=100)
    comparison_note_exact: str | None = Field(default=None, max_length=600)
    human_review_required: Literal[True] = True


class TestCatalogueEntry(FrozenStrategyModel):
    catalogue_entry_id: str
    test_class: TestClass
    display_name: str
    approved_trigger_mechanisms: list[StrategyMechanism]
    general_detection_scope: list[str]
    important_blind_spots: list[str]
    proband_sample_requirements: list[str]
    family_sample_requirements: list[str]
    family_sample_mode: FamilySampleMode
    prerequisites: list[str]
    reasons_to_defer: list[str]
    after_negative_result: list[str]


class StrategyTriggerFact(FrozenStrategyModel):
    fact_id: str
    fact_summary_exact: str
    source_path: str
    source_record_ids: list[str] = Field(default_factory=list)
    provenance_source_ids: list[str] = Field(default_factory=list)
    rule_input_id: str | None = None


class SuppliedStrategyContext(FrozenStrategyModel):
    care_setting: str | None = None
    locale_profile_type: str | None = None
    laboratory_availability_context: list[str] = Field(default_factory=list)
    access_constraints: list[str] = Field(default_factory=list)
    turnaround_time_exact: str | None = None
    affordability_context_exact: str | None = None
    sample_context: list[str] = Field(default_factory=list)
    family_sample_context: list[str] = Field(default_factory=list)
    universal_price_assumed: Literal[False] = False
    patient_worth_inference_made: Literal[False] = False


class TestStrategyOption(FrozenStrategyModel):
    option_id: str
    catalogue_entry_id: str
    test_class: TestClass
    display_name: str
    status: Literal["proposed_not_approved"] = "proposed_not_approved"
    why_surfaced: list[str]
    trigger_facts: list[StrategyTriggerFact]
    general_detection_scope: list[str]
    important_blind_spots: list[str]
    proband_sample_requirements: list[str]
    family_sample_requirements: list[str]
    supplied_context: SuppliedStrategyContext
    prerequisites: list[str]
    reasons_to_defer: list[str]
    after_negative_result: list[str]
    feasibility_status: StrategyFeasibilityStatus
    requires_clinician_selection: Literal[True] = True
    approved: Literal[False] = False
    ordered: Literal[False] = False
    medically_necessary_claim_made: Literal[False] = False
    commercial_product_selected: Literal[False] = False


class StrategyRuleReviewItem(FrozenStrategyModel):
    review_item_id: str
    code: str
    rule_input_id: str | None = None
    message: str
    status: Literal["requires_rule_review"] = "requires_rule_review"
    human_review_required: Literal[True] = True


class StrategyLinkageIssue(FrozenStrategyModel):
    issue_id: str
    code: str
    rule_input_id: str
    fact_id: str
    source_record_id: str
    message: str


class TestStrategyWorkspaceResult(FrozenStrategyModel):
    schema_version: Literal["0.31.3"] = TEST_STRATEGY_SCHEMA_VERSION
    algorithm_version: Literal["insilicopop-staged-test-strategy-0.31.3"] = TEST_STRATEGY_ALGORITHM_VERSION
    catalogue_version: Literal["insilicopop-bounded-test-catalogue-0.31.3"] = TEST_STRATEGY_CATALOGUE_VERSION
    rule_spec_version: Literal["insilicopop-test-strategy-rules-0.31.3"] = TEST_STRATEGY_RULE_SPEC_VERSION
    research_use_only: Literal[True] = True
    pseudonymous_case_id: str
    pre_test_assessment_outcome: str | None = None
    workspace_status: StrategyWorkspaceStatus
    status_rationale_codes: list[str] = Field(default_factory=list)
    comparison_note_exact: str | None = None
    comparison_dimensions: list[str] = Field(default_factory=list)
    options: list[TestStrategyOption] = Field(default_factory=list)
    rule_review_items: list[StrategyRuleReviewItem] = Field(default_factory=list)
    linkage_issues: list[StrategyLinkageIssue] = Field(default_factory=list)
    proposed_option_count: int = 0
    constrained_option_count: int = 0
    deferred_option_count: int = 0
    human_review_required: Literal[True] = True
    all_options_proposed_not_approved: Literal[True] = True
    test_strategy_generated: bool = False
    test_recommendation_made: Literal[False] = False
    test_approved: Literal[False] = False
    test_order_placed: Literal[False] = False
    final_test_selected: Literal[False] = False
    medically_necessary_claim_made: Literal[False] = False
    diagnosis_made: Literal[False] = False
    treatment_recommendation_made: Literal[False] = False
    final_acmg_classification_made: Literal[False] = False
    clinical_sign_out_made: Literal[False] = False
    external_api_call_made: Literal[False] = False
    external_llm_called: Literal[False] = False
    external_tools_executed: Literal[False] = False
    raw_genomic_files_parsed: Literal[False] = False
