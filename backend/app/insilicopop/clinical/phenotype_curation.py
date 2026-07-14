from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass

from app.insilicopop.clinical.hpo_models import (
    CurationIssue,
    CurationPolicyBlock,
    ContradictionRecord,
    HPO_ALGORITHM_VERSION,
    HpoReplacement,
    HpoReviewStatus,
    HpoSuggestion,
    MatchContextRecord,
    NegationRecord,
    PhenotypeHpoCurationResult,
    PromotedObservation,
    ReviewerActionInput,
    SourceSnippetMetadata,
)
from app.insilicopop.clinical.hpo_registry import HpoTerm, LocalHpoRegistry, load_hpo_registry
from app.insilicopop.clinical.models import ClinicalCaseIntake, ClinicalIntakeIssue, ClinicalPolicyBlock


NEGATION_CONTEXT_WINDOW = 48
CONTEXT_WINDOW = 32
NEGATION_CUES = ("negative for", "absence of", "without", "denies", "not", "no")
ONSET_PATTERNS = ("since birth", "congenital", "childhood onset", "adult onset")
TEMPORAL_PATTERNS = ("resolved", "previously", "currently", "intermittent", "progressive")


@dataclass(frozen=True)
class _Candidate:
    snippet_id: str
    term: HpoTerm
    start: int
    end: int
    matched: str
    method: str


def build_phenotype_hpo_curation(
    case: ClinicalCaseIntake,
    *,
    validation_errors: list[ClinicalIntakeIssue] | None = None,
    validation_warnings: list[ClinicalIntakeIssue] | None = None,
    missing_information: list[ClinicalIntakeIssue] | None = None,
    policy_blocks: list[ClinicalPolicyBlock] | None = None,
    registry: LocalHpoRegistry | None = None,
) -> PhenotypeHpoCurationResult | None:
    request = case.phenotype_curation
    if request is None:
        return None
    registry = registry or load_hpo_registry()
    errors = [_curation_issue(item) for item in validation_errors or []]
    warnings = [_curation_issue(item) for item in validation_warnings or []]
    missing = [_curation_issue(item) for item in missing_information or []]
    blocks = [_curation_block(item) for item in policy_blocks or []]
    sources = [
        SourceSnippetMetadata(
            snippet_id=snippet.snippet_id,
            character_length=len(snippet.redacted_text),
            text_sha256=hashlib.sha256(snippet.redacted_text.encode("utf-8")).hexdigest(),
            source_label=snippet.source_label,
            supplied_onset=snippet.supplied_onset,
            supplied_temporal_context=snippet.supplied_temporal_context,
            provenance=snippet.provenance,
        )
        for snippet in sorted(request.snippets, key=lambda item: item.snippet_id)
    ]

    duplicate_snippets = _duplicates(item.snippet_id for item in request.snippets)
    for snippet_id in duplicate_snippets:
        errors.append(CurationIssue(code="duplicate_snippet_id", field="phenotype_curation.snippets", record_id=snippet_id, message="Snippet IDs must be unique."))

    suggestions: list[HpoSuggestion] = []
    if not errors and not blocks:
        for snippet in sorted(request.snippets, key=lambda item: item.snippet_id):
            candidates = _resolved_candidates(snippet.snippet_id, snippet.redacted_text, registry)
            for candidate in candidates:
                suggestion = _suggestion(candidate, snippet, candidates, registry.registry_version)
                suggestions.append(suggestion)

    actions_by_suggestion: dict[str, list[ReviewerActionInput]] = defaultdict(list)
    for action in request.reviewer_actions:
        actions_by_suggestion[action.suggestion_id].append(action)
    known_ids = {item.suggestion_id for item in suggestions}
    for action in request.reviewer_actions:
        if action.suggestion_id not in known_ids:
            errors.append(CurationIssue(code="unknown_suggestion_id", field="phenotype_curation.reviewer_actions", record_id=action.suggestion_id, message="Reviewer action references an unknown deterministic suggestion ID."))
        if action.action == HpoReviewStatus.MODIFIED and action.replacement is None:
            missing.append(CurationIssue(code="modified_replacement_required", field="phenotype_curation.reviewer_actions.replacement", record_id=action.suggestion_id, message="A modified action requires a complete typed replacement."))

    reviewed: list[HpoSuggestion] = []
    for suggestion in suggestions:
        actions = actions_by_suggestion.get(suggestion.suggestion_id, [])
        action = actions[-1] if actions else None
        replacement = _validated_replacement(action.replacement, registry) if action and action.replacement else None
        if action and action.action == HpoReviewStatus.MODIFIED and action.replacement and replacement is None:
            errors.append(CurationIssue(code="invalid_modified_replacement", field="phenotype_curation.reviewer_actions.replacement", record_id=suggestion.suggestion_id, message="Modified HPO ID or label is not valid in the local registry."))
        reviewed.append(
            suggestion.model_copy(
                update={
                    "review_status": action.action if action else HpoReviewStatus.PENDING,
                    "reviewer_action": action,
                    "validated_modification": replacement,
                }
            )
        )

    contradictions = _contradictions(reviewed, case, actions_by_suggestion)
    refs: dict[str, list[str]] = defaultdict(list)
    for contradiction in contradictions:
        for record_id in contradiction.involved_record_ids:
            refs[record_id].append(contradiction.contradiction_id)
    reviewed = [item.model_copy(update={"contradiction_references": sorted(refs.get(item.suggestion_id, []))}) for item in reviewed]
    promoted = _promote(reviewed, case)

    return PhenotypeHpoCurationResult(
        registry_version=registry.registry_version,
        pseudonymous_case_id=case.pseudonymous_case_id,
        source_snippets=sources,
        validation_errors=_stable_issues(errors),
        validation_warnings=_stable_issues(warnings),
        missing_information=_stable_issues(missing),
        policy_blocks=sorted(blocks, key=lambda item: (item.code, item.category)),
        hpo_suggestions=reviewed,
        contradictions=contradictions,
        review_actions=list(request.reviewer_actions),
        promoted_observations=promoted,
    )


