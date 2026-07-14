from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from app.insilicopop.clinical.models import ClinicalCaseIntake, HypothesisType
from app.insilicopop.clinical.pedigree_models import (
    AuditReviewAction,
    PedigreeAuditIssue,
    PedigreeInheritanceAuditRequest,
    RelationshipType,
)


@dataclass(frozen=True)
class PedigreeValidationResult:
    validation_errors: list[PedigreeAuditIssue]
    validation_warnings: list[PedigreeAuditIssue]
    missing_information: list[PedigreeAuditIssue]
    relationship_issues: list[PedigreeAuditIssue]
    review_actions: list[AuditReviewAction]


def stable_identifier(prefix: str, *parts: Any) -> str:
    canonical = json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return f"{prefix}-{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:20]}"


def issue(
    code: str,
    explanation: str,
    severity: str,
    *,
    member_ids: Iterable[str] = (),
    candidate_ids: Iterable[str] = (),
    record_ids: Iterable[str] = (),
    supplied_facts: dict[str, Any] | None = None,
    provenance_ids: Iterable[str] = (),
) -> PedigreeAuditIssue:
    members = sorted(set(member_ids))
    candidates = sorted(set(candidate_ids))
    records = sorted(set(record_ids))
    facts = _canonical_value(supplied_facts or {})
    provenance = sorted(set(provenance_ids))
    issue_id = stable_identifier(
        "pedigree-issue",
        code,
        explanation,
        severity,
        members,
        candidates,
        records,
        facts,
        provenance,
    )
    return PedigreeAuditIssue(
        issue_id=issue_id,
        code=code,
        involved_member_ids=members,
        involved_candidate_variant_ids=candidates,
        involved_record_ids=records,
        supplied_facts=facts,
        explanation=explanation,
        severity=severity,  # type: ignore[arg-type]
        provenance_source_ids=provenance,
    )


def review_action(
    code: str,
    explanation: str,
    *,
    audit_target_id: str | None = None,
    member_ids: Iterable[str] = (),
    candidate_ids: Iterable[str] = (),
) -> AuditReviewAction:
    members = sorted(set(member_ids))
    candidates = sorted(set(candidate_ids))
    return AuditReviewAction(
        action_id=stable_identifier(
            "pedigree-review-action",
            code,
            explanation,
            audit_target_id or "",
            members,
            candidates,
        ),
        code=code,
        audit_target_id=audit_target_id,
        involved_member_ids=members,
        involved_candidate_variant_ids=candidates,
        explanation=explanation,
    )


