from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Annotated, Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


CANDIDATE_ANALYSIS_SCHEMA_VERSION = "0.37"
CANDIDATE_ANALYSIS_ALGORITHM_VERSION = "insilicopop-candidate-analysis-0.37.0"
CANDIDATE_RANKING_RULE_VERSION = "insilicopop-candidate-ranking-0.37.0"
CANDIDATE_RANKING_WEIGHT_VERSION = "insilicopop-candidate-ranking-weights-0.37.0"
CANDIDATE_REQUIRED_UNRESOLVED_WORDING = (
    "No sufficiently supported candidate was identified within the supplied analysis scope."
)
CANDIDATE_SOURCE_BINDING_DOMAIN = "insilicopop:candidate-source-binding:v0.37"
CANDIDATE_FIXED_SUPPORT_THRESHOLD = 8.0
CANDIDATE_FIXED_TIE_EPSILON = 0.000001
CANDIDATE_FIXED_FAMILY_GQ_THRESHOLD = 20.0
LOCAL_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
SHA256_PATTERN = r"^[a-fA-F0-9]{64}$"
BoundedIdentifier = Annotated[str, Field(min_length=1, max_length=160, pattern=LOCAL_ID_PATTERN)]
StrictFiniteFloat = Annotated[float, Field(strict=True, allow_inf_nan=False)]
StrictFiniteUnitFloat = Annotated[
    float,
    Field(strict=True, allow_inf_nan=False, ge=0.0, le=1.0),
]


CANDIDATE_FIXED_COMPONENT_WEIGHTS = MappingProxyType(
    {
        "phenotype_match": 4.0,
        "phenotype_specificity": 1.0,
        "onset_compatibility": 0.5,
        "inheritance_compatibility": 3.0,
        "segregation": 2.0,
        "frequency": 2.0,
        "consequence": 2.0,
        "transcript_relevance": 1.5,
        "gene_disease_validity": 1.5,
        "variant_quality": 1.0,
        "qc": 0.5,
        "coverage_assay_scope": 1.0,
        "supporting_evidence": 1.0,
        "contradicting_evidence": 1.0,
        "missing_information": 0.0,
        "unresolved_uncertainty": 0.0,
    }
)


def _fixed_component_rationale(component_id: str) -> str:
    return {
        "phenotype_match": "Supplied HPO identifiers are compared exactly; related terms are used only when a pinned supplied relation is present.",
        "phenotype_specificity": "Only a supplied specificity value is used; specificity is not inferred from an unpinned ontology.",
        "onset_compatibility": "Only the supplied onset compatibility state is used.",
        "inheritance_compatibility": "Uses supplied inheritance statements and the bounded v0.29 consistency audit; it is review evidence, not a diagnosis.",
        "segregation": "Uses supplied family observations and deterministic genotype/sample bindings where all prerequisites are present.",
        "frequency": "Uses a supplied population-frequency value as prioritization context; absence from a dataset is never negative evidence.",
        "consequence": "Uses supplied consequence text only and does not predict pathogenicity.",
        "transcript_relevance": "Uses supplied transcript relevance only; transcript selection is not performed.",
        "gene_disease_validity": "Uses supplied validity context only; no external evidence retrieval is performed.",
        "variant_quality": "Uses supplied VCF quality/filter fields only.",
        "qc": "Uses supplied QC fields only; missing or warning-only QC is not converted into disease absence.",
        "coverage_assay_scope": "Coverage and reportable-scope limits change confidence and review status, never disease absence.",
        "supporting_evidence": "Counts supplied candidate evidence with visible source references.",
        "contradicting_evidence": "Counts supplied contradictory evidence and retains it visibly.",
        "missing_information": "Missing inputs are retained as missing and contribute no false positive or false negative evidence.",
        "unresolved_uncertainty": "Unresolved inputs remain explicit and contribute no score.",
    }[component_id]


def _canonical_input_items(value: Any, *, key_fields: tuple[str, ...]) -> Any:
    if value is None:
        return value
    items = list(value)

    def key(item: Any) -> str:
        if isinstance(item, BaseModel):
            payload = item.model_dump(mode="json")
        elif isinstance(item, dict):
            payload = item
        else:
            payload = {field: getattr(item, field, None) for field in key_fields}
        selected = {field: payload.get(field) for field in key_fields}
        return canonical_json(selected)

    return tuple(sorted(items, key=key))


def _normalized_public_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.casefold())).strip()


def _contains_absolute_negative_language(value: str) -> bool:
    text = _normalized_public_text(value)
    patterns = (
        r"\b(?:the )?(?:patient|person|case) (?:does not have|has no|lacks) (?:a )?(?:genetic )?(?:disorder|disease|condition)\b",
        r"\b(?:the )?(?:condition|disorder|disease|result|test) (?:is|was) (?:ruled out|absent|negative)\b",
        r"\bno (?:disease causing )?(?:variant|disease|disorder|condition) (?:exists|identified|present)\b",
        r"\bconfirmed (?:absence|negative)\b",
        r"\b(?:definitive|conclusive) negative\b",
    )
    return any(re.search(pattern, text) for pattern in patterns)


