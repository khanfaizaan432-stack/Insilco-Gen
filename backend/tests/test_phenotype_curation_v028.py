import copy

from app.insilicopop.clinical.hpo_models import HPO_ALGORITHM_VERSION
from app.insilicopop.clinical.service import build_clinical_case_with_curation


def payload(text="No seizures; progressive short stature.", *, snippets=None, phenotypes=None, actions=None):
    return {
        "schema_version": "0.27",
        "pseudonymous_case_id": "CASE-V028",
        "intended_use": "clinical_genetics_research_curation",
        "redaction_declared": True,
        "reviewer_status": "pending",
        "human_review_required": True,
        "genome_build": "GRCh38",
        "provenance": [{"source_id": "CASE-SRC", "source_type": "synthetic_fixture"}],
        "phenotypes": phenotypes if phenotypes is not None else [{"observation_id": "PH-BASE", "supplied_term": "synthetic finding", "state": "unknown"}],
        "candidate_variants": [{"candidate_id": "VAR-1", "submitted_representation": "synthetic variant", "gene": "GENE1"}],
        "phenotype_curation": {
            "snippets": snippets if snippets is not None else [{
                "snippet_id": "SNIP-1",
                "redaction_declared": True,
                "redacted_text": text,
                "source_label": "fictional summary",
                "provenance": [{"source_id": "SNIP-SRC", "source_type": "synthetic_redacted_fixture"}],
            }],
            "reviewer_actions": actions or [],
        },
    }


def curation(data):
    _, result = build_clinical_case_with_curation(data)
    assert result is not None
    return result


def test_exact_matching_offsets_methods_boundaries_and_stable_ids():
    text = "SEIZURES and hearing loss, not seizurelike wording."
    first = curation(payload(text))
    second = curation(payload(text))
    assert [(item.hpo_id, item.match_start, item.match_end, item.matched_substring, item.matching_method) for item in first.hpo_suggestions] == [
        ("HP:0001250", 0, 8, "SEIZURES", "synonym_exact"),
        ("HP:0000365", 13, 25, "hearing loss", "synonym_exact"),
    ]
    assert [item.suggestion_id for item in first.hpo_suggestions] == [item.suggestion_id for item in second.hpo_suggestions]
    assert first.algorithm_version == HPO_ALGORITHM_VERSION


def test_overlap_prefers_longest_at_equal_start_and_suppresses_duplicates():
    result = curation(payload("Global developmental delay"))
    assert [(item.hpo_id, item.canonical_label) for item in result.hpo_suggestions] == [("HP:0001263", "Global developmental delay")]


def test_clear_and_ambiguous_negation_are_narrow_and_explainable():
    result = curation(payload("No seizures or microcephaly."))
    seizure, microcephaly = result.hpo_suggestions
    assert seizure.proposed_state == "absent"
    assert seizure.negation and seizure.negation.cue.casefold() == "no"
    assert seizure.negation.context_window_size == 48
    assert microcephaly.proposed_state == "unknown"
    assert "ambiguous_negation_scope" in microcephaly.validation_warnings
    assert microcephaly.proposed_state != "absent"


def test_explicit_and_textual_onset_temporal_context_are_bounded():
    explicit = payload("Seizure")
    explicit["phenotype_curation"]["snippets"][0]["supplied_onset"] = "childhood onset"
    explicit["phenotype_curation"]["snippets"][0]["supplied_temporal_context"] = "resolved"
    explicit_suggestion = curation(explicit).hpo_suggestions[0]
    assert explicit_suggestion.onset.source == "explicit"
    assert explicit_suggestion.temporal.source == "explicit"
    assert explicit_suggestion.proposed_state == "resolved"
    textual = curation(payload("Seizure resolved."))
    assert textual.hpo_suggestions[0].temporal.detected_text.casefold() == "resolved"
    assert textual.hpo_suggestions[0].proposed_state == "resolved"


def test_present_absent_and_existing_observation_contradictions_are_typed():
    snippets = [
        {"snippet_id": "S1", "redaction_declared": True, "redacted_text": "No seizures", "provenance": [{"source_id": "S1", "source_type": "synthetic"}]},
        {"snippet_id": "S2", "redaction_declared": True, "redacted_text": "Seizure", "provenance": [{"source_id": "S2", "source_type": "synthetic"}]},
    ]
    result = curation(payload(snippets=snippets))
    assert "proposed_present_and_absent" in {item.contradiction_type for item in result.contradictions}
    existing = [{"observation_id": "PH-CONF", "supplied_term": "Seizure", "hpo_id": "HP:0001250", "state": "absent", "review_state": "confirmed"}]
    conflict = curation(payload("Seizure", phenotypes=existing))
    assert "existing_observation_conflict" in {item.contradiction_type for item in conflict.contradictions}
    assert all(item.resolution_status == "requires_reviewer_resolution" for item in conflict.contradictions)