def _resolved_candidates(snippet_id: str, text: str, registry: LocalHpoRegistry) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    for term in registry.terms:
        phrases = [(term.canonical_label, "canonical_exact"), *((synonym, "synonym_exact") for synonym in term.synonyms)]
        for phrase, method in phrases:
            pattern = re.compile(rf"(?<!\w){re.escape(phrase)}(?!\w)", re.IGNORECASE)
            for match in pattern.finditer(text):
                candidates.append(_Candidate(snippet_id, term, match.start(), match.end(), match.group(0), method))
    candidates.sort(key=lambda item: (item.start, -(item.end - item.start), item.term.hpo_id, item.method))
    selected: list[_Candidate] = []
    seen: set[tuple[str, str, int, int]] = set()
    for candidate in candidates:
        key = (candidate.snippet_id, candidate.term.hpo_id, candidate.start, candidate.end)
        if key in seen or any(candidate.start < item.end and item.start < candidate.end for item in selected):
            continue
        seen.add(key)
        selected.append(candidate)
    return selected


def _suggestion(candidate: _Candidate, snippet, candidates: list[_Candidate], registry_version: str) -> HpoSuggestion:
    negation, negation_warning = _negation(candidate, snippet.redacted_text, candidates)
    onset = _context(candidate, snippet.redacted_text, snippet.supplied_onset, ONSET_PATTERNS)
    temporal = _context(candidate, snippet.redacted_text, snippet.supplied_temporal_context, TEMPORAL_PATTERNS)
    warnings = [negation_warning] if negation_warning else []
    state = "absent" if negation and negation.result == "clear" else "unknown" if negation and negation.result == "ambiguous" else "present"
    if temporal and temporal.detected_text.casefold() == "resolved":
        if temporal.source == "explicit" or _local_context_is_clear(candidate, temporal, candidates):
            state = "resolved"
        else:
            warnings.append("ambiguous_resolved_scope")
    suggestion_id = _stable_id("hpo-suggestion", HPO_ALGORITHM_VERSION, candidate.snippet_id, candidate.term.hpo_id, candidate.start, candidate.end, state)
    return HpoSuggestion(
        suggestion_id=suggestion_id,
        source_snippet_id=candidate.snippet_id,
        hpo_id=candidate.term.hpo_id,
        canonical_label=candidate.term.canonical_label,
        match_start=candidate.start,
        match_end=candidate.end,
        matched_substring=candidate.matched,
        matching_method=candidate.method,
        proposed_state=state,
        negation=negation,
        onset=onset,
        temporal=temporal,
        match_quality="exact_canonical" if candidate.method == "canonical_exact" else "exact_synonym",
        registry_version=registry_version,
        provenance=snippet.provenance,
        validation_warnings=warnings,
    )


