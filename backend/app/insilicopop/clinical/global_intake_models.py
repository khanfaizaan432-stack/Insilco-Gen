from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


GLOBAL_INTAKE_SCHEMA_VERSION = "0.31"


class GlobalFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ExactTextModel(GlobalFrozenModel):
    """Model for source wording that must not be silently normalized."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)


class CareSetting(str, Enum):
    PRIMARY_CARE = "primary_care"
    DISTRICT_OR_REGIONAL_HOSPITAL = "district_or_regional_hospital"
    TERTIARY_HOSPITAL = "tertiary_hospital"
    UNIVERSITY_OR_MEDICAL_COLLEGE = "university_or_medical_college"
    PRIVATE_CLINIC = "private_clinic"
    DIAGNOSTIC_LABORATORY = "diagnostic_laboratory"
    RESEARCH_STUDY = "research_study"
    TELECONSULTATION = "teleconsultation"
    UNKNOWN = "unknown"
    OTHER = "other"


class CareStage(str, Enum):
    PRENATAL = "prenatal"
    NEONATAL = "neonatal"
    PEDIATRIC = "pediatric"
    ADULT = "adult"
    UNSPECIFIED = "unspecified"


class TranslationStatus(str, Enum):
    ORIGINAL = "original"
    CLINICIAN_TRANSLATED = "clinician_translated"
    QUALIFIED_INTERPRETER_TRANSLATED = "qualified_interpreter_translated"
    FAMILY_TRANSLATED = "family_translated"
    MACHINE_TRANSLATED = "machine_translated"
    TRANSLATION_STATUS_UNKNOWN = "translation_status_unknown"


class TranslationReviewState(str, Enum):
    NOT_REQUIRED = "not_required"
    UNREVIEWED = "unreviewed"
    HUMAN_REVIEWED = "human_reviewed"
    NEEDS_REVISION = "needs_revision"
    UNKNOWN = "unknown"


class RelationshipContextReviewStatus(str, Enum):
    NOT_REVIEWED = "not_reviewed"
    REVIEWED_CONFIRMED = "reviewed_confirmed"
    REVIEWED_CORRECTED = "reviewed_corrected"
    REQUIRES_CLARIFICATION = "requires_clarification"


class ReportCompleteness(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    SCANNED = "scanned"
    TRANSCRIBED = "transcribed"
    HANDWRITTEN = "handwritten"
    UNAVAILABLE = "unavailable"


class SampleAvailability(str, Enum):
    AVAILABLE = "available"
    POTENTIALLY_AVAILABLE = "potentially_available"
    UNAVAILABLE = "unavailable"
    NOT_ASSESSED = "not_assessed"
    UNKNOWN = "unknown"


class TestingAccessConstraint(str, Enum):
    PRIOR_REPORTS_UNAVAILABLE = "prior_reports_unavailable"
    PRIOR_TESTING_UNAVAILABLE = "prior_testing_unavailable"
    TESTING_DEFERRED = "testing_deferred"
    FAMILY_SAMPLE_UNAVAILABLE = "family_sample_unavailable"
    TRAVEL_LIMITATION_REPORTED = "travel_limitation_reported"
    FINANCIAL_OR_ACCESS_LIMITATION_REPORTED = "financial_or_access_limitation_reported"
    REFERRAL_UNAVAILABLE = "referral_unavailable"
    FOLLOW_UP_UNCERTAIN = "follow_up_uncertain"
    LANGUAGE_SUPPORT_LIMITATION = "language_support_limitation"
    OTHER = "other"


class IndiaCareSetting(str, Enum):
    GOVERNMENT_HOSPITAL = "government_hospital"
    PRIVATE_HOSPITAL = "private_hospital"
    MEDICAL_COLLEGE = "medical_college"
    DIAGNOSTIC_LABORATORY = "diagnostic_laboratory"
    RESEARCH_STUDY = "research_study"
    TELECONSULTATION = "teleconsultation"
    OTHER = "other"


class ConsanguinityStatus(str, Enum):
    REPORTED = "reported"
    NOT_REPORTED = "not_reported"
    UNKNOWN = "unknown"
    NOT_ASSESSED = "not_assessed"


class SuppliedConsanguinityRelationship(str, Enum):
    FIRST_COUSINS = "first_cousins"
    SECOND_COUSINS = "second_cousins"
    UNCLE_NIECE = "uncle_niece"
    AUNT_NEPHEW = "aunt_nephew"
    RELATED_DEGREE_UNKNOWN = "related_degree_unknown"
    NO_KNOWN_CONSANGUINITY = "no_known_relatedness"
    NOT_SUPPLIED = "not_supplied"
    OTHER = "other"


class FamilySampleCategory(str, Enum):
    PROBAND = "proband"
    MATERNAL = "maternal"
    PATERNAL = "paternal"
    SIBLING = "sibling"
    AFFECTED_RELATIVE = "affected_relative"
    UNAFFECTED_RELATIVE = "unaffected_relative"
    RELATIVE_DECEASED = "relative_deceased"
    OTHER = "other"


class LanguageContext(ExactTextModel):
    preferred_language: str | None = Field(default=None, max_length=120)
    source_language: str | None = Field(default=None, max_length=120)
    original_language_code: str | None = Field(default=None, max_length=35, pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
    original_text: str | None = Field(default=None, max_length=2000)
    translated_language_code: str | None = Field(default=None, max_length=35, pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
    translated_text: str | None = Field(default=None, max_length=2000)
    translation_status: TranslationStatus = TranslationStatus.TRANSLATION_STATUS_UNKNOWN
    translation_source_category: str | None = Field(default=None, max_length=160)
    translation_review_state: TranslationReviewState = TranslationReviewState.UNREVIEWED


class LaboratoryContext(ExactTextModel):
    laboratory_source_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    source_label: str | None = Field(default=None, max_length=160)
    report_country_code: str | None = Field(default=None, min_length=2, max_length=2, pattern=r"^[A-Z]{2}$")
    report_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    test_type_exact: str | None = Field(default=None, max_length=240)
    sample_type_exact: str | None = Field(default=None, max_length=160)
    assay_or_sequencing_method_exact: str | None = Field(default=None, max_length=240)
    report_language: str | None = Field(default=None, max_length=120)
    report_completeness: ReportCompleteness | None = None
    genome_build_exact: str | None = Field(default=None, max_length=80)
    transcript_exact: str | None = Field(default=None, max_length=160)
    variant_notation_exact: list[str] = Field(default_factory=list, max_length=50)
    accreditation_wording_exact: str | None = Field(default=None, max_length=500)
    supporting_files_available: bool | None = None
    provenance_source_ids: list[str] = Field(default_factory=list, max_length=30)


class FamilySampleRecord(ExactTextModel):
    family_member_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    relationship_to_proband_exact: str | None = Field(default=None, max_length=160)
    sample_category: FamilySampleCategory = FamilySampleCategory.OTHER
    sample_availability: SampleAvailability = SampleAvailability.UNKNOWN
    sample_type_exact: str | None = Field(default=None, max_length=160)
    testing_status_exact: str | None = Field(default=None, max_length=240)
    provenance_source_ids: list[str] = Field(default_factory=list, max_length=30)
    family_history_incomplete: bool = False


class TestingAccessContext(ExactTextModel):
    constraints: list[TestingAccessConstraint] = Field(default_factory=list, max_length=20)
    other_constraint_exact: str | None = Field(default=None, max_length=500)
    prior_authorization_status_exact: str | None = Field(default=None, max_length=240)
    estimated_turnaround_time_exact: str | None = Field(default=None, max_length=160)


class GovernanceConsentContext(ExactTextModel):
    consent_status_exact: str | None = Field(default=None, max_length=240)
    permitted_use_exact: str | None = Field(default=None, max_length=500)
    data_residency_constraint_exact: str | None = Field(default=None, max_length=240)
    ethics_or_governance_reference: str | None = Field(default=None, max_length=160)
    direct_identifiers_removed_declared: bool | None = None


class GlobalDefaultLocaleProfile(ExactTextModel):
    schema_version: Literal["0.31"] = GLOBAL_INTAKE_SCHEMA_VERSION
    profile_type: Literal["global_default"] = "global_default"
    country_code: str | None = Field(default=None, min_length=2, max_length=2, pattern=r"^[A-Z]{2}$")
    health_system_context_exact: str | None = Field(default=None, max_length=500)


class IndiaLocaleProfile(ExactTextModel):
    schema_version: Literal["0.31"] = GLOBAL_INTAKE_SCHEMA_VERSION
    profile_type: Literal["india"] = "india"
    country_code: Literal["IN"] = "IN"
    state_or_union_territory_code: str | None = Field(default=None, max_length=35, pattern=r"^[A-Z0-9-]+$")
    district_or_region_exact: str | None = Field(default=None, max_length=160)
    care_setting: IndiaCareSetting | None = None
    local_language_context: LanguageContext | None = None
    laboratory_report_context: list[LaboratoryContext] = Field(default_factory=list, max_length=30)
    report_generated_by_indian_laboratory_declared: bool | None = None
    testing_access_context: TestingAccessContext | None = None
    public_program_or_scheme_exact: str | None = Field(default=None, max_length=240)
    consanguinity_status: ConsanguinityStatus = ConsanguinityStatus.NOT_ASSESSED
    relationship_description_original: str | None = Field(default=None, max_length=240)
    relationship_description_translated: str | None = Field(default=None, max_length=240)
    supplied_relationship: SuppliedConsanguinityRelationship = SuppliedConsanguinityRelationship.NOT_SUPPLIED
    relationship_translation_status: TranslationStatus = TranslationStatus.ORIGINAL
    relationship_translation_review_state: TranslationReviewState = TranslationReviewState.NOT_REQUIRED
    relationship_context_review_status: RelationshipContextReviewStatus = RelationshipContextReviewStatus.NOT_REVIEWED
    relationship_description_corrected: str | None = Field(default=None, max_length=240)
    relationship_context_review_provenance_source_ids: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("relationship_context_review_provenance_source_ids", mode="before")
    @classmethod
    def canonicalize_relationship_review_provenance(cls, value):
        return sorted(set(value or []))

    @model_validator(mode="after")
    def validate_corrected_relationship_review(self):
        if self.relationship_context_review_status == RelationshipContextReviewStatus.REVIEWED_CORRECTED:
            if not self.relationship_description_corrected:
                raise ValueError("reviewed_corrected relationship context requires a corrected representation")
            if not self.relationship_context_review_provenance_source_ids:
                raise ValueError("reviewed_corrected relationship context requires review provenance")
        return self


LocaleProfile = Annotated[GlobalDefaultLocaleProfile | IndiaLocaleProfile, Field(discriminator="profile_type")]


class GlobalIntakeContext(ExactTextModel):
    schema_version: Literal["0.31"] = GLOBAL_INTAKE_SCHEMA_VERSION
    enabled: Literal[True] = True
    country_code: str | None = Field(default=None, min_length=2, max_length=2, pattern=r"^[A-Z]{2}$")
    region_or_administrative_area_exact: str | None = Field(default=None, max_length=160)
    care_setting: CareSetting = CareSetting.UNKNOWN
    care_stage: CareStage = CareStage.UNSPECIFIED
    referral_context_exact: str | None = Field(default=None, max_length=500)
    language_context: LanguageContext | None = None
    laboratory_contexts: list[LaboratoryContext] = Field(default_factory=list, max_length=50)
    family_sample_contexts: list[FamilySampleRecord] = Field(default_factory=list, max_length=100)
    testing_access_context: TestingAccessContext | None = None
    governance_consent_context: GovernanceConsentContext | None = None
    locale_profile: LocaleProfile | None = None
    provenance_source_ids: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_locale_consistency(self) -> "GlobalIntakeContext":
        if isinstance(self.locale_profile, IndiaLocaleProfile) and self.country_code not in (None, "IN"):
            raise ValueError("The explicitly selected India locale profile requires country_code IN when country_code is supplied.")
        if isinstance(self.locale_profile, GlobalDefaultLocaleProfile):
            if self.country_code and self.locale_profile.country_code and self.country_code != self.locale_profile.country_code:
                raise ValueError("Global context and locale-profile country codes must agree when both are supplied.")
        return self