def test_all_reviewer_states_and_confirmed_promotion_are_explicit_and_immutable():
    base = payload("Seizure")
    original = copy.deepcopy(base)
    suggestion_id = curation(base).hpo_suggestions[0].suggestion_id
    for status in ("pending", "rejected", "needs_clarification"):
        reviewed = payload("Seizure", actions=[{"suggestion_id": suggestion_id, "action": status}])
        assert not curation(reviewed).promoted_observations
    confirmed = payload("Seizure", actions=[{"suggestion_id": suggestion_id, "action": "confirmed", "provenance": [{"source_id": "REVIEW-1", "source_type": "human_reviewer"}]}])
    promoted = curation(confirmed)
    assert promoted.hpo_suggestions[0].review_status == "confirmed"
    assert len(promoted.promoted_observations) == 1
    assert promoted.promoted_observations[0].hpo_id == "HP:0001250"
    assert base == original


def test_modified_action_requires_complete_registry_valid_replacement():
    suggestion_id = curation(payload("Seizure")).hpo_suggestions[0].suggestion_id
    missing = curation(payload("Seizure", actions=[{"suggestion_id": suggestion_id, "action": "modified"}]))
    assert "modified_replacement_required" in {item.code for item in missing.missing_information}
    assert not missing.promoted_observations
    valid = curation(payload("Seizure", actions=[{"suggestion_id": suggestion_id, "action": "modified", "replacement": {"hpo_id": "HP:0000252", "state": "present"}}]))
    assert valid.hpo_suggestions[0].validated_modification.canonical_label == "Microcephaly"
    assert valid.promoted_observations[0].hpo_id == "HP:0000252"
    invalid = curation(payload("Seizure", actions=[{"suggestion_id": suggestion_id, "action": "modified", "replacement": {"hpo_id": "HP:9999999", "state": "present"}}]))
    assert "invalid_modified_replacement" in {item.code for item in invalid.validation_errors}
    assert not invalid.promoted_observations


def test_duplicate_promotion_is_prevented():
    existing = [{"observation_id": "PH-CONF", "supplied_term": "Seizure", "hpo_id": "HP:0001250", "state": "present", "review_state": "confirmed"}]
    suggestion_id = curation(payload("Seizure", phenotypes=existing)).hpo_suggestions[0].suggestion_id
    result = curation(payload("Seizure", phenotypes=existing, actions=[{"suggestion_id": suggestion_id, "action": "confirmed"}]))
    assert not result.promoted_observations


def test_modified_target_conflict_is_detected_by_replacement_hpo_id():
    existing = [{"observation_id": "PH-MICRO", "supplied_term": "Microcephaly", "hpo_id": "HP:0000252", "state": "absent", "review_state": "confirmed"}]
    suggestion_id = curation(payload("Seizure", phenotypes=existing)).hpo_suggestions[0].suggestion_id
    result = curation(payload("Seizure", phenotypes=existing, actions=[{
        "suggestion_id": suggestion_id,
        "action": "modified",
        "replacement": {"hpo_id": "HP:0000252", "state": "present"},
    }]))
    assert "modified_existing_observation_conflict" in {item.contradiction_type for item in result.contradictions}
    assert not result.promoted_observations


def test_central_validation_blocks_unredacted_or_direct_identifier_snippets():
    unredacted = payload("Seizure")
    unredacted["phenotype_curation"]["snippets"][0]["redaction_declared"] = False
    result = curation(unredacted)
    assert "snippet_redaction_declaration_required" in {item.code for item in result.validation_errors}
    assert not result.hpo_suggestions
    direct = curation(payload("Seizure noted for person@example.org"))
    assert "email_address" in {item.code for item in direct.policy_blocks}
    assert not direct.hpo_suggestions
    unsafe_label = payload("Seizure")
    unsafe_label["phenotype_curation"]["snippets"][0]["source_label"] = "person@example.org"
    label_result = curation(unsafe_label)
    assert "email_address" in {item.code for item in label_result.policy_blocks}
    assert not label_result.hpo_suggestions


def test_policy_blocks_remain_central_and_safety_flags_are_false():
    data = payload("Seizure")
    data["requested_actions"] = ["provide final ACMG classification"]
    result = curation(data)
    assert "final_classification_request" in {item.code for item in result.policy_blocks}
    assert result.research_use_only and result.human_review_required
    assert result.diagnosis_made is False
    assert result.treatment_recommendation_made is False
    assert result.final_acmg_classification_made is False
    assert result.external_llm_called is False
    assert result.external_tools_executed is False
    assert result.raw_genomic_files_parsed is False