def _negation(candidate: _Candidate, text: str, candidates: list[_Candidate]) -> tuple[NegationRecord | None, str | None]:
    window_start = max(0, candidate.start - NEGATION_CONTEXT_WINDOW)
    prefix = text[window_start:candidate.start]
    matches = []
    for cue in NEGATION_CUES:
        for found in re.finditer(rf"(?<!\w){re.escape(cue)}(?!\w)", prefix, re.IGNORECASE):
            matches.append((window_start + found.start(), window_start + found.end(), found.group(0)))
    if not matches:
        return None, None
    cue_start, cue_end, cue = max(matches, key=lambda item: item[1])
    intervening_candidates = [item for item in candidates if cue_end <= item.start < candidate.start]
    gap = text[cue_end:candidate.start].strip(" \t\r\n,;:-")
    clear = not intervening_candidates and gap.casefold() in {"", "history of", "evidence of"}
    result = "clear" if clear else "ambiguous"
    record = NegationRecord(
        cue=cue,
        cue_start=cue_start,
        cue_end=cue_end,
        match_start=candidate.start,
        match_end=candidate.end,
        context_window_size=NEGATION_CONTEXT_WINDOW,
        result=result,
    )
    return record, None if clear else "ambiguous_negation_scope"


def _context(candidate: _Candidate, text: str, explicit: str | None, patterns: tuple[str, ...]) -> MatchContextRecord | None:
    if explicit:
        return MatchContextRecord(detected_text=explicit, start=-1, end=-1, source="explicit")
    start = max(0, candidate.start - CONTEXT_WINDOW)
    end = min(len(text), candidate.end + CONTEXT_WINDOW)
    matches = []
    for phrase in patterns:
        for found in re.finditer(rf"(?<!\w){re.escape(phrase)}(?!\w)", text[start:end], re.IGNORECASE):
            absolute_start = start + found.start()
            absolute_end = start + found.end()
            distance = min(abs(candidate.start - absolute_end), abs(absolute_start - candidate.end))
            matches.append((distance, absolute_start, absolute_end, found.group(0)))
    if not matches:
        return None
    _, matched_start, matched_end, matched = min(matches, key=lambda item: (item[0], item[1], item[3].casefold()))
    return MatchContextRecord(detected_text=matched, start=matched_start, end=matched_end, source="text_pattern")


def _local_context_is_clear(candidate: _Candidate, context: MatchContextRecord, candidates: list[_Candidate]) -> bool:
    if min(abs(candidate.start - context.end), abs(context.start - candidate.end)) > 16:
        return False
    low, high = sorted((candidate.start, context.start))
    return not any(low < item.start < high for item in candidates if item != candidate)


def _validated_replacement(replacement: HpoReplacement, registry: LocalHpoRegistry) -> HpoReplacement | None:
    term = registry.resolve(replacement.hpo_id)
    if term is None:
        return None
    if replacement.canonical_label and replacement.canonical_label.casefold() != term.canonical_label.casefold():
        return None
    return replacement.model_copy(update={"canonical_label": term.canonical_label})


def _contradictions(suggestions: list[HpoSuggestion], case: ClinicalCaseIntake, actions: dict[str, list[ReviewerActionInput]]) -> list[ContradictionRecord]:
    records: list[ContradictionRecord] = []
    by_hpo: dict[str, list[HpoSuggestion]] = defaultdict(list)
    for suggestion in suggestions:
        by_hpo[suggestion.hpo_id].append(suggestion)
    existing = [item for item in case.phenotypes if item.hpo_id and item.review_state.value == "confirmed"]
    for hpo_id in sorted(by_hpo):
        group = by_hpo[hpo_id]
        states = {item.proposed_state for item in group}
        if "present" in states and "absent" in states:
            records.append(_contradiction(hpo_id, "proposed_present_and_absent", [item.suggestion_id for item in group], sorted(states), [item.source_snippet_id for item in group]))
        elif len(states) > 1 and len({item.source_snippet_id for item in group}) > 1:
            records.append(_contradiction(hpo_id, "incompatible_source_states", [item.suggestion_id for item in group], sorted(states), [item.source_snippet_id for item in group]))
        for observation in sorted((item for item in existing if item.hpo_id == hpo_id), key=lambda item: item.observation_id):
            for suggestion in group:
                proposed = suggestion.validated_modification.state if suggestion.validated_modification else suggestion.proposed_state
                if {observation.state.value, proposed} == {"confirmed", "resolved"} or ({observation.state.value, proposed} == {"present", "resolved"} and not (observation.onset_text or suggestion.temporal)):
                    records.append(_contradiction(hpo_id, "confirmed_resolved_without_temporal_context", [observation.observation_id, suggestion.suggestion_id], [observation.state.value, proposed], [observation.source_reference or observation.observation_id, suggestion.source_snippet_id]))
                elif observation.state.value != proposed and {observation.state.value, proposed} <= {"present", "absent", "resolved"}:
                    kind = "modified_existing_observation_conflict" if suggestion.validated_modification else "existing_observation_conflict"
                    records.append(_contradiction(hpo_id, kind, [observation.observation_id, suggestion.suggestion_id], [observation.state.value, proposed], [observation.source_reference or observation.observation_id, suggestion.source_snippet_id]))
    for suggestion in suggestions:
        replacement = suggestion.validated_modification
        if not replacement or replacement.hpo_id == suggestion.hpo_id:
            continue
        for observation in sorted((item for item in existing if item.hpo_id == replacement.hpo_id), key=lambda item: item.observation_id):
            if observation.state.value != replacement.state and {observation.state.value, replacement.state} <= {"present", "absent", "resolved"}:
                records.append(
                    _contradiction(
                        replacement.hpo_id,
                        "modified_existing_observation_conflict",
                        [observation.observation_id, suggestion.suggestion_id],
                        [observation.state.value, replacement.state],
                        [observation.source_reference or observation.observation_id, suggestion.source_snippet_id],
                    )
                )
    for suggestion in suggestions:
        supplied_actions = actions.get(suggestion.suggestion_id, [])
        action_states = {item.action.value for item in supplied_actions}
        if len(action_states) > 1:
            records.append(_contradiction(suggestion.hpo_id, "incompatible_reviewer_decisions", [suggestion.suggestion_id], sorted(action_states), [suggestion.source_snippet_id]))
    unique = {(item.contradiction_type, tuple(item.involved_record_ids), tuple(item.involved_states)): item for item in records}
    return sorted(unique.values(), key=lambda item: (item.hpo_id, item.contradiction_type, item.contradiction_id))