class CandidateFrozenModel(BaseModel):
    """Deeply immutable v0.37 public contracts.

    Collections are tuples so a caller cannot mutate a nested result after it
    has been built.  Public JSON still serializes tuples as ordinary arrays.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=False,
        revalidate_instances="always",
    )


class CandidateAnalysisState(str, Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    STALE = "stale"
    UNRESOLVED = "unresolved"
    NOT_ASSESSED = "not_assessed"


class ComponentState(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    MISSING = "missing"
    NOT_ASSESSED = "not_assessed"


@dataclass(frozen=True, slots=True)
class CandidateComponentRule:
    """Immutable rule entry for one component/state pair."""

    component_id: str
    state: ComponentState
    weight: float
    allowed_values: tuple[float, ...] = ()
    minimum_value: float | None = None
    maximum_value: float | None = None
    no_contribution: bool = False


@dataclass(frozen=True, slots=True)
class CandidateComponentCalculation:
    raw_contribution: float | None
    weighted_contribution: float | None


def _component_rule(
    component_id: str,
    state: ComponentState,
    *,
    allowed_values: tuple[float, ...] = (),
    minimum_value: float | None = None,
    maximum_value: float | None = None,
    no_contribution: bool = False,
) -> CandidateComponentRule:
    return CandidateComponentRule(
        component_id=component_id,
        state=state,
        weight=CANDIDATE_FIXED_COMPONENT_WEIGHTS[component_id],
        allowed_values=allowed_values,
        minimum_value=minimum_value,
        maximum_value=maximum_value,
        no_contribution=no_contribution,
    )


def _no_contribution_rule(component_id: str, state: ComponentState) -> CandidateComponentRule:
    return _component_rule(component_id, state, no_contribution=True)


def _signed_state_rules(component_id: str) -> dict[str, CandidateComponentRule]:
    return {
        ComponentState.POSITIVE.value: _component_rule(component_id, ComponentState.POSITIVE, allowed_values=(1.0,)),
        ComponentState.NEGATIVE.value: _component_rule(component_id, ComponentState.NEGATIVE, allowed_values=(-1.0,)),
        ComponentState.NEUTRAL.value: _component_rule(component_id, ComponentState.NEUTRAL, allowed_values=(0.0,)),
        ComponentState.MISSING.value: _no_contribution_rule(component_id, ComponentState.MISSING),
        ComponentState.NOT_ASSESSED.value: _no_contribution_rule(component_id, ComponentState.NOT_ASSESSED),
    }


def _no_contribution_states(component_id: str) -> dict[str, CandidateComponentRule]:
    return {
        ComponentState.MISSING.value: _no_contribution_rule(component_id, ComponentState.MISSING),
        ComponentState.NOT_ASSESSED.value: _no_contribution_rule(component_id, ComponentState.NOT_ASSESSED),
    }


def _freeze_component_rules(
    rules: dict[str, dict[str, CandidateComponentRule]],
) -> MappingProxyType:
    return MappingProxyType({
        component_id: MappingProxyType(state_rules)
        for component_id, state_rules in rules.items()
    })


_CANDIDATE_COMPONENT_RULES_V037 = _freeze_component_rules({
    "phenotype_match": {
        ComponentState.POSITIVE.value: _component_rule("phenotype_match", ComponentState.POSITIVE, allowed_values=(0.5, 1.0)),
        ComponentState.NEUTRAL.value: _component_rule("phenotype_match", ComponentState.NEUTRAL, allowed_values=(-0.5, 0.0, 0.5)),
        **_no_contribution_states("phenotype_match"),
    },
    "phenotype_specificity": {
        ComponentState.POSITIVE.value: _component_rule("phenotype_specificity", ComponentState.POSITIVE, minimum_value=0.0, maximum_value=1.0),
        **_no_contribution_states("phenotype_specificity"),
    },
    "onset_compatibility": _signed_state_rules("onset_compatibility"),
    "inheritance_compatibility": _signed_state_rules("inheritance_compatibility"),
    "segregation": _signed_state_rules("segregation"),
    "frequency": {
        ComponentState.POSITIVE.value: _component_rule("frequency", ComponentState.POSITIVE, allowed_values=(1.0,)),
        ComponentState.NEGATIVE.value: _component_rule("frequency", ComponentState.NEGATIVE, allowed_values=(-1.0,)),
        **_no_contribution_states("frequency"),
    },
    "consequence": {
        ComponentState.POSITIVE.value: _component_rule("consequence", ComponentState.POSITIVE, allowed_values=(1.0,)),
        ComponentState.NEUTRAL.value: _component_rule("consequence", ComponentState.NEUTRAL, allowed_values=(0.0,)),
        **_no_contribution_states("consequence"),
    },
    "transcript_relevance": _signed_state_rules("transcript_relevance"),
    "gene_disease_validity": {
        ComponentState.POSITIVE.value: _component_rule("gene_disease_validity", ComponentState.POSITIVE, allowed_values=(1.0,)),
        ComponentState.NEGATIVE.value: _component_rule("gene_disease_validity", ComponentState.NEGATIVE, allowed_values=(-1.0,)),
        ComponentState.NEUTRAL.value: _component_rule("gene_disease_validity", ComponentState.NEUTRAL, allowed_values=(0.3,)),
        **_no_contribution_states("gene_disease_validity"),
    },
    "variant_quality": _signed_state_rules("variant_quality"),
    "qc": _signed_state_rules("qc"),
    "coverage_assay_scope": _signed_state_rules("coverage_assay_scope"),
    "supporting_evidence": {
        ComponentState.POSITIVE.value: _component_rule("supporting_evidence", ComponentState.POSITIVE, minimum_value=0.5, maximum_value=1.0),
        **_no_contribution_states("supporting_evidence"),
    },
    "contradicting_evidence": {
        ComponentState.NEGATIVE.value: _component_rule("contradicting_evidence", ComponentState.NEGATIVE, minimum_value=-1.0, maximum_value=-0.5),
        ComponentState.NEUTRAL.value: _component_rule("contradicting_evidence", ComponentState.NEUTRAL, allowed_values=(0.0,)),
        **_no_contribution_states("contradicting_evidence"),
    },
    "missing_information": {
        ComponentState.NEUTRAL.value: _component_rule("missing_information", ComponentState.NEUTRAL, allowed_values=(0.0,)),
        ComponentState.MISSING.value: _no_contribution_rule("missing_information", ComponentState.MISSING),
    },
    "unresolved_uncertainty": {
        ComponentState.NEUTRAL.value: _component_rule("unresolved_uncertainty", ComponentState.NEUTRAL, allowed_values=(0.0,)),
        ComponentState.NOT_ASSESSED.value: _no_contribution_rule("unresolved_uncertainty", ComponentState.NOT_ASSESSED),
    },
})

CANDIDATE_COMPONENT_RULE_REGISTRY = MappingProxyType({
    CANDIDATE_RANKING_RULE_VERSION: _CANDIDATE_COMPONENT_RULES_V037,
})


def calculate_candidate_component(
    *,
    component_version: str,
    component_id: str,
    state: ComponentState | str,
    normalized_value: float | None,
) -> CandidateComponentCalculation:
    """Calculate a component from the immutable v0.37 rule registry."""

    state_value = getattr(state, "value", state)
    version_rules = CANDIDATE_COMPONENT_RULE_REGISTRY.get(component_version)
    if version_rules is None:
        raise ValueError("component versions must use the fixed v0.37 ranking rule")
    component_rules = version_rules.get(component_id)
    if component_rules is None:
        raise ValueError(f"unsupported ranking component: {component_id}")
    rule = component_rules.get(str(state_value))
    if rule is None:
        raise ValueError(f"component state {state_value!r} is not allowed for {component_id}")
    if rule.no_contribution:
        if normalized_value is not None:
            raise ValueError(f"{component_id} {state_value} components must not carry a normalized value")
        return CandidateComponentCalculation(raw_contribution=None, weighted_contribution=None)
    if normalized_value is None:
        raise ValueError(f"{component_id} {state_value} components require a normalized value")
    value = float(normalized_value)
    if value != round(value, 6):
        raise ValueError("component normalized values must be deterministically quantized to six decimals")
    if rule.allowed_values and value not in rule.allowed_values:
        raise ValueError(f"normalized value {value!r} is not allowed for {component_id} {state_value}")
    if rule.minimum_value is not None and value < rule.minimum_value:
        raise ValueError(f"normalized value {value!r} is below the bound for {component_id} {state_value}")
    if rule.maximum_value is not None and value > rule.maximum_value:
        raise ValueError(f"normalized value {value!r} is above the bound for {component_id} {state_value}")
    raw = round(value, 6)
    weighted = round(raw * rule.weight, 6)
    return CandidateComponentCalculation(raw_contribution=raw, weighted_contribution=weighted)


class CandidateReviewStatus(str, Enum):
    RANKED_FOR_REVIEW = "ranked_for_review"
    RETAINED_WEAK_FOR_REVIEW = "retained_weak_for_review"
    RETAINED_NOT_ASSESSED_FOR_REVIEW = "retained_not_assessed_for_review"
    EXCLUDED_WITH_REASON = "excluded_with_reason"
    STALE_REQUIRES_REPLAY = "stale_requires_replay"


class CandidateVariantScope(str, Enum):
    SNV = "snv"
    SMALL_INDEL = "small_indel"
    SYMBOLIC_OUT_OF_SCOPE = "symbolic_out_of_scope"
    STRUCTURAL_VARIANT_OUT_OF_SCOPE = "structural_variant_out_of_scope"
    COPY_NUMBER_OUT_OF_SCOPE = "copy_number_out_of_scope"
    MITOCHONDRIAL_OUT_OF_SCOPE = "mitochondrial_out_of_scope"
    LARGE_INDEL_OUT_OF_SCOPE = "large_indel_out_of_scope"
    REPEAT_OUT_OF_SCOPE = "repeat_out_of_scope"
    MOSAIC_OUT_OF_SCOPE = "mosaic_out_of_scope"
    UNKNOWN = "unknown"


class EvidenceRole(str, Enum):
    SUPPORTING = "supporting"
    CONTRADICTING = "contradicting"
    MISSING = "missing"
    UNRESOLVED = "unresolved"
    CONTEXT_ONLY = "context_only"


class EvidenceState(str, Enum):
    SUPPLIED = "supplied"
    DETERMINISTIC = "deterministic"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    NOT_ASSESSED = "not_assessed"


class FamilyObservationStatus(str, Enum):
    SUPPLIED = "supplied"
    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"
    MISSING = "missing"
    NOT_ASSESSED = "not_assessed"
    CONTRADICTORY = "contradictory"


class RelationshipObservationState(str, Enum):
    SUPPLIED_RELATIONSHIP = "supplied_relationship"
    MISSING_RELATIONSHIP = "missing_relationship"
    NOT_ASSESSED = "not_assessed"
    CONTRADICTORY = "contradictory"


class InheritanceStatementState(str, Enum):
    SUPPLIED_INHERITANCE = "supplied_inheritance"
    NOT_SUPPLIED = "not_supplied"
    NOT_ASSESSED = "not_assessed"
    CONTRADICTORY = "contradictory"


class DeNovoState(str, Enum):
    SUPPLIED_DE_NOVO = "supplied_de_novo"
    DETERMINISTICALLY_SUPPORTED_DE_NOVO = "deterministically_supported_de_novo"
    INSUFFICIENT_INFORMATION = "insufficient_information"
    CONTRADICTORY = "contradictory"
    NOT_ASSESSED = "not_assessed"


class PhaseEvaluation(str, Enum):
    CONFIRMED_TRANS = "confirmed_trans"
    SUPPLIED_TRANS = "supplied_trans"
    DETERMINISTICALLY_SUPPORTED_TRANS = "deterministically_supported_trans"
    CIS = "cis"
    PHASE_UNKNOWN = "phase_unknown"
    INSUFFICIENT_INFORMATION = "insufficient_information"
    NOT_ASSESSED = "not_assessed"


class ExclusionOutcome(str, Enum):
    RETAINED = "retained"
    EXCLUDED = "excluded"


class ExclusionCode(str, Enum):
    SOURCE_RECORD_NOT_FOUND = "source_record_not_found"
    UNSUPPORTED_VARIANT_SCOPE = "unsupported_variant_scope"
    OUTSIDE_SUPPORTED_SNV_SMALL_INDEL_SCOPE = "outside_supported_snv_small_indel_scope"
    OUTSIDE_REPORTABLE_RANGE = "outside_reportable_range"
    INADEQUATE_COVERAGE = "inadequate_coverage"
    EXPLICIT_ASSAY_EXCLUSION = "explicit_assay_exclusion"
    VERSIONED_RULE_EXCLUSION = "versioned_rule_exclusion"
    STALE_RESULT_PACKAGE = "stale_result_package"
    STALE_PHENOTYPE_SNAPSHOT = "stale_phenotype_snapshot"
    STALE_FAMILY_SNAPSHOT = "stale_family_snapshot"
    STALE_ASSAY_COVERAGE_SNAPSHOT = "stale_assay_coverage_snapshot"
    STALE_RANKING_RULE = "stale_ranking_rule"
    INVALID_SOURCE_BINDING = "invalid_source_binding"
    UNAVAILABLE_ADAPTER = "unavailable_adapter"


class FamilyShape(str, Enum):
    SINGLETON = "singleton"
    DUO = "duo"
    TRIO = "trio"
    EXTENDED_FAMILY = "extended_family"
    NOT_ASSESSED = "not_assessed"


class RuntimeMetadata(CandidateFrozenModel):
    """Runtime-only fields are deliberately outside checksum-sensitive identity."""

    generated_at_utc: str = "not_recorded"
    runtime_id: str = "deterministic"
    timestamp_scope: Literal["runtime_metadata_only"] = "runtime_metadata_only"


class ProvenanceReference(CandidateFrozenModel):
    source_id: BoundedIdentifier
    source_type: str = Field(min_length=1, max_length=160)
    source_path: str | None = Field(default=None, max_length=300)
    source_version: str | None = Field(default=None, max_length=120)
    source_identity_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    package_identity_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    manifest_identity_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)


class ComponentWeight(CandidateFrozenModel):
    component_id: BoundedIdentifier
    component_version: str = Field(min_length=1, max_length=120)
    weight: StrictFiniteFloat
    priority: int = Field(ge=0, le=100)
    rationale: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def is_fixed_registry_entry(self) -> "ComponentWeight":
        expected = CANDIDATE_FIXED_COMPONENT_WEIGHTS.get(self.component_id)
        if expected is None:
            raise ValueError(f"unsupported ranking component: {self.component_id}")
        expected_priority = tuple(CANDIDATE_FIXED_COMPONENT_WEIGHTS).index(self.component_id) + 1
        if self.component_version != CANDIDATE_RANKING_RULE_VERSION:
            raise ValueError("component versions must use the fixed v0.37 ranking rule")
        if self.weight != expected or self.priority != expected_priority:
            raise ValueError("component weights and priorities are fixed by the v0.37 registry")
        if self.rationale != _fixed_component_rationale(self.component_id):
            raise ValueError("component rationales are fixed by the v0.37 registry")
        return self


class FilteringRule(CandidateFrozenModel):
    rule_id: BoundedIdentifier
    rule_version: str = Field(min_length=1, max_length=120)
    rule: str = Field(min_length=1, max_length=600)
    outcome: Literal["retain", "exclude", "retain_not_assessed"]
    explanation: str = Field(min_length=1, max_length=1000)


class CandidateRankingRule(CandidateFrozenModel):
    rule_id: Literal["candidate_prioritization"] = "candidate_prioritization"
    rule_version: Literal["insilicopop-candidate-ranking-0.37.0"] = CANDIDATE_RANKING_RULE_VERSION
    weight_version: Literal["insilicopop-candidate-ranking-weights-0.37.0"] = CANDIDATE_RANKING_WEIGHT_VERSION
    support_threshold: StrictFiniteFloat = Field(default=CANDIDATE_FIXED_SUPPORT_THRESHOLD, ge=-100.0, le=100.0)
    tie_epsilon: StrictFiniteFloat = Field(default=CANDIDATE_FIXED_TIE_EPSILON, ge=0.0, le=1.0)
    component_weights: tuple[ComponentWeight, ...] = Field(default_factory=tuple, max_length=100)
    filtering_rules: tuple[FilteringRule, ...] = Field(default_factory=tuple, max_length=100)

    @model_validator(mode="after")
    def fixed_rule_registry(self) -> "CandidateRankingRule":
        if self.support_threshold != CANDIDATE_FIXED_SUPPORT_THRESHOLD:
            raise ValueError("support threshold is fixed by the v0.37 ranking registry")
        if self.tie_epsilon != CANDIDATE_FIXED_TIE_EPSILON:
            raise ValueError("tie epsilon is fixed by the v0.37 ranking registry")
        expected_ids = tuple(CANDIDATE_FIXED_COMPONENT_WEIGHTS)
        actual_ids = tuple(item.component_id for item in self.component_weights)
        if actual_ids != expected_ids:
            raise ValueError("ranking components must match the fixed v0.37 registry in priority order")
        expected_filter_ids = (
            "supported_variant_scope",
            "assay_reportable_scope",
            "candidate_context_exclusion",
        )
        if tuple(item.rule_id for item in self.filtering_rules) != expected_filter_ids:
            raise ValueError("filtering rules must match the fixed v0.37 registry")
        if any(item.rule_version != CANDIDATE_RANKING_RULE_VERSION for item in self.filtering_rules):
            raise ValueError("filtering rules must use the fixed v0.37 ranking rule")
        return self


class CandidateSourceRecordIdentity(CandidateFrozenModel):
    candidate_schema_version: Literal["0.37"] = CANDIDATE_ANALYSIS_SCHEMA_VERSION
    gateway_record_id: BoundedIdentifier
    source_record_id: BoundedIdentifier
    source_record_key: BoundedIdentifier
    package_id: BoundedIdentifier
    package_version: str = Field(min_length=1, max_length=120)
    package_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    manifest_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    invocation_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    source_record_sha256: str = Field(pattern=SHA256_PATTERN)
    source_file: str = Field(min_length=1, max_length=300)
    chromosome: str = Field(min_length=1, max_length=80)
    position: int = Field(ge=1)
    reference_allele: str = Field(min_length=1, max_length=1_000_000)
    alternate_allele: str = Field(min_length=1, max_length=1_000_000)
    variant_scope: CandidateVariantScope
    source_alt_index: int = Field(ge=1)
    gene: str | None = Field(default=None, max_length=160)
    transcript: str | None = Field(default=None, max_length=240)


class CandidateSourceAlleleKey(CandidateFrozenModel):
    """Complete v0.36 package-bound identity for one selected source allele."""

    package_id: BoundedIdentifier
    package_version: str = Field(min_length=1, max_length=120)
    package_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    source_record_id: BoundedIdentifier
    source_record_key: BoundedIdentifier
    source_record_sha256: str = Field(pattern=SHA256_PATTERN)
    chromosome: str = Field(min_length=1, max_length=80)
    position: int = Field(ge=1)
    reference_allele: str = Field(min_length=1, max_length=1_000_000)
    alternate_allele: str = Field(min_length=1, max_length=1_000_000)
    source_alt_index: int = Field(ge=1)


class CandidateIdentity(CandidateFrozenModel):
    candidate_id: BoundedIdentifier
    stable_candidate_id: BoundedIdentifier
    source_record: CandidateSourceRecordIdentity
    supplied_candidate_id: BoundedIdentifier | None = None
    supplied_representation: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def canonical_source_binding(self) -> "CandidateIdentity":
        expected = canonical_candidate_id(self.source_record)
        expected_stable = stable_candidate_id(self.source_record)
        if self.candidate_id != expected:
            raise ValueError("candidate ID is not derived from the canonical v0.37 source binding")
        if self.stable_candidate_id != expected_stable:
            raise ValueError("stable candidate ID is not derived from the canonical v0.37 source binding")
        return self


class GeneTranscriptContext(CandidateFrozenModel):
    gene: str | None = Field(default=None, max_length=160)
    transcript: str | None = Field(default=None, max_length=240)
    supplied_gene: str | None = Field(default=None, max_length=160)
    supplied_transcript: str | None = Field(default=None, max_length=240)
    consequence: str | None = Field(default=None, max_length=500)
    transcript_relevance: ComponentState = ComponentState.NOT_ASSESSED
    gene_disease_validity: ComponentState = ComponentState.NOT_ASSESSED
    validity_label_supplied: str | None = Field(default=None, max_length=160)
    provenance: tuple[ProvenanceReference, ...] = Field(default_factory=tuple, max_length=50)


class VariantGenotypeContext(CandidateFrozenModel):
    chromosome: str = Field(min_length=1, max_length=80)
    position: int = Field(ge=1)
    reference_allele: str = Field(min_length=1, max_length=1_000_000)
    alternate_allele: str = Field(min_length=1, max_length=1_000_000)
    variant_scope: CandidateVariantScope
    sample_names: tuple[str, ...] = Field(default_factory=tuple, max_length=1000)
    zygosity: str | None = Field(default=None, max_length=120)
    phase_state: str = Field(default="unknown", max_length=80)
    quality: str | None = Field(default=None, max_length=120)
    filter_status: str | None = Field(default=None, max_length=160)
    source_state: Literal["supplied", "out_of_scope", "not_assessed"] = "supplied"


class PhenotypeMatchSummary(CandidateFrozenModel):
    exact_hpo_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=500)
    related_hpo_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=500)
    negated_hpo_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=500)
    specificity_state: ComponentState = ComponentState.NOT_ASSESSED
    specificity_value_supplied: StrictFiniteUnitFloat | None = None
    onset_state: ComponentState = ComponentState.NOT_ASSESSED
    matched_term_count: int = Field(ge=0)
    explanation: str = Field(min_length=1, max_length=2000)
    provenance: tuple[ProvenanceReference, ...] = Field(default_factory=tuple, max_length=100)


class InheritanceCompatibilitySummary(CandidateFrozenModel):
    state: ComponentState
    x_linked_state: ComponentState = ComponentState.NOT_ASSESSED
    supplied_inheritance_statements: tuple[str, ...] = Field(default_factory=tuple, max_length=50)
    deterministic_compatibility: str = Field(min_length=1, max_length=120)
    segregation_state: ComponentState = ComponentState.NOT_ASSESSED
    de_novo_state: DeNovoState = DeNovoState.NOT_ASSESSED
    phase_state: PhaseEvaluation = PhaseEvaluation.NOT_ASSESSED
    compound_heterozygosity_state: PhaseEvaluation = PhaseEvaluation.NOT_ASSESSED
    compound_partner_candidate_id: BoundedIdentifier | None = None
    compound_pair_identity: BoundedIdentifier | None = None
    missing_relative_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=100)
    low_quality_member_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=100)
    contradiction_codes: tuple[str, ...] = Field(default_factory=tuple, max_length=100)
    explanation: str = Field(min_length=1, max_length=3000)
    provenance: tuple[ProvenanceReference, ...] = Field(default_factory=tuple, max_length=100)


class FrequencyContext(CandidateFrozenModel):
    # Strict float validation intentionally accepts native integer 0 and 1,
    # while excluding bool explicitly because bool is an int subclass.
    frequency_supplied: StrictFiniteUnitFloat | None = None
    source_name: str | None = Field(default=None, max_length=200)
    source_version: str | None = Field(default=None, max_length=120)
    source_scope: str | None = Field(default=None, max_length=200)
    indian_population_source: bool = False
    absence_from_dataset_is_not_evidence: Literal[True] = True
    explanation: str = Field(min_length=1, max_length=1200)
    provenance: tuple[ProvenanceReference, ...] = Field(default_factory=tuple, max_length=50)


class ConsequenceContext(CandidateFrozenModel):
    consequence_supplied: str | None = Field(default=None, max_length=500)
    transcript_relevance: ComponentState = ComponentState.NOT_ASSESSED
    explanation: str = Field(min_length=1, max_length=1200)
    provenance: tuple[ProvenanceReference, ...] = Field(default_factory=tuple, max_length=50)


class QualityCoverageAssayContext(CandidateFrozenModel):
    variant_quality_state: ComponentState = ComponentState.NOT_ASSESSED
    qc_state: ComponentState = ComponentState.NOT_ASSESSED
    coverage_state: ComponentState = ComponentState.NOT_ASSESSED
    assay_scope_state: ComponentState = ComponentState.NOT_ASSESSED
    poor_coverage_region_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=500)
    outside_reportable_range: bool = False
    assay_blind_spot_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=500)
    warnings: tuple[str, ...] = Field(default_factory=tuple, max_length=500)
    explanation: str = Field(min_length=1, max_length=3000)
    provenance: tuple[ProvenanceReference, ...] = Field(default_factory=tuple, max_length=100)


class CandidateEvidence(CandidateFrozenModel):
    evidence_id: BoundedIdentifier
    candidate_id: BoundedIdentifier
    role: EvidenceRole
    state: EvidenceState
    statement: str = Field(min_length=1, max_length=2000)
    source: ProvenanceReference


class MissingInformation(CandidateFrozenModel):
    missing_id: BoundedIdentifier
    candidate_id: BoundedIdentifier | None = None
    category: str = Field(min_length=1, max_length=120)
    information_needed: str = Field(min_length=1, max_length=1200)
    source: tuple[ProvenanceReference, ...] = Field(default_factory=tuple, max_length=50)
    human_review_required: Literal[True] = True


class UnresolvedUncertainty(CandidateFrozenModel):
    uncertainty_id: BoundedIdentifier
    candidate_id: BoundedIdentifier | None = None
    category: str = Field(min_length=1, max_length=120)
    statement: str = Field(min_length=1, max_length=1500)
    reason: str = Field(min_length=1, max_length=1200)
    source: tuple[ProvenanceReference, ...] = Field(default_factory=tuple, max_length=50)
    human_review_required: Literal[True] = True


class FamilySegregationObservation(CandidateFrozenModel):
    observation_id: BoundedIdentifier
    candidate_id: BoundedIdentifier
    source_record_id: BoundedIdentifier | None = None
    family_member_id: BoundedIdentifier
    sample_name: str | None = Field(default=None, max_length=300)
    selected_alt_index: int | None = Field(default=None, ge=1)
    observed_alt_presence_state: Literal["present", "absent", "unknown", "not_assessed"] = "not_assessed"
    observed_genotype_quality: StrictFiniteFloat | None = None
    relationship_state: RelationshipObservationState
    relationship_type: str | None = Field(default=None, max_length=120)
    affected_status: str
    presence_state: str
    zygosity: str
    genotype_quality_state: ComponentState
    supplied_inheritance_state: InheritanceStatementState
    deterministic_compatibility: ComponentState
    supplied_de_novo_state: DeNovoState
    phase_state: PhaseEvaluation
    compound_heterozygosity_state: PhaseEvaluation
    status: FamilyObservationStatus
    explanation: str = Field(min_length=1, max_length=2400)
    provenance: tuple[ProvenanceReference, ...] = Field(default_factory=tuple, max_length=100)


class FamilySegregationSummary(CandidateFrozenModel):
    family_shape: FamilyShape
    member_count: int = Field(ge=0)
    biological_parent_relationship_count: int = Field(ge=0)
    tested_member_count: int = Field(ge=0)
    affected_member_count: int = Field(ge=0)
    missing_relative_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=100)
    low_quality_member_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=100)
    supplied_relationship_count: int = Field(ge=0)
    supplied_inheritance_statement_count: int = Field(ge=0)
    observations: tuple[FamilySegregationObservation, ...] = Field(default_factory=tuple, max_length=5000)
    no_relationship_inference: Literal[True] = True


class ExclusionTrace(CandidateFrozenModel):
    exclusion_id: BoundedIdentifier
    candidate_id: BoundedIdentifier
    input_state: str = Field(min_length=1, max_length=160)
    rule_id: BoundedIdentifier
    rule_version: str = Field(min_length=1, max_length=120)
    rule_or_threshold: str = Field(min_length=1, max_length=1000)
    result: ExclusionOutcome
    code: ExclusionCode
    reason: str = Field(min_length=1, max_length=2000)
    provenance: tuple[ProvenanceReference, ...] = Field(default_factory=tuple, max_length=100)
    timestamp_utc: str = "runtime_metadata_not_recorded"


class CandidateRankingComponent(CandidateFrozenModel):
    component_id: BoundedIdentifier
    component_version: str = Field(min_length=1, max_length=120)
    display_name: str = Field(min_length=1, max_length=160)
    supplied_input: str = Field(min_length=1, max_length=4000)
    normalized_input: str | None = Field(default=None, max_length=4000)
    deterministic_rule: str = Field(min_length=1, max_length=2000)
    state: ComponentState
    normalized_value: StrictFiniteFloat | None = None
    raw_contribution: StrictFiniteFloat | None = None
    numerical_contribution: StrictFiniteFloat | None = None
    weight: StrictFiniteFloat | None = None
    source: tuple[ProvenanceReference, ...] = Field(default_factory=tuple, max_length=100)
    explanation: str = Field(min_length=1, max_length=3000)

    @model_validator(mode="after")
    def contribution_is_visible(self) -> "CandidateRankingComponent":
        expected_weight = CANDIDATE_FIXED_COMPONENT_WEIGHTS.get(self.component_id)
        if expected_weight is None:
            raise ValueError(f"unsupported ranking component: {self.component_id}")
        if self.component_version != CANDIDATE_RANKING_RULE_VERSION:
            raise ValueError("component versions must use the fixed v0.37 ranking rule")
        if self.weight != expected_weight:
            raise ValueError("component weights are fixed by the v0.37 registry")
        if self.weight is None:
            raise ValueError("every persisted component requires its fixed visible weight")
        expected = calculate_candidate_component(
            component_version=self.component_version,
            component_id=self.component_id,
            state=self.state,
            normalized_value=self.normalized_value,
        )
        if self.raw_contribution != expected.raw_contribution:
            raise ValueError("raw component contribution does not match the fixed v0.37 rule")
        if self.numerical_contribution != expected.weighted_contribution:
            raise ValueError("weighted component contribution does not match the fixed v0.37 rule")
        return self


class CandidateAnalysisRecord(CandidateFrozenModel):
    candidate_identity: CandidateIdentity
    gene_transcript_context: GeneTranscriptContext
    variant_genotype_context: VariantGenotypeContext
    phenotype_match: PhenotypeMatchSummary
    inheritance_compatibility: InheritanceCompatibilitySummary
    frequency_context: FrequencyContext
    consequence_context: ConsequenceContext
    quality_coverage_assay: QualityCoverageAssayContext
    supporting_evidence: tuple[CandidateEvidence, ...] = Field(default_factory=tuple, max_length=1000)
    contradicting_evidence: tuple[CandidateEvidence, ...] = Field(default_factory=tuple, max_length=1000)
    missing_information: tuple[MissingInformation, ...] = Field(default_factory=tuple, max_length=1000)
    unresolved_uncertainties: tuple[UnresolvedUncertainty, ...] = Field(default_factory=tuple, max_length=1000)
    family_segregation_observations: tuple[FamilySegregationObservation, ...] = Field(default_factory=tuple, max_length=5000)
    ranking_components: tuple[CandidateRankingComponent, ...] = Field(default_factory=tuple, max_length=100)
    aggregate_score: StrictFiniteFloat | None = None
    deterministic_rank: int | None = Field(default=None, ge=1)
    tied: bool = False
    tie_group_id: BoundedIdentifier | None = None
    tie_break_explanation: str = Field(min_length=1, max_length=1200)
    presentation_order_note: str = (
        "Stable presentation order is a deterministic review aid and is not a claim of scientific superiority."
    )
    review_status: CandidateReviewStatus
    exclusion_history: tuple[ExclusionTrace, ...] = Field(default_factory=tuple, max_length=100)
    human_review_required: Literal[True] = True


class ExcludedCandidate(CandidateFrozenModel):
    candidate_identity: CandidateIdentity | None = None
    candidate_id: BoundedIdentifier
    exclusion_history: tuple[ExclusionTrace, ...] = Field(min_length=1, max_length=100)
    missing_information: tuple[MissingInformation, ...] = Field(default_factory=tuple, max_length=1000)
    unresolved_uncertainties: tuple[UnresolvedUncertainty, ...] = Field(default_factory=tuple, max_length=1000)
    human_review_required: Literal[True] = True


class NegativeUnresolvedResult(CandidateFrozenModel):
    analysis_scope: str = Field(min_length=1, max_length=2000)
    assessed_regions: tuple[str, ...] = Field(default_factory=tuple, max_length=5000)
    unassessed_regions: tuple[str, ...] = Field(default_factory=tuple, max_length=5000)
    coverage_gaps: tuple[str, ...] = Field(default_factory=tuple, max_length=5000)
    assay_blind_spots: tuple[str, ...] = Field(default_factory=tuple, max_length=5000)
    unsupported_result_types: tuple[str, ...] = Field(default_factory=tuple, max_length=500)
    unavailable_adapters: tuple[str, ...] = Field(default_factory=tuple, max_length=500)
    retained_candidate_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=5000)
    excluded_candidate_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=5000)
    excluded_candidate_reasons: tuple[str, ...] = Field(default_factory=tuple, max_length=5000)
    weak_candidate_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=5000)
    contradictory_candidate_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=5000)
    missing_information: tuple[MissingInformation, ...] = Field(default_factory=tuple, max_length=5000)
    unresolved_questions: tuple[UnresolvedUncertainty, ...] = Field(default_factory=tuple, max_length=5000)
    human_review_questions: tuple[str, ...] = Field(default_factory=tuple, max_length=5000)
    no_sufficiently_supported_candidate: bool
    required_no_candidate_wording: Literal[
        "No sufficiently supported candidate was identified within the supplied analysis scope."
    ] = CANDIDATE_REQUIRED_UNRESOLVED_WORDING
    summary: Literal[
        "No sufficiently supported candidate was identified within the supplied analysis scope."
    ] = CANDIDATE_REQUIRED_UNRESOLVED_WORDING
    human_review_required: Literal[True] = True

    @model_validator(mode="after")
    def prohibit_absolute_negative_language(self) -> "NegativeUnresolvedResult":
        text = " ".join((*self.human_review_questions, self.summary))
        if any(_contains_absolute_negative_language(value) for value in (*self.human_review_questions, self.summary)):
            raise ValueError("absolute-negative result language is prohibited")
        return self


class CandidateAnalysisRequest(CandidateFrozenModel):
    schema_version: Literal["0.37"] = CANDIDATE_ANALYSIS_SCHEMA_VERSION
    ranking_rule_version: str = CANDIDATE_RANKING_RULE_VERSION
    ranking_weight_version: str = CANDIDATE_RANKING_WEIGHT_VERSION
    support_threshold: StrictFiniteFloat | None = Field(default=None, ge=-100.0, le=100.0)
    tie_epsilon: StrictFiniteFloat | None = Field(default=None, ge=0.0, le=1.0)
    candidate_contexts: tuple["CandidateContextInput", ...] = Field(
        default_factory=tuple,
        max_length=5000,
        validation_alias=AliasChoices("candidate_contexts", "candidate_overrides", "candidate_inputs"),
    )
    evidence: tuple["CandidateEvidenceInput", ...] = Field(
        default_factory=tuple,
        max_length=10_000,
        validation_alias=AliasChoices("evidence", "candidate_evidence", "evidence_inputs"),
    )
    phenotype_relations: tuple["SuppliedHpoRelation", ...] = Field(default_factory=tuple, max_length=5000)
    family_sample_bindings: tuple["FamilySampleBindingInput", ...] = Field(default_factory=tuple, max_length=5000)
    expected_result_package_identity_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    expected_phenotype_snapshot_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    expected_family_snapshot_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    expected_assay_coverage_snapshot_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    human_review_required: Literal[True] = True

    @model_validator(mode="after")
    def unique_context_ids(self) -> "CandidateAnalysisRequest":
        if self.support_threshold is not None and self.support_threshold != CANDIDATE_FIXED_SUPPORT_THRESHOLD:
            raise ValueError("support threshold is fixed by the v0.37 ranking registry")
        if self.tie_epsilon is not None and self.tie_epsilon != CANDIDATE_FIXED_TIE_EPSILON:
            raise ValueError("tie epsilon is fixed by the v0.37 ranking registry")
        ids = [item.candidate_id for item in self.candidate_contexts]
        if len(ids) != len(set(ids)):
            raise ValueError("candidate context IDs must be unique")
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("candidate evidence IDs must be unique")
        member_ids = [item.family_member_id for item in self.family_sample_bindings]
        if len(member_ids) != len(set(member_ids)):
            raise ValueError("family sample bindings must contain one binding per family member")
        sample_names = [item.sample_name for item in self.family_sample_bindings]
        if len(sample_names) != len(set(sample_names)):
            raise ValueError("family sample bindings must use distinct sample names")
        return self

    _canonical_contexts = field_validator("candidate_contexts", mode="before")(
        lambda value: _canonical_input_items(value, key_fields=("source_record_id", "candidate_id"))
    )
    _canonical_evidence = field_validator("evidence", mode="before")(
        lambda value: _canonical_input_items(value, key_fields=("candidate_id", "evidence_id"))
    )
    _canonical_relations = field_validator("phenotype_relations", mode="before")(
        lambda value: _canonical_input_items(
            value,
            key_fields=("source_hpo_id", "target_hpo_id", "relation", "source_id"),
        )
    )
    _canonical_bindings = field_validator("family_sample_bindings", mode="before")(
        lambda value: _canonical_input_items(value, key_fields=("family_member_id", "sample_name"))
    )


class CandidateContextInput(CandidateFrozenModel):
    candidate_id: BoundedIdentifier
    source_record_id: BoundedIdentifier | None = Field(default=None)
    source_record_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    chromosome: str | None = Field(default=None, max_length=80)
    position: int | None = Field(default=None, ge=1)
    reference_allele: str | None = Field(default=None, max_length=1_000_000)
    alternate_allele: str | None = Field(default=None, max_length=1_000_000)
    source_alt_index: int | None = Field(default=None, ge=1)
    gene: str | None = Field(default=None, max_length=160)
    transcript: str | None = Field(default=None, max_length=240)
    consequence: str | None = Field(default=None, max_length=500)
    transcript_relevance: Literal["relevant", "not_relevant", "unknown", "not_assessed"] = "not_assessed"
    gene_disease_validity: Literal["established", "limited", "conflicting", "not_supplied", "not_assessed"] = "not_assessed"
    phenotype_hpo_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=500)
    phenotype_specificity_score: StrictFiniteUnitFloat | None = None
    onset_compatibility: Literal["compatible", "incompatible", "unknown", "not_assessed"] = "not_assessed"
    population_frequency: StrictFiniteUnitFloat | None = None
    population_source_name: str | None = Field(default=None, max_length=200)
    population_source_version: str | None = Field(default=None, max_length=120)
    population_source_scope: str | None = Field(default=None, max_length=200)
    indian_population_source: bool = False
    zygosity: str | None = Field(default=None, max_length=120)
    inheritance_context_state: Literal["supplied", "missing", "not_assessed"] = "not_assessed"
    supplied_inheritance: tuple[str, ...] = Field(default_factory=tuple, max_length=50)
    supplied_phase: PhaseEvaluation = PhaseEvaluation.NOT_ASSESSED
    phase_evidence: str | None = Field(default=None, max_length=1200)
    compound_heterozygosity_partner_candidate_id: BoundedIdentifier | None = None
    compound_gene_context: BoundedIdentifier | None = None
    x_linked_compatibility: Literal["compatible", "incompatible", "not_assessed"] = "not_assessed"
    supplied_de_novo: bool | None = None
    quality_state: Literal["positive", "negative", "neutral", "missing", "not_assessed"] = "not_assessed"
    qc_state: Literal["positive", "negative", "neutral", "missing", "not_assessed"] = "not_assessed"
    exclusion_rule_id: BoundedIdentifier | None = None
    exclusion_rule_version: str | None = Field(default=None, max_length=120)
    exclusion_rule_reason: str | None = Field(default=None, max_length=1200)
    provenance: tuple[ProvenanceReference, ...] = Field(default_factory=tuple, max_length=100)

    @model_validator(mode="after")
    def exclusion_rule_is_versioned(self) -> "CandidateContextInput":
        if self.exclusion_rule_id and not self.exclusion_rule_version:
            raise ValueError("candidate exclusion rules require an explicit rule version")
        hpo_ids = tuple(self.phenotype_hpo_ids)
        if len(hpo_ids) != len(set(hpo_ids)):
            raise ValueError("candidate HPO identifiers must not contain duplicates")
        return self

    _canonical_hpo_ids = field_validator("phenotype_hpo_ids", mode="before")(
        lambda value: tuple(sorted(str(item) for item in (value or ())))
    )


class CandidateEvidenceInput(CandidateFrozenModel):
    evidence_id: BoundedIdentifier
    candidate_id: BoundedIdentifier
    role: EvidenceRole
    statement: str = Field(min_length=1, max_length=2000)
    source_id: BoundedIdentifier
    source_type: str = Field(min_length=1, max_length=160)
    source_version: str | None = Field(default=None, max_length=120)
    source_reference: str | None = Field(default=None, max_length=300)


class SuppliedHpoRelation(CandidateFrozenModel):
    source_hpo_id: str = Field(pattern=r"^HP:\d{7}$")
    target_hpo_id: str = Field(pattern=r"^HP:\d{7}$")
    relation: Literal["is_a", "part_of", "related"]
    ontology_version: str = Field(min_length=1, max_length=120)
    source_id: BoundedIdentifier
    source_type: str = Field(min_length=1, max_length=160)


class FamilySampleBindingInput(CandidateFrozenModel):
    family_member_id: BoundedIdentifier
    sample_name: str = Field(min_length=1, max_length=300)
    package_id: BoundedIdentifier
    source_id: BoundedIdentifier
    genotype_quality_threshold: StrictFiniteFloat | None = Field(default=None, ge=0.0, le=1000.0)
    genotype_quality_state: Literal["positive", "negative", "missing", "not_assessed", "not_supplied"] = "not_supplied"

    @model_validator(mode="after")
    def fixed_quality_threshold(self) -> "FamilySampleBindingInput":
        if self.genotype_quality_threshold is not None and self.genotype_quality_threshold != CANDIDATE_FIXED_FAMILY_GQ_THRESHOLD:
            raise ValueError("family genotype-quality threshold is fixed by the v0.37 registry")
        return self


class CandidateAnalysisResult(CandidateFrozenModel):
    schema_version: Literal["0.37"] = CANDIDATE_ANALYSIS_SCHEMA_VERSION
    algorithm_version: Literal["insilicopop-candidate-analysis-0.37.0"] = CANDIDATE_ANALYSIS_ALGORITHM_VERSION
    research_use_only: Literal[True] = True
    pseudonymous_case_id: BoundedIdentifier
    analysis_status: CandidateAnalysisState
    ranking_rule: CandidateRankingRule
    ranked_candidates: tuple[CandidateAnalysisRecord, ...] = Field(default_factory=tuple, max_length=5000)
    excluded_candidates: tuple[ExcludedCandidate, ...] = Field(default_factory=tuple, max_length=5000)
    exclusion_trace: tuple[ExclusionTrace, ...] = Field(default_factory=tuple, max_length=10_000)
    family_segregation: FamilySegregationSummary
    negative_unresolved_result: NegativeUnresolvedResult
    source_record_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=10_000)
    v036_package_id: str | None = None
    v036_package_identity_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    v036_manifest_identity_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    v036_invocation_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=500)
    phenotype_snapshot_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    family_snapshot_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    assay_coverage_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    evidence_input_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    ranking_input_canonical_json: str = Field(min_length=2, max_length=5_000_000)
    ranking_input_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    ranking_output_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    analysis_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    result_integrity_sha256: str = Field(pattern=SHA256_PATTERN, default="0" * 64)
    stale_input_codes: tuple[str, ...] = Field(default_factory=tuple, max_length=100)
    missing_information: tuple[MissingInformation, ...] = Field(default_factory=tuple, max_length=10_000)
    unresolved_uncertainties: tuple[UnresolvedUncertainty, ...] = Field(default_factory=tuple, max_length=10_000)
    runtime_metadata: RuntimeMetadata = Field(default_factory=RuntimeMetadata)
    human_review_required: Literal[True] = True
    draft_not_clinically_approved: Literal[True] = True
    diagnosis_made: Literal[False] = False
    treatment_recommendation_made: Literal[False] = False
    final_acmg_classification_made: Literal[False] = False
    clinical_sign_out_made: Literal[False] = False
    external_api_call_made: Literal[False] = False
    external_llm_called: Literal[False] = False
    external_tools_executed: Literal[False] = False
    autonomous_test_order_placed: Literal[False] = False

    @model_validator(mode="after")
    def stable_candidate_order_and_safety(self) -> "CandidateAnalysisResult":
        ranks = [item.deterministic_rank for item in self.ranked_candidates]
        if any(rank is None for rank in ranks):
            raise ValueError("ranked candidate records require deterministic ranks")
        if ranks != sorted(ranks):
            raise ValueError("ranked candidates must be ordered by deterministic rank")
        if len({item.candidate_identity.candidate_id for item in self.ranked_candidates}) != len(self.ranked_candidates):
            raise ValueError("ranked candidate IDs must be unique")
        if self.result_integrity_sha256 == "0" * 64:
            raise ValueError("candidate analysis integrity digest is required for a persisted result")
        self.verify_integrity()
        return self

    @classmethod
    def verified_load(
        cls,
        payload: dict[str, Any] | "CandidateAnalysisResult",
        *,
        persisted_checksum: str | None = None,
    ) -> "CandidateAnalysisResult":
        result = payload if isinstance(payload, cls) else cls.model_validate(payload)
        result.verify_integrity(persisted_checksum=persisted_checksum)
        return result

    def verify_integrity(self, *, persisted_checksum: str | None = None) -> None:
        if persisted_checksum is not None and persisted_checksum != self.result_integrity_sha256:
            raise ValueError("candidate analysis persisted checksum does not match the result integrity digest")
        try:
            input_payload = json.loads(self.ranking_input_canonical_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("candidate analysis ranking input payload is not valid canonical JSON") from exc
        if canonical_json(input_payload) != self.ranking_input_canonical_json:
            raise ValueError("candidate analysis ranking input payload is not canonical")
        if sha256_hex(input_payload) != self.ranking_input_identity_sha256:
            raise ValueError("candidate analysis ranking input identity does not match its canonical payload")

        expected_component_ids = tuple(CANDIDATE_FIXED_COMPONENT_WEIGHTS)
        for record in self.ranked_candidates:
            component_ids = tuple(item.component_id for item in record.ranking_components)
            if component_ids != expected_component_ids:
                raise ValueError("candidate ranking components do not match the fixed v0.37 registry")
            for component in record.ranking_components:
                expected_weight = CANDIDATE_FIXED_COMPONENT_WEIGHTS[component.component_id]
                if component.weight != expected_weight:
                    raise ValueError("candidate component weight does not match the fixed v0.37 registry")
                expected_component = calculate_candidate_component(
                    component_version=component.component_version,
                    component_id=component.component_id,
                    state=component.state,
                    normalized_value=component.normalized_value,
                )
                if component.raw_contribution != expected_component.raw_contribution:
                    raise ValueError("candidate raw component contribution does not recompute from normalized input")
                if component.numerical_contribution != expected_component.weighted_contribution:
                    raise ValueError("candidate weighted component contribution does not recompute from normalized input")
            score = round(
                sum(item.numerical_contribution or 0.0 for item in record.ranking_components),
                6,
            )
            if record.aggregate_score is None or record.aggregate_score != score:
                raise ValueError("candidate aggregate score does not recompute from visible components")
        expected_ranked = sorted(
            self.ranked_candidates,
            key=lambda item: (
                -(item.aggregate_score if item.aggregate_score is not None else float("-inf")),
                item.candidate_identity.candidate_id,
                item.candidate_identity.source_record.source_record_id,
            ),
        )
        if tuple(expected_ranked) != self.ranked_candidates:
            raise ValueError("ranked candidates are not in deterministic score and canonical-ID order")
        expected_rank = 0
        index = 0
        while index < len(expected_ranked):
            anchor = expected_ranked[index].aggregate_score
            end = index + 1
            while end < len(expected_ranked) and abs((expected_ranked[end].aggregate_score or 0.0) - (anchor or 0.0)) <= self.ranking_rule.tie_epsilon:
                end += 1
            group = expected_ranked[index:end]
            expected_rank = index + 1
            tie_group = (
                safe_candidate_id(
                    "tie-group",
                    CANDIDATE_RANKING_RULE_VERSION,
                    round(anchor or 0.0, 6),
                    tuple(item.candidate_identity.candidate_id for item in group),
                )
                if len(group) > 1
                else None
            )
            for item in group:
                if item.deterministic_rank != expected_rank:
                    raise ValueError("candidate rank does not recompute from deterministic tie groups")
                if item.tied != (len(group) > 1) or item.tie_group_id != tie_group:
                    raise ValueError("candidate tie membership does not match its deterministic tie group")
            index = end

        output_payload = {
            "ranked_candidates": [item.model_dump(mode="json") for item in self.ranked_candidates],
            "excluded_candidates": [item.model_dump(mode="json") for item in self.excluded_candidates],
            "exclusion_trace": [item.model_dump(mode="json") for item in self.exclusion_trace],
            "negative_unresolved_result": self.negative_unresolved_result.model_dump(mode="json"),
            "rule": self.ranking_rule.model_dump(mode="json"),
        }
        if sha256_hex(output_payload) != self.ranking_output_identity_sha256:
            raise ValueError("candidate ranking output identity does not match the ranked output")
        analysis_payload = self.model_dump(
            mode="json",
            exclude={"analysis_identity_sha256", "result_integrity_sha256", "runtime_metadata"},
        )
        if sha256_hex(analysis_payload) != self.analysis_identity_sha256:
            raise ValueError("candidate analysis identity does not match the verified result payload")
        integrity_payload = self.model_dump(
            mode="json",
            exclude={"result_integrity_sha256", "runtime_metadata"},
        )
        if sha256_hex(integrity_payload) != self.result_integrity_sha256:
            raise ValueError("candidate analysis integrity digest does not match the persisted payload")


def canonical_json(value: object) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def sha256_hex(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def safe_candidate_id(prefix: str, *parts: object) -> str:
    return f"{prefix}-{sha256_hex(parts)[:20]}"


def canonical_candidate_id(source_record: CandidateSourceRecordIdentity) -> str:
    """Derive the only accepted candidate ID from a domain-separated source binding."""

    return safe_candidate_id(
        "candidate-v037",
        CANDIDATE_SOURCE_BINDING_DOMAIN,
        source_record.model_dump(mode="json"),
    )


def stable_candidate_id(source_record: CandidateSourceRecordIdentity) -> str:
    return safe_candidate_id(
        "stable-candidate-v037",
        CANDIDATE_SOURCE_BINDING_DOMAIN,
        source_record.model_dump(mode="json"),
    )


__all__ = [
    "CANDIDATE_ANALYSIS_SCHEMA_VERSION",
    "CANDIDATE_ANALYSIS_ALGORITHM_VERSION",
    "CANDIDATE_RANKING_RULE_VERSION",
    "CANDIDATE_RANKING_WEIGHT_VERSION",
    "CANDIDATE_REQUIRED_UNRESOLVED_WORDING",
    "CANDIDATE_SOURCE_BINDING_DOMAIN",
    "CANDIDATE_FIXED_SUPPORT_THRESHOLD",
    "CANDIDATE_FIXED_TIE_EPSILON",
    "CANDIDATE_FIXED_FAMILY_GQ_THRESHOLD",
    "CANDIDATE_FIXED_COMPONENT_WEIGHTS",
    "CANDIDATE_COMPONENT_RULE_REGISTRY",
    "CandidateAnalysisRequest",
    "CandidateAnalysisResult",
    "CandidateAnalysisState",
    "CandidateAnalysisRecord",
    "CandidateContextInput",
    "CandidateEvidenceInput",
    "CandidateRankingRule",
    "CandidateRankingComponent",
    "CandidateReviewStatus",
    "CandidateComponentRule",
    "CandidateComponentCalculation",
    "CandidateSourceAlleleKey",
    "CandidateSourceRecordIdentity",
    "CandidateVariantScope",
    "ComponentState",
    "DeNovoState",
    "EvidenceRole",
    "FamilySampleBindingInput",
    "FamilySegregationObservation",
    "FamilySegregationSummary",
    "MissingInformation",
    "NegativeUnresolvedResult",
    "PhaseEvaluation",
    "ProvenanceReference",
    "SuppliedHpoRelation",
    "UnresolvedUncertainty",
    "canonical_json",
    "calculate_candidate_component",
    "canonical_candidate_id",
    "stable_candidate_id",
    "safe_candidate_id",
    "sha256_hex",
]


CandidateAnalysisRequest.model_rebuild()