def validate_pedigree_audit_request(
    case: ClinicalCaseIntake,
    request: PedigreeInheritanceAuditRequest,
) -> PedigreeValidationResult:
    errors: list[PedigreeAuditIssue] = []
    warnings: list[PedigreeAuditIssue] = []
    missing: list[PedigreeAuditIssue] = []
    relationship_issues: list[PedigreeAuditIssue] = []
    actions: list[AuditReviewAction] = []

    member_ids = [item.family_member_id for item in case.pedigree]
    member_set = set(member_ids)
    candidate_ids = [item.candidate_id for item in case.candidate_variants]
    candidate_set = set(candidate_ids)
    hypotheses = {item.hypothesis_id: item for item in case.hypotheses}
    provenance_set = _provenance_source_ids(case)

    _duplicate_issues(errors, "duplicate_member_id", member_ids, "Supplied pedigree member IDs must be unique.")
    _duplicate_issues(errors, "duplicate_relationship_id", [item.relationship_id for item in request.relationships], "Supplied relationship record IDs must be unique.")
    _duplicate_issues(errors, "duplicate_variant_observation_id", [item.observation_id for item in request.variant_observations], "Supplied family variant-observation IDs must be unique.")
    _duplicate_issues(errors, "duplicate_audit_target_id", [item.audit_target_id for item in request.audit_targets], "Supplied audit-target IDs must be unique.")
    _duplicate_issues(errors, "duplicate_phase_declaration_id", [item.phase_declaration_id for item in request.phase_declarations], "Supplied phase-declaration IDs must be unique.")

    if request.proband_member_id not in member_set:
        errors.append(issue("proband_member_not_found", "The explicitly supplied proband ID is not present in the supplied pedigree members.", "error", member_ids=[request.proband_member_id]))
    proband_labels = sorted(item.family_member_id for item in case.pedigree if item.relationship_to_proband.casefold() == "proband")
    if request.proband_member_id in member_set and proband_labels and request.proband_member_id not in proband_labels:
        relationship_issues.append(
            issue(
                "supplied_proband_declaration_conflict",
                "The explicit proband ID and supplied relationship-to-proband records cannot be reconciled under the bounded rule and require manual verification.",
                "conflict",
                member_ids=[request.proband_member_id, *proband_labels],
            )
        )
    if len(proband_labels) > 1:
        relationship_issues.append(issue("multiple_supplied_proband_labels", "More than one supplied member record is labelled as the proband and requires manual verification.", "conflict", member_ids=proband_labels))

    biological_edges: list[tuple[str, str, str]] = []
    seen_edges: dict[tuple[str, str], str] = {}
    parents_by_child: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for relationship in sorted(request.relationships, key=lambda item: item.relationship_id):
        _validate_provenance_refs(errors, relationship.provenance_source_ids, provenance_set, relationship.relationship_id)
        if relationship.relationship_type == RelationshipType.OTHER_SUPPLIED:
            warnings.append(issue("unsupported_supplied_relationship_structure", "The supplied relationship record is retained but is not interpreted by the bounded inheritance audit.", "warning", member_ids=[relationship.parent_member_id, relationship.child_member_id], record_ids=[relationship.relationship_id]))
            continue
        parent = relationship.parent_member_id
        child = relationship.child_member_id
        if parent == child:
            relationship_issues.append(issue("self_parent_reference", "A supplied biological-parent record references the same pseudonymous member as parent and child.", "conflict", member_ids=[parent], record_ids=[relationship.relationship_id]))
            continue
        missing_members = sorted({item for item in (parent, child) if item not in member_set})
        if missing_members:
            relationship_issues.append(issue("missing_member_reference", "A supplied biological-parent record references a pseudonymous member that is not present.", "conflict", member_ids=missing_members, record_ids=[relationship.relationship_id]))
            continue
        edge = (parent, child)
        if edge in seen_edges:
            relationship_issues.append(issue("duplicate_biological_parent_edge", "The same supplied biological-parent edge appears more than once.", "conflict", member_ids=[parent, child], record_ids=[seen_edges[edge], relationship.relationship_id]))
            continue
        seen_edges[edge] = relationship.relationship_id
        biological_edges.append((relationship.relationship_id, parent, child))
        parents_by_child[child].append((parent, relationship.relationship_id))

    for child, parents in sorted(parents_by_child.items()):
        if len(parents) > 2:
            relationship_issues.append(issue("excess_biological_parent_edges", "More than two biological-parent edges were explicitly supplied for one child.", "conflict", member_ids=[child, *(parent for parent, _ in parents)], record_ids=[record_id for _, record_id in parents]))

    cycle_members = _cycle_members([(parent, child) for _, parent, child in biological_edges])
    if cycle_members:
        relationship_issues.append(issue("pedigree_cycle", "The supplied biological-parent graph contains a directed cycle and cannot be evaluated without changing supplied records.", "conflict", member_ids=cycle_members))

    phases = {item.phase_declaration_id: item for item in request.phase_declarations}
    phase_ids = set(phases)
    for phase in request.phase_declarations:
        _validate_provenance_refs(errors, phase.provenance_source_ids, provenance_set, phase.phase_declaration_id)
        unknown = sorted(set(phase.candidate_variant_ids) - candidate_set)
        if unknown:
            errors.append(issue("unknown_phase_candidate_reference", "A phase declaration references a candidate ID that is not present in the clinical intake.", "error", candidate_ids=unknown, record_ids=[phase.phase_declaration_id]))

    observation_pairs: Counter[tuple[str, str]] = Counter()
    for observation in request.variant_observations:
        _validate_provenance_refs(errors, observation.provenance_source_ids, provenance_set, observation.observation_id)
        if observation.family_member_id not in member_set:
            errors.append(issue("unknown_observation_member_reference", "A family variant observation references a member ID that is not present.", "error", member_ids=[observation.family_member_id], candidate_ids=[observation.candidate_variant_id], record_ids=[observation.observation_id]))
        if observation.candidate_variant_id not in candidate_set:
            errors.append(issue("unknown_observation_candidate_reference", "A family variant observation references a candidate ID that is not present.", "error", member_ids=[observation.family_member_id], candidate_ids=[observation.candidate_variant_id], record_ids=[observation.observation_id]))
        observation_pairs[(observation.family_member_id, observation.candidate_variant_id)] += 1
    for (member_id, candidate_id), count in sorted(observation_pairs.items()):
        if count > 1:
            errors.append(issue("duplicate_member_candidate_observation", "More than one supplied observation exists for the same member and candidate ID.", "error", member_ids=[member_id], candidate_ids=[candidate_id], supplied_facts={"observation_count": count}))

    for target in request.audit_targets:
        if target.x_linked_context is not None:
            _validate_provenance_refs(
                errors,
                target.x_linked_context.provenance_source_ids,
                provenance_set,
                target.audit_target_id,
            )
        hypothesis = hypotheses.get(target.hypothesis_id)
        if hypothesis is None:
            errors.append(issue("unknown_audit_hypothesis_reference", "An audit target references a hypothesis ID that is not present.", "error", record_ids=[target.audit_target_id, target.hypothesis_id]))
        elif hypothesis.hypothesis_type != HypothesisType.INHERITANCE or hypothesis.inheritance_candidate is None:
            errors.append(issue("audit_hypothesis_not_typed_inheritance", "An audit target must reference an existing typed inheritance hypothesis.", "error", record_ids=[target.audit_target_id, target.hypothesis_id]))
        unknown_candidates = sorted(set(target.candidate_variant_ids) - candidate_set)
        if unknown_candidates:
            errors.append(issue("unknown_audit_candidate_reference", "An audit target references a candidate ID that is not present.", "error", candidate_ids=unknown_candidates, record_ids=[target.audit_target_id]))
        if len(set(target.candidate_variant_ids)) != len(target.candidate_variant_ids):
            errors.append(issue("duplicate_audit_candidate_reference", "An audit target contains a repeated candidate ID.", "error", candidate_ids=target.candidate_variant_ids, record_ids=[target.audit_target_id]))
        if target.phase_declaration_id and target.phase_declaration_id not in phase_ids:
            errors.append(issue("unknown_phase_declaration_reference", "An audit target references a phase declaration ID that is not present.", "error", record_ids=[target.audit_target_id, target.phase_declaration_id]))
        elif target.phase_declaration_id:
            phase = phases[target.phase_declaration_id]
            if sorted(phase.candidate_variant_ids) != sorted(target.candidate_variant_ids):
                errors.append(
                    issue(
                        "phase_candidate_mapping_conflict",
                        "The explicit audit-target candidate IDs and phase-declaration candidate IDs differ and are not reconciled or normalized.",
                        "error",
                        candidate_ids=[*target.candidate_variant_ids, *phase.candidate_variant_ids],
                        record_ids=[target.audit_target_id, phase.phase_declaration_id],
                    )
                )

    if not request.audit_targets:
        missing.append(issue("audit_targets_not_supplied", "No explicit inheritance audit targets were supplied.", "requirement"))

    for relationship_issue in relationship_issues:
        actions.append(review_action("verify_supplied_relationship_records", "Manually verify the bounded supplied relationship records before interpreting the affected audit target.", member_ids=relationship_issue.involved_member_ids))

    return PedigreeValidationResult(
        validation_errors=stable_issues(errors),
        validation_warnings=stable_issues(warnings),
        missing_information=stable_issues(missing),
        relationship_issues=stable_issues(relationship_issues),
        review_actions=stable_review_actions(actions),
    )