def _contradiction(hpo_id: str, kind: str, ids: list[str], states: list[str], sources: list[str]) -> ContradictionRecord:
    stable_ids = sorted(set(ids))
    stable_states = sorted(set(states))
    stable_sources = sorted(set(sources))
    return ContradictionRecord(
        contradiction_id=_stable_id("hpo-contradiction", HPO_ALGORITHM_VERSION, hpo_id, kind, *stable_ids, *stable_states),
        hpo_id=hpo_id,
        involved_record_ids=stable_ids,
        contradiction_type=kind,
        involved_states=stable_states,
        source_references=stable_sources,
    )


def _promote(suggestions: list[HpoSuggestion], case: ClinicalCaseIntake) -> list[PromotedObservation]:
    existing = {(item.hpo_id, item.state.value, item.onset_text) for item in case.phenotypes if item.hpo_id and item.review_state.value == "confirmed"}
    promoted: list[PromotedObservation] = []
    for suggestion in suggestions:
        action = suggestion.reviewer_action
        if not action or action.action not in {HpoReviewStatus.CONFIRMED, HpoReviewStatus.MODIFIED} or suggestion.contradiction_references:
            continue
        replacement = suggestion.validated_modification
        if action.action == HpoReviewStatus.MODIFIED and replacement is None:
            continue
        hpo_id = replacement.hpo_id if replacement else suggestion.hpo_id
        label = replacement.canonical_label if replacement else suggestion.canonical_label
        state = replacement.state if replacement else suggestion.proposed_state
        onset = replacement.onset_text if replacement else suggestion.onset.detected_text if suggestion.onset else None
        key = (hpo_id, state, onset)
        if key in existing:
            continue
        existing.add(key)
        promoted.append(
            PromotedObservation(
                observation_id=_stable_id("hpo-observation", HPO_ALGORITHM_VERSION, case.pseudonymous_case_id, suggestion.suggestion_id, hpo_id, state, onset or ""),
                suggestion_id=suggestion.suggestion_id,
                supplied_term=label or suggestion.canonical_label,
                hpo_id=hpo_id,
                state=state,
                onset_text=onset,
                source_reference=suggestion.source_snippet_id,
                redacted_source_span=suggestion.matched_substring,
                reviewer_provenance=action.provenance,
            )
        )
    return promoted


def _stable_id(prefix: str, *parts: object) -> str:
    canonical = "\x1f".join(str(part) for part in parts)
    return f"{prefix}-{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:20]}"


def _curation_issue(item: ClinicalIntakeIssue) -> CurationIssue:
    return CurationIssue(code=item.code, field=item.field, record_id=item.record_id, message=item.message)


def _curation_block(item: ClinicalPolicyBlock) -> CurationPolicyBlock:
    return CurationPolicyBlock(code=item.code, category=item.category, message=item.message)


def _stable_issues(items: list[CurationIssue]) -> list[CurationIssue]:
    unique = {(item.code, item.field or "", item.record_id or "", item.message): item for item in items}
    return [unique[key] for key in sorted(unique)]


def _duplicates(values) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)
