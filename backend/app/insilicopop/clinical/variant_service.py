from __future__ import annotations

from collections import Counter

from app.insilicopop.clinical.models import ClinicalCaseIntake
from app.insilicopop.clinical.variant_models import (
    VARIANT_INTELLIGENCE_ALGORITHM_VERSION,
    VariantIntelligenceResult,
    VariantNormalizationStatus,
)
from app.insilicopop.clinical.variant_normalization import normalize_variant_request
from app.insilicopop.clinical.variant_validation import stable_variant_identifier


def build_variant_intelligence(case: ClinicalCaseIntake) -> VariantIntelligenceResult | None:
    declaration = case.variant_intelligence
    if declaration is None:
        return None
    candidates = {item.candidate_id: item for item in case.candidate_variants}
    results = [
        normalize_variant_request(request, candidates.get(request.candidate_variant_id))
        for request in sorted(declaration.normalization_requests, key=lambda item: item.request_id)
    ]
    validation_counts = Counter(item.validation_status.value for item in results)
    normalization_counts = Counter(item.normalization_status.value for item in results)
    equivalence_counts = Counter(item.equivalence_status.value for item in results)
    stable_payload = {
        "schema_version": "0.30",
        "algorithm_version": VARIANT_INTELLIGENCE_ALGORITHM_VERSION,
        "pseudonymous_case_id": case.pseudonymous_case_id,
        "normalization_results": [item.model_dump() for item in results],
        "reviewer_status": declaration.reviewer_status.value,
    }
    return VariantIntelligenceResult(
        pseudonymous_case_id=case.pseudonymous_case_id,
        normalization_results=results,
        validation_status_counts={key: validation_counts[key] for key in sorted(validation_counts)},
        normalization_status_counts={key: normalization_counts[key] for key in sorted(normalization_counts)},
        equivalence_status_counts={key: equivalence_counts[key] for key in sorted(equivalence_counts)},
        reviewer_status=declaration.reviewer_status.value,
        stable_result_id=stable_variant_identifier("variant-intelligence", stable_payload),
        variant_normalization_performed=any(
            item.normalization_status in {
                VariantNormalizationStatus.NORMALIZED,
                VariantNormalizationStatus.PARTIALLY_NORMALIZED,
            }
            for item in results
        ),
    )
