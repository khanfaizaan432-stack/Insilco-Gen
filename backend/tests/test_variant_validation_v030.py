from __future__ import annotations

import pytest

from app.insilicopop.clinical.models import CandidateVariantIntake
from app.insilicopop.clinical.variant_models import VariantNormalizationRequest
from app.insilicopop.clinical.variant_validation import validate_variant_request
from app.insilicopop.clinical.variant_reference_registry import SYNTHETIC_REFERENCE_SOURCE_ID


def candidate(**updates):
    data = {
        "candidate_id": "VAR-1",
        "submitted_representation": "TEST1:2:A:G",
        "genome_build": "InSilicoPopSynthetic-0.30",
        "chromosome": "TEST1",
        "position": 2,
        "ref": "A",
        "alt": "G",
        "transcript": "NM_000001.2",
    }
    data.update(updates)
    return CandidateVariantIntake.model_validate(data)


def structured_request(**updates):
    data = {
        "request_id": "REQ-1",
        "candidate_variant_id": "VAR-1",
        "supplied_representation": "TEST1:2:A:G",
        "representation_type": "vcf_like_fields",
        "declared_variant_class": "snv",
        "supplied_transcript_accession": "NM_000001.2",
        "structured_allele": {
            "chromosome": "TEST1",
            "position": 2,
            "reference": "A",
            "alternate": "G",
            "coordinate_system": "vcf_one_based",
            "genome_build": "InSilicoPopSynthetic-0.30",
            "reference_accession": "ISP_TESTREF.1",
            "reference_source_id": SYNTHETIC_REFERENCE_SOURCE_ID,
        },
        "requested_outputs": ["canonical_internal_allele"],
        "provenance_source_ids": ["SRC-1"],
    }
    data.update(updates)
    return VariantNormalizationRequest.model_validate(data)


def codes(assessment):
    return {item.code for group in (
        assessment.errors, assessment.warnings, assessment.missing,
        assessment.unsupported, assessment.conflicts, assessment.review_actions,
    ) for item in group}


def test_valid_structured_snv_has_no_validation_findings():
    result = validate_variant_request(structured_request(), candidate())
    assert codes(result) == set()


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"supplied_representation": "not-hgvs", "representation_type": "hgvs_genomic", "structured_allele": None}, "MALFORMED_HGVS_SYNTAX"),
        ({"supplied_representation": "NM_000001:c.1A>G", "representation_type": "hgvs_coding", "structured_allele": None, "supplied_transcript_accession": "NM_000001"}, "TRANSCRIPT_VERSION_REQUIRED"),
        ({"structured_allele": {"chromosome": "1", "position": 100, "reference": "A", "alternate": "G", "coordinate_system": "unknown", "genome_build": "GRCh38"}}, "COORDINATE_SYSTEM_REQUIRED"),
        ({"structured_allele": {"chromosome": "1", "position": 100, "reference": "A", "alternate": "G", "coordinate_system": "one_based_closed"}}, "GENOME_BUILD_REQUIRED"),
        ({"structured_allele": {"chromosome": "1", "position": 100, "reference": "", "alternate": "G", "coordinate_system": "vcf_one_based", "genome_build": "GRCh38"}}, "VCF_ALLELES_REQUIRED"),
        ({"structured_allele": {"chromosome": "1", "position": 100, "reference": "", "alternate": "", "coordinate_system": "one_based_closed", "genome_build": "GRCh38"}}, "REFERENCE_ALTERNATE_COMBINATION_INVALID"),
        ({"supplied_representation": "free variant description", "representation_type": "free_text", "structured_allele": None}, "UNSUPPORTED_FREE_TEXT_REPRESENTATION"),
        ({"supplied_representation": "C:/cases/sample.vcf", "representation_type": "unknown", "structured_allele": None}, "RAW_GENOMIC_INPUT_NOT_SUPPORTED"),
    ],
)
def test_validation_refuses_or_flags_ambiguous_inputs(overrides, expected):
    assert expected in codes(validate_variant_request(structured_request(**overrides), candidate()))


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("genome_build", "GRCh37", "BUILD_CONFLICT"),
        ("chromosome", "2", "CHROMOSOME_CONFLICT"),
        ("reference", "C", "REFERENCE_MISMATCH"),
        ("alternate", "T", "ALTERNATE_MISMATCH"),
    ],
)
def test_candidate_and_request_context_conflicts_are_explicit(field, value, expected):
    allele = structured_request().structured_allele.model_dump()
    allele[field] = value
    result = validate_variant_request(structured_request(structured_allele=allele), candidate())
    assert expected in codes(result)


def test_transcript_conflict_and_missing_candidate_are_explicit():
    assert "TRANSCRIPT_CONFLICT" in codes(validate_variant_request(structured_request(supplied_transcript_accession="NM_000002.1"), candidate()))
    assert "CANDIDATE_VARIANT_REFERENCE_REQUIRED" in codes(validate_variant_request(structured_request(), None))


def test_formatting_and_allele_case_are_preserved_and_flagged():
    allele = structured_request().structured_allele.model_dump()
    allele["reference"] = "a"
    request = structured_request(supplied_representation=" 1:100:a:G ", structured_allele=allele)
    result = validate_variant_request(request, candidate(ref="a"))
    assert request.supplied_representation == " 1:100:a:G "
    assert request.structured_allele.reference == "a"
    assert {"FORMATTING_ANOMALY_PRESERVED", "ALLELE_FORMATTING_ANOMALY_PRESERVED"} <= codes(result)


@pytest.mark.parametrize("variant_class", [
    "cnv", "structural_variant", "inversion", "translocation", "repeat_expansion",
    "mosaic", "somatic", "mitochondrial_complex", "complex_rearrangement",
    "pharmacogenomic_haplotype", "hla_allele", "star_allele", "polygenic_score",
])
def test_unsupported_classes_are_retained_with_reasons(variant_class):
    result = validate_variant_request(structured_request(declared_variant_class=variant_class), candidate())
    assert result.unsupported
    assert all(item.severity == "unsupported" for item in result.unsupported)