def stable_issues(items: Iterable[PedigreeAuditIssue]) -> list[PedigreeAuditIssue]:
    unique = {item.issue_id: item for item in items}
    return sorted(unique.values(), key=lambda item: (item.code, item.issue_id))


def stable_review_actions(items: Iterable[AuditReviewAction]) -> list[AuditReviewAction]:
    unique = {item.action_id: item for item in items}
    return sorted(unique.values(), key=lambda item: (item.code, item.action_id))


def _duplicate_issues(target: list[PedigreeAuditIssue], code: str, values: list[str], explanation: str) -> None:
    for value, count in sorted(Counter(values).items()):
        if count > 1:
            target.append(issue(code, explanation, "error", record_ids=[value], supplied_facts={"count": count}))


def _validate_provenance_refs(errors: list[PedigreeAuditIssue], supplied: list[str], known: set[str], record_id: str) -> None:
    unknown = sorted(set(supplied) - known)
    if unknown:
        errors.append(issue("unknown_provenance_reference", "A supplied audit record references a provenance source ID that is not present in the clinical intake.", "error", record_ids=[record_id, *unknown], provenance_ids=unknown))


def _provenance_source_ids(case: ClinicalCaseIntake) -> set[str]:
    values = {item.source_id for item in case.provenance}
    for member in case.pedigree:
        values.update(item.source_id for item in member.provenance)
    for candidate in case.candidate_variants:
        values.update(item.source_id for item in candidate.provenance)
    return values


def _cycle_members(edges: list[tuple[str, str]]) -> list[str]:
    graph: dict[str, set[str]] = defaultdict(set)
    nodes: set[str] = set()
    for parent, child in edges:
        graph[parent].add(child)
        nodes.update((parent, child))
    visiting: set[str] = set()
    visited: set[str] = set()
    cycle: set[str] = set()

    def visit(node: str, stack: list[str]) -> None:
        if node in visiting:
            start = stack.index(node) if node in stack else 0
            cycle.update(stack[start:])
            return
        if node in visited:
            return
        visiting.add(node)
        stack.append(node)
        for child in sorted(graph.get(node, ())):
            visit(child, stack)
        stack.pop()
        visiting.remove(node)
        visited.add(node)

    for node in sorted(nodes):
        visit(node, [])
    return sorted(cycle)


def _canonical_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _canonical_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple, set)):
        return sorted((_canonical_value(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True, default=str))
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
