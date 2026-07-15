from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.insilicopop.clinical.models import ClinicalCaseIntake
from app.insilicopop.clinical.service import (
    build_clinical_case_bundle,
    build_clinical_case_extended_bundle,
    build_clinical_case_with_curation,
)
from app.insilicopop.clinical.variant_models import VariantIntelligenceRequest, VariantNormalizationRequest


def request_payload(**updates):
    payload = {
        "request_id": "REQ-1",
        "candidate_variant_id": "VAR-1",
        "supplied_representation": "  NC_000001.11:g.100A>G  ",
        "representation_type": "hgvs_genomic",
        "declared_variant_class": "snv",
        "supplied_genome_build": "GRCh38",
        "supplied_reference_accession": "NC_000001.11",
        "requested_outputs": ["validated_supplied_representation"],
        "provenance_source_ids": ["SRC-2", "SRC-1"],
    }
    payload.update(updates)
    return payload


def clinical_payload(*, include_variant=True):
    payload = {
        "schema_version": "0.27",
        "pseudonymous_case_id": "CASE-V030-MODEL",
        "intended_use": "clinical_genetics_research_curation",
        "redaction_declared": True,
        "human_review_required": True,
        "provenance": [{"source_id": "SRC-1", "source_type": "synthetic_fixture"}],
        "candidate_variants": [{"candidate_id": "VAR-1", "submitted_representation": "NC_000001.11:g.100A>G"}],
    }
    if include_variant:
        payload["variant_intelligence"] = {
            "schema_version": "0.30",
            "normalization_requests": [request_payload(supplied_representation="NC_000001.11:g.100A>G")],
            "human_review_required": True,
        }
    return payload


def test_v030_is_optional_and_legacy_service_contracts_are_unchanged():
    case = ClinicalCaseIntake.model_validate(clinical_payload(include_variant=False))
    assert case.schema_version == "0.27"
    assert case.variant_intelligence is None
    assert len(build_clinical_case_with_curation(clinical_payload(include_variant=False))) == 2
    assert len(build_clinical_case_bundle(clinical_payload(include_variant=False))) == 3
    extended = build_clinical_case_extended_bundle(clinical_payload())
    assert len(extended) == 4
    assert extended[3].schema_version == "0.30"


def test_exact_supplied_strings_are_preserved_without_implicit_cleanup():
    request = VariantNormalizationRequest.model_validate(request_payload())
    assert request.supplied_representation == "  NC_000001.11:g.100A>G  "
    assert request.provenance_source_ids == ["SRC-2", "SRC-1"]


def test_every_supplied_biological_field_round_trips_exactly():
    raw = request_payload(
        supplied_representation="  NM_000001.2:c.1A>G!?  ",
        representation_type="hgvs_coding",
        supplied_genome_build=" GRCh38 ",
        supplied_reference_accession=" NC_000001.11 ",
        supplied_transcript_accession=" NM_000001.2 ",
        supplied_gene_id=" Gene-α!? ",
        supplied_chromosome=" chrX ",
        supplied_reference=" aC ",
        supplied_alternate=" T! ",
        supplied_spdi=" NC_000001.11:0:A:G ",
        supplied_vrs={"type": " Allele ", "id": "ga4gh:VA.test!?"},
        supplied_caid=" CA123 ",
        supplied_protein_consequence=" NP_000001.1:p.(Val1Ala) ",
        structured_allele={
            "chromosome": " chrX ",
            "position": 1,
            "reference": " a ",
            "alternate": " T ",
            "coordinate_system": "one_based_closed",
            "genome_build": " GRCh38 ",
            "reference_accession": " NC_000001.11 ",
            "reference_source_id": " LOCAL!? ",
            "reference_context_sequence": " aCgT!? ",
            "reference_context_start": 0,
            "reference_context_verified": True,
        },
    )
    parsed = VariantNormalizationRequest.model_validate(raw).model_dump(mode="json")
    for field in (
        "supplied_representation", "supplied_genome_build", "supplied_reference_accession",
        "supplied_transcript_accession", "supplied_gene_id", "supplied_chromosome",
        "supplied_reference", "supplied_alternate", "supplied_spdi", "supplied_vrs",
        "supplied_caid", "supplied_protein_consequence",
    ):
        assert parsed[field] == raw[field]
    for field in (
        "chromosome", "reference", "alternate", "genome_build", "reference_accession",
        "reference_source_id", "reference_context_sequence",
    ):
        assert parsed["structured_allele"][field] == raw["structured_allele"][field]


def test_request_ids_must_be_unique_and_candidate_reference_is_required_by_schema():
    duplicate = request_payload()
    with pytest.raises(ValidationError, match="request IDs must be unique"):
        VariantIntelligenceRequest.model_validate({
            "schema_version": "0.30",
            "normalization_requests": [duplicate, duplicate],
            "human_review_required": True,
        })
    missing = request_payload()
    missing.pop("candidate_variant_id")
    with pytest.raises(ValidationError):
        VariantNormalizationRequest.model_validate(missing)


@pytest.mark.parametrize(
    ("field", "value"),
    [("representation_type", "invented"), ("declared_variant_class", "pathogenic"), ("review_state", "approved")],
)
def test_closed_enums_reject_unrecognized_values(field, value):
    with pytest.raises(ValidationError):
        VariantNormalizationRequest.model_validate(request_payload(**{field: value}))


def test_schema_and_human_review_guardrails_are_fixed():
    with pytest.raises(ValidationError):
        VariantIntelligenceRequest.model_validate({"schema_version": "0.31", "human_review_required": True})
    with pytest.raises(ValidationError):
        VariantIntelligenceRequest.model_validate({"schema_version": "0.30", "human_review_required": False})
