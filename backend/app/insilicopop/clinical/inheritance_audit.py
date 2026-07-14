from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable

from app.insilicopop.clinical.models import (
    AffectedStatus,
    ClinicalCaseIntake,
    ClinicalIntakeIssue,
    ClinicalPolicyBlock,
    InheritanceHypothesis,
    SexForInheritance,
)
from app.insilicopop.clinical.pedigree_models import (
    AvailableParentChildTransmissionSummary,
    AuditReviewAction,
    ConfirmationState,
    FamilyVariantObservation,
    InheritanceAuditRecord,
    InheritanceAuditStatus,
    ObservationTestingState,
    ParentChildTransmissionRecord,
    PedigreeAuditIssue,
    PedigreeAuditPolicyBlock,
    PedigreeInheritanceAuditRequest,
    PedigreeInheritanceAuditResult,
    PhaseAssessment,
    PhaseEvidenceBasis,
    PhaseState,
    RelationshipType,
    SuppliedZygosity,
    VariantPresenceState,
    XLinkedAuditContext,
    XLinkedLocusContext,
    XLinkedMosaicContext,
    XLinkedSexChromosomeContext,
)
from app.insilicopop.clinical.pedigree_validation import (
    issue,
    review_action,
    stable_identifier,
    stable_issues,
    stable_review_actions,
    validate_pedigree_audit_request,
)


def build_pedigree_inheritance_audit(
    case: ClinicalCaseIntake,
    *,
    validation_errors: list[ClinicalIntakeIssue] | None = None,
    validation_warnings: list[ClinicalIntakeIssue] | None = None,
    missing_information: list[ClinicalIntakeIssue] | None = None,
    policy_blocks: list[ClinicalPolicyBlock] | None = None,
) -> PedigreeInheritanceAuditResult | None:
    request = case.pedigree_inheritance_audit
    if request is None:
        return None

    structural = validate_pedigree_audit_request(case, request)
    errors = [*_converted_intake_issues(validation_errors or [], "error"), *structural.validation_errors]
    warnings = [*_converted_intake_issues(validation_warnings or [], "warning"), *structural.validation_warnings]
    missing = [*_converted_intake_issues(missing_information or [], "requirement"), *structural.missing_information]
    blocks = _policy_blocks(policy_blocks or [])
    relationship_issues = list(structural.relationship_issues)
    mendelian: list[PedigreeAuditIssue] = []
    phase_requirements: list[PedigreeAuditIssue] = []
    relative_requirements: list[PedigreeAuditIssue] = []
    actions: list[AuditReviewAction] = list(structural.review_actions)

    members = {item.family_member_id: item for item in case.pedigree}
    candidates = {item.candidate_id: item for item in case.candidate_variants}
    hypotheses = {item.hypothesis_id: item for item in case.hypotheses}
    observations = _observation_index(request.variant_observations)
    supplied_biological_relationships = sorted(
        (item for item in request.relationships if item.relationship_type == RelationshipType.BIOLOGICAL_PARENT),
        key=lambda item: item.relationship_id,
    )
    globally_gated = bool(errors or blocks or relationship_issues)
    biological_relationships = [] if globally_gated else supplied_biological_relationships
    parents_by_child: dict[str, list[str]] = defaultdict(list)
    relationship_by_pair: dict[tuple[str, str], str] = {}
    for relationship in biological_relationships:
        parents_by_child[relationship.child_member_id].append(relationship.parent_member_id)
        relationship_by_pair[(relationship.parent_member_id, relationship.child_member_id)] = relationship.relationship_id

    transmission_records = _transmission_records(request, biological_relationships, observations)
    phase_assessments: list[PhaseAssessment] = []
    audit_records: list[InheritanceAuditRecord] = []

    for target in sorted(request.audit_targets, key=lambda item: item.audit_target_id):
        hypothesis = hypotheses.get(target.hypothesis_id)
        hypothesis_type = hypothesis.inheritance_candidate.value if hypothesis and hypothesis.inheritance_candidate else "unsupported"
        target_mendelian: list[PedigreeAuditIssue] = []
        target_missing: list[PedigreeAuditIssue] = []
        target_phase_requirements: list[PedigreeAuditIssue] = []
        target_relative_requirements: list[PedigreeAuditIssue] = []
        target_actions: list[AuditReviewAction] = []
        supporting: list[str] = []
        phase_assessment: PhaseAssessment | None = None

        if globally_gated or hypothesis is None or any(candidate_id not in candidates for candidate_id in target.candidate_variant_ids):
            status = InheritanceAuditStatus.CANNOT_EVALUATE
            explanation = "The supplied representation cannot be evaluated under the bounded rule without changing or inferring supplied records."
        elif hypothesis_type in {InheritanceHypothesis.UNKNOWN.value, InheritanceHypothesis.OTHER.value, "unsupported"}:
            status = InheritanceAuditStatus.CANNOT_EVALUATE
            explanation = "The supplied inheritance hypothesis is unknown or unsupported by the bounded deterministic rules."
        else:
            phase_required_for_rule = (
                hypothesis_type == InheritanceHypothesis.COMPOUND_HETEROZYGOUS.value
                or (
                    hypothesis_type == InheritanceHypothesis.AUTOSOMAL_RECESSIVE.value
                    and len(target.candidate_variant_ids) == 2
                )
            )
            phase_assessment = (
                _phase_assessment(target, request, observations, parents_by_child, request.proband_member_id)
                if phase_required_for_rule
                else None
            )
            if phase_assessment:
                phase_assessments.append(phase_assessment)
            status, explanation = _audit_hypothesis(
                hypothesis_type,
                target.audit_target_id,
                target.candidate_variant_ids,
                target.x_linked_context,
                request.proband_member_id,
                members,
                candidates,
                observations,
                parents_by_child,
                relationship_by_pair,
                phase_assessment,
                target_mendelian,
                target_missing,
                target_phase_requirements,
                target_relative_requirements,
                target_actions,
                supporting,
            )

        mendelian.extend(target_mendelian)
        missing.extend(target_missing)
        phase_requirements.extend(target_phase_requirements)
        relative_requirements.extend(target_relative_requirements)
        actions.extend(target_actions)
        stable_supporting = sorted(set(supporting))
        stable_relationship_issue_ids = sorted(item.issue_id for item in relationship_issues)
        stable_mendelian_ids = sorted(item.issue_id for item in target_mendelian)
        stable_missing_ids = sorted(item.issue_id for item in [*target_missing, *target_phase_requirements, *target_relative_requirements])
        phase_assessment_id = phase_assessment.assessment_id if phase_assessment else None
        audit_records.append(
            InheritanceAuditRecord(
                audit_id=stable_identifier(
                    "inheritance-audit",
                    target.audit_target_id,
                    target.hypothesis_id,
                    hypothesis_type,
                    sorted(target.candidate_variant_ids),
                    status.value,
                    explanation,
                    stable_supporting,
                    stable_relationship_issue_ids,
                    stable_mendelian_ids,
                    stable_missing_ids,
                    phase_assessment_id or "",
                ),
                audit_target_id=target.audit_target_id,
                hypothesis_id=target.hypothesis_id,
                hypothesis_type=hypothesis_type,
                candidate_variant_ids=sorted(target.candidate_variant_ids),
                status=status,
                bounded_explanation=explanation,
                supporting_record_ids=stable_supporting,
                relationship_issue_ids=stable_relationship_issue_ids,
                mendelian_inconsistency_ids=stable_mendelian_ids,
                missing_information_ids=stable_missing_ids,
                phase_assessment_id=phase_assessment_id,
            )
        )

    affected_counts = Counter(item.affected_status.value for item in case.pedigree)
    testing_counts = Counter(item.testing_availability.value for item in case.pedigree)
    transmission_summary = _transmission_summary(biological_relationships, transmission_records)
    return PedigreeInheritanceAuditResult(
        pseudonymous_case_id=case.pseudonymous_case_id,
        proband_member_id=request.proband_member_id,
        member_count=len(case.pedigree),
        biological_parent_relationship_count=len(supplied_biological_relationships),
        affected_status_summary={key: affected_counts.get(key, 0) for key in sorted(set(affected_counts) | {item.value for item in AffectedStatus})},
        testing_availability_summary={key: testing_counts[key] for key in sorted(testing_counts)},
        supplied_hypothesis_types=sorted({item.hypothesis_type for item in audit_records}),
        variant_observation_count=len(request.variant_observations),
        validation_errors=stable_issues(errors),
        validation_warnings=stable_issues(warnings),
        missing_information=stable_issues(missing),
        policy_blocks=blocks,
        relationship_issues=stable_issues(relationship_issues),
        mendelian_inconsistencies=stable_issues(mendelian),
        inheritance_audits=sorted(audit_records, key=lambda item: (item.audit_target_id, item.audit_id)),
        phase_assessments=sorted({item.assessment_id: item for item in phase_assessments}.values(), key=lambda item: (item.audit_target_id, item.assessment_id)),
        phase_requirements=stable_issues(phase_requirements),
        missing_relative_requirements=stable_issues(relative_requirements),
        review_actions=stable_review_actions(actions),
        available_parent_child_transmission_summary=transmission_summary,
        parent_child_transmission_records=transmission_records,
        reviewer_status=request.reviewer_status.value,
    )


def _audit_hypothesis(
    hypothesis_type: str,
    target_id: str,
    candidate_ids: list[str],
    x_linked_context: XLinkedAuditContext | None,
    proband_id: str,
    members,
    candidates,
    observations,
    parents_by_child,
    relationship_by_pair,
    phase_assessment,
    mendelian,
    missing,
    phase_requirements,
    relative_requirements,
    actions,
    supporting,
) -> tuple[InheritanceAuditStatus, str]:
    if hypothesis_type == InheritanceHypothesis.AUTOSOMAL_DOMINANT.value:
        return _autosomal_dominant(target_id, candidate_ids, proband_id, members, observations, parents_by_child, mendelian, missing, actions, supporting)
    if hypothesis_type == InheritanceHypothesis.AUTOSOMAL_RECESSIVE.value:
        return _autosomal_recessive(target_id, candidate_ids, proband_id, observations, phase_assessment, mendelian, missing, phase_requirements, supporting)
    if hypothesis_type == InheritanceHypothesis.X_LINKED.value:
        return _x_linked(target_id, candidate_ids, x_linked_context, proband_id, members, observations, parents_by_child, relationship_by_pair, mendelian, missing, actions, supporting)
    if hypothesis_type == InheritanceHypothesis.MITOCHONDRIAL.value:
        return _mitochondrial(target_id, candidate_ids, proband_id, members, observations, parents_by_child, mendelian, relative_requirements, actions, supporting)
    if hypothesis_type == InheritanceHypothesis.DE_NOVO.value:
        return _de_novo(target_id, candidate_ids, proband_id, observations, parents_by_child, mendelian, relative_requirements, supporting)
    if hypothesis_type == InheritanceHypothesis.COMPOUND_HETEROZYGOUS.value:
        return _compound_heterozygous(target_id, candidate_ids, proband_id, candidates, observations, phase_assessment, mendelian, missing, phase_requirements, supporting)
    return InheritanceAuditStatus.CANNOT_EVALUATE, "The supplied inheritance hypothesis is unsupported by the bounded deterministic rules."


def _autosomal_dominant(target_id, candidate_ids, proband_id, members, observations, parents_by_child, mendelian, missing, actions, supporting):
    if len(candidate_ids) != 1:
        return InheritanceAuditStatus.CANNOT_EVALUATE, "The bounded autosomal-dominant rule requires one explicit candidate ID."
    candidate_id = candidate_ids[0]
    proband = observations.get((proband_id, candidate_id))
    if not _adequate(proband):
        missing.append(_missing_observation("proband_candidate_observation_required", target_id, proband_id, candidate_id))
        return InheritanceAuditStatus.MISSING_EVIDENCE, "Specific proband candidate-observation evidence is missing."
    if proband.presence_state != VariantPresenceState.PRESENT:
        return InheritanceAuditStatus.CANNOT_EVALUATE, "The supplied proband observation does not provide a present candidate state for the bounded autosomal-dominant audit."
    supporting.append(proband.observation_id)
    partial = False
    vertical_support = False
    for (member_id, observed_candidate), observation in sorted(observations.items()):
        if observed_candidate != candidate_id or member_id == proband_id or not _adequate(observation) or member_id not in members:
            continue
        affected = members[member_id].affected_status
        if affected == AffectedStatus.AFFECTED and observation.presence_state == VariantPresenceState.PRESENT:
            supporting.append(observation.observation_id)
        elif affected == AffectedStatus.AFFECTED and observation.presence_state == VariantPresenceState.ABSENT:
            partial = True
            actions.append(review_action("review_affected_relative_candidate_absence", "The supplied affected-status and candidate-observation records require expert review. The bounded audit does not infer a biological explanation or candidate causality.", audit_target_id=target_id, member_ids=[member_id], candidate_ids=[candidate_id]))
        elif affected == AffectedStatus.UNAFFECTED and observation.presence_state == VariantPresenceState.PRESENT:
            partial = True
            actions.append(review_action("review_unaffected_supplied_carrier", "Review the supplied unaffected-status and candidate observation without treating the supplied pattern as an absolute contradiction.", audit_target_id=target_id, member_ids=[member_id], candidate_ids=[candidate_id]))
    for child_id, parent_ids in sorted(parents_by_child.items()):
        for parent_id in sorted(set(parent_ids)):
            parent_observation = observations.get((parent_id, candidate_id))
            child_observation = observations.get((child_id, candidate_id))
            if (
                parent_id in members
                and child_id in members
                and members[parent_id].affected_status == AffectedStatus.AFFECTED
                and members[child_id].affected_status == AffectedStatus.AFFECTED
                and _adequate(parent_observation)
                and _adequate(child_observation)
                and parent_observation.presence_state == VariantPresenceState.PRESENT
                and child_observation.presence_state == VariantPresenceState.PRESENT
            ):
                vertical_support = True
                supporting.extend([parent_observation.observation_id, child_observation.observation_id])
    parents = parents_by_child.get(proband_id, [])
    if len(parents) == 2:
        parent_observations = [observations.get((parent, candidate_id)) for parent in parents]
        if all(_adequate(item) and item.presence_state == VariantPresenceState.ABSENT for item in parent_observations):
            partial = True
            actions.append(
                review_action(
                    "review_candidate_absent_supplied_parent_records",
                    "Review the supplied parent-child candidate observations; the bounded autosomal-dominant audit does not infer a cause for the supplied pattern.",
                    audit_target_id=target_id,
                    member_ids=[proband_id, *parents],
                    candidate_ids=[candidate_id],
                )
            )
    if partial or not vertical_support:
        return InheritanceAuditStatus.PARTIALLY_CONSISTENT, "The available supplied evidence is partially consistent but incomplete or requires review."
    return InheritanceAuditStatus.CONSISTENT, "The supplied records are consistent with the proposed autosomal-dominant hypothesis under the bounded available records."


def _autosomal_recessive(target_id, candidate_ids, proband_id, observations, phase_assessment, mendelian, missing, phase_requirements, supporting):
    proband_observations = [observations.get((proband_id, candidate_id)) for candidate_id in candidate_ids]
    if not candidate_ids or any(not _adequate(item) for item in proband_observations):
        missing.append(_missing_observation("proband_allele_observation_required", target_id, proband_id, candidate_ids[0] if candidate_ids else "unsupplied"))
        return InheritanceAuditStatus.MISSING_EVIDENCE, "Required supplied proband allele evidence is missing."
    present = [item for item in proband_observations if item.presence_state == VariantPresenceState.PRESENT]
    supporting.extend(item.observation_id for item in present)
    if len(candidate_ids) == 1 and present and present[0].zygosity == SuppliedZygosity.HOMOZYGOUS:
        return InheritanceAuditStatus.CONSISTENT, "The supplied homozygous candidate record is consistent with the proposed autosomal-recessive hypothesis under the bounded available records."
    if len(candidate_ids) < 2 or len(present) < 2:
        missing.append(issue("required_second_candidate_missing", "A required second exact supplied candidate allele is missing; no second allele is inferred.", "requirement", member_ids=[proband_id], candidate_ids=candidate_ids, record_ids=[target_id]))
        return InheritanceAuditStatus.MISSING_EVIDENCE, "Required second-allele evidence is missing."
    if len(candidate_ids) > 2:
        return InheritanceAuditStatus.CANNOT_EVALUATE, "The bounded autosomal-recessive two-candidate representation cannot evaluate more than two candidate IDs."
    if phase_assessment and phase_assessment.assessment in {"confirmed_in_trans", "supported_in_trans_by_supplied_parental_observations"}:
        return InheritanceAuditStatus.CONSISTENT, "The supplied two-candidate records are consistent with the proposed autosomal-recessive hypothesis under the bounded available records."
    phase_requirements.append(issue("phase_evidence_required", "Explicit phase or exact qualifying supplied parental observations are required for the two-candidate autosomal-recessive audit.", "requirement", candidate_ids=candidate_ids, record_ids=[target_id]))
    return InheritanceAuditStatus.MISSING_EVIDENCE, "Required phase evidence is missing."


def _x_linked(target_id, candidate_ids, x_linked_context, proband_id, members, observations, parents_by_child, relationship_by_pair, mendelian, missing, actions, supporting):
    if len(candidate_ids) != 1:
        return InheritanceAuditStatus.CANNOT_EVALUATE, "The bounded X-linked rule requires one explicit candidate ID."
    candidate_id = candidate_ids[0]
    if x_linked_context is None:
        missing.append(issue("x_linked_audit_context_required", "Explicit structured X-linked locus, sex-chromosome, and mosaic context is required; it is not derived from candidate text or coordinates.", "requirement", candidate_ids=[candidate_id], record_ids=[target_id]))
        return InheritanceAuditStatus.MISSING_EVIDENCE, "Required structured X-linked audit context is missing."
    if x_linked_context.locus_context == XLinkedLocusContext.UNKNOWN:
        return InheritanceAuditStatus.CANNOT_EVALUATE, "The supplied X-linked locus context is unknown and cannot be evaluated under the bounded rule."
    if x_linked_context.locus_context == XLinkedLocusContext.PSEUDOAUTOSOMAL_X:
        return InheritanceAuditStatus.CANNOT_EVALUATE, "The supplied pseudoautosomal X context is outside the bounded non-pseudoautosomal X-linked transmission rule."
    if x_linked_context.locus_context == XLinkedLocusContext.NON_X:
        return InheritanceAuditStatus.CANNOT_EVALUATE, "The supplied non-X locus context cannot be evaluated as an X-linked target."
    if x_linked_context.sex_chromosome_context != XLinkedSexChromosomeContext.SUFFICIENT_FOR_BOUNDED_RULE:
        return InheritanceAuditStatus.CANNOT_EVALUATE, "The supplied sex-chromosome context is not sufficient for the bounded X-linked rule."
    if x_linked_context.mosaic_context != XLinkedMosaicContext.NOT_INDICATED_IN_SUPPLIED_RECORDS:
        return InheritanceAuditStatus.CANNOT_EVALUATE, "The supplied mosaic context is unresolved or outside the bounded X-linked rule."
    proband_member = members.get(proband_id)
    if not proband_member or proband_member.sex_for_inheritance not in {SexForInheritance.MALE, SexForInheritance.FEMALE}:
        missing.append(issue("sex_for_inheritance_required", "An explicit structured sex-for-inheritance value is required for this bounded X-linked audit.", "requirement", member_ids=[proband_id], candidate_ids=[candidate_id], record_ids=[target_id]))
        return InheritanceAuditStatus.MISSING_EVIDENCE, "Required structured sex-for-inheritance evidence is missing."
    proband = observations.get((proband_id, candidate_id))
    if not _adequate(proband):
        missing.append(_missing_observation("proband_candidate_observation_required", target_id, proband_id, candidate_id))
        return InheritanceAuditStatus.MISSING_EVIDENCE, "Specific proband candidate-observation evidence is missing."
    if proband.presence_state != VariantPresenceState.PRESENT:
        return InheritanceAuditStatus.CANNOT_EVALUATE, "The supplied proband observation does not provide a present candidate state for the bounded X-linked audit."
    supporting.append(proband.observation_id)
    for parent_id in parents_by_child.get(proband_id, []):
        parent = members.get(parent_id)
        parent_observation = observations.get((parent_id, candidate_id))
        if parent and parent.sex_for_inheritance == SexForInheritance.MALE and proband_member.sex_for_inheritance == SexForInheritance.MALE and _adequate(parent_observation) and parent_observation.presence_state == VariantPresenceState.PRESENT:
            relationship_id = relationship_by_pair.get((parent_id, proband_id), "")
            explanation = "The supplied non-pseudoautosomal X-linked candidate and parent-child observation records conflict under this bounded transmission rule. Verify the supplied records and review manually."
            mendelian.append(issue("x_linked_father_to_son_supplied_record_conflict", explanation, "conflict", member_ids=[parent_id, proband_id], candidate_ids=[candidate_id], record_ids=[relationship_id, parent_observation.observation_id, proband.observation_id]))
            return InheritanceAuditStatus.INCONSISTENT, explanation
    if proband_member.sex_for_inheritance == SexForInheritance.FEMALE:
        actions.append(review_action("review_female_x_linked_record", "Review the supplied female X-linked record without applying affected-status or X-inactivation assumptions.", audit_target_id=target_id, member_ids=[proband_id], candidate_ids=[candidate_id]))
        return InheritanceAuditStatus.PARTIALLY_CONSISTENT, "The supplied female X-linked record is partially consistent and requires expert review."
    if proband.zygosity != SuppliedZygosity.HEMIZYGOUS:
        return InheritanceAuditStatus.PARTIALLY_CONSISTENT, "The candidate is supplied as present, but the bounded hemizygous state required for a complete X-linked audit is not confirmed."
    return InheritanceAuditStatus.CONSISTENT, "The supplied records are consistent with the proposed X-linked hypothesis under the bounded available records."


def _mitochondrial(target_id, candidate_ids, proband_id, members, observations, parents_by_child, mendelian, relative_requirements, actions, supporting):
    if len(candidate_ids) != 1:
        return InheritanceAuditStatus.CANNOT_EVALUATE, "The bounded mitochondrial rule requires one explicit candidate ID."
    candidate_id = candidate_ids[0]
    proband = observations.get((proband_id, candidate_id))
    if not _adequate(proband) or proband.presence_state != VariantPresenceState.PRESENT:
        relative_requirements.append(_missing_observation("proband_candidate_observation_required", target_id, proband_id, candidate_id))
        return InheritanceAuditStatus.MISSING_EVIDENCE, "Required proband candidate-observation evidence is missing."
    supporting.append(proband.observation_id)
    parents = parents_by_child.get(proband_id, [])
    supplied_maternal = [parent for parent in parents if parent in members and members[parent].sex_for_inheritance == SexForInheritance.FEMALE]
    supplied_paternal = [parent for parent in parents if parent in members and members[parent].sex_for_inheritance == SexForInheritance.MALE]
    for parent in supplied_paternal:
        parent_observation = observations.get((parent, candidate_id))
        if parent_observation and parent_observation.presence_state == VariantPresenceState.PRESENT:
            explanation = "A supplied paternal mtDNA candidate observation requires expert review. The bounded audit does not resolve inheritance, relationship, assay, tissue, heteroplasmy, or technical explanations."
            actions.append(review_action("paternal_mtdna_observation_requires_review", explanation, audit_target_id=target_id, member_ids=[parent, proband_id], candidate_ids=[candidate_id]))
            supplied_context = {proband.zygosity, parent_observation.zygosity}
            if not _adequate(parent_observation) or not supplied_context <= {SuppliedZygosity.HETEROPLASMIC, SuppliedZygosity.HOMOPLASMIC}:
                return InheritanceAuditStatus.CANNOT_EVALUATE, explanation
            return InheritanceAuditStatus.PARTIALLY_CONSISTENT, explanation
    if not supplied_maternal:
        relative_requirements.append(issue("supplied_maternal_parent_record_required", "An explicit supplied biological-parent record with the structured sex-for-inheritance value required for the maternal-line rule is missing.", "requirement", member_ids=[proband_id], candidate_ids=[candidate_id], record_ids=[target_id]))
        return InheritanceAuditStatus.MISSING_EVIDENCE, "Required supplied maternal-line evidence is missing."
    maternal_observation = observations.get((supplied_maternal[0], candidate_id))
    if not _adequate(maternal_observation):
        relative_requirements.append(_missing_observation("supplied_maternal_candidate_observation_required", target_id, supplied_maternal[0], candidate_id))
        return InheritanceAuditStatus.MISSING_EVIDENCE, "Required supplied maternal candidate-observation evidence is missing."
    if maternal_observation.presence_state != VariantPresenceState.PRESENT:
        return InheritanceAuditStatus.PARTIALLY_CONSISTENT, "The supplied maternal-line records are incomplete or ambiguous under the bounded rule."
    supporting.append(maternal_observation.observation_id)
    if proband.zygosity == SuppliedZygosity.HETEROPLASMIC or maternal_observation.zygosity == SuppliedZygosity.HETEROPLASMIC:
        actions.append(review_action("review_heteroplasmic_supplied_records", "Review the supplied heteroplasmic states without applying a threshold or tissue-level assumption.", audit_target_id=target_id, member_ids=[proband_id, supplied_maternal[0]], candidate_ids=[candidate_id]))
        return InheritanceAuditStatus.PARTIALLY_CONSISTENT, "The supplied maternal-line records are partially consistent, with heteroplasmic uncertainty retained."
    return InheritanceAuditStatus.CONSISTENT, "The supplied records are consistent with the proposed mitochondrial hypothesis under the bounded available records."


def _de_novo(target_id, candidate_ids, proband_id, observations, parents_by_child, mendelian, relative_requirements, supporting):
    if len(candidate_ids) != 1:
        return InheritanceAuditStatus.CANNOT_EVALUATE, "The bounded de novo rule requires one explicit candidate ID."
    candidate_id = candidate_ids[0]
    proband = observations.get((proband_id, candidate_id))
    if not _adequate(proband) or proband.presence_state != VariantPresenceState.PRESENT:
        relative_requirements.append(_missing_observation("proband_candidate_observation_required", target_id, proband_id, candidate_id))
        return InheritanceAuditStatus.MISSING_EVIDENCE, "Required proband candidate-observation evidence is missing."
    supporting.append(proband.observation_id)
    parents = sorted(set(parents_by_child.get(proband_id, [])))
    if len(parents) != 2:
        relative_requirements.append(issue("two_supplied_parent_records_required", "Exactly two explicit supplied biological-parent records are required for the bounded de novo audit.", "requirement", member_ids=[proband_id, *parents], candidate_ids=[candidate_id], record_ids=[target_id]))
        return InheritanceAuditStatus.MISSING_EVIDENCE, "Required supplied parent records are missing."
    parent_observations = [observations.get((parent, candidate_id)) for parent in parents]
    if any(not _adequate(item) for item in parent_observations):
        for parent, observation in zip(parents, parent_observations):
            if not _adequate(observation):
                relative_requirements.append(_missing_observation("adequately_tested_parent_observation_required", target_id, parent, candidate_id))
        return InheritanceAuditStatus.MISSING_EVIDENCE, "A supplied parent is missing, unavailable, unknown, or not adequately tested."
    positive = [(parent, observation) for parent, observation in zip(parents, parent_observations) if observation.presence_state == VariantPresenceState.PRESENT]
    if positive:
        mendelian.append(issue("de_novo_parent_positive", "A supplied parent candidate-positive record conflicts with the supplied de novo hypothesis under the bounded rule.", "conflict", member_ids=[proband_id, *(parent for parent, _ in positive)], candidate_ids=[candidate_id], record_ids=[proband.observation_id, *(observation.observation_id for _, observation in positive)]))
        return InheritanceAuditStatus.INCONSISTENT, "A supplied parent candidate-positive record is inconsistent with the supplied de novo hypothesis."
    if not all(item.presence_state == VariantPresenceState.ABSENT for item in parent_observations):
        return InheritanceAuditStatus.MISSING_EVIDENCE, "Both supplied parents require explicit candidate-absent states for the bounded de novo audit."
    supporting.extend(item.observation_id for item in parent_observations)
    return InheritanceAuditStatus.CONSISTENT, "Consistent with the supplied de novo hypothesis under the bounded available records."


def _compound_heterozygous(target_id, candidate_ids, proband_id, candidates, observations, phase_assessment, mendelian, missing, phase_requirements, supporting):
    if len(candidate_ids) != 2 or len(set(candidate_ids)) != 2:
        missing.append(issue("two_distinct_candidate_ids_required", "Exactly two distinct supplied candidate IDs are required for the compound-heterozygous audit.", "requirement", member_ids=[proband_id], candidate_ids=candidate_ids, record_ids=[target_id]))
        return InheritanceAuditStatus.MISSING_EVIDENCE, "Two distinct supplied candidate IDs are required."
    genes = [candidates[candidate_id].gene for candidate_id in candidate_ids]
    if any(not gene or not gene.strip() for gene in genes):
        missing.append(issue("exact_supplied_gene_identifier_required", "A non-empty exact supplied gene identifier is required for each candidate; no identifier or alias is inferred.", "requirement", candidate_ids=candidate_ids, record_ids=[target_id]))
        return InheritanceAuditStatus.MISSING_EVIDENCE, "Required exact supplied gene identifiers are missing."
    if any(gene != gene.strip() for gene in genes):
        missing.append(issue("exact_supplied_gene_identifier_format_review_required", "A supplied gene identifier contains surrounding whitespace and is preserved exactly; it is not normalized for deterministic comparison.", "requirement", candidate_ids=candidate_ids, record_ids=[target_id]))
        return InheritanceAuditStatus.CANNOT_EVALUATE, "A supplied exact gene identifier requires formatting review before deterministic comparison."
    if genes[0] != genes[1]:
        return InheritanceAuditStatus.CANNOT_EVALUATE, "The exact supplied gene identifiers differ; the candidates are not combined and no equivalence is inferred."
    proband_observations = [observations.get((proband_id, candidate_id)) for candidate_id in candidate_ids]
    if any(not _adequate(item) or item.presence_state != VariantPresenceState.PRESENT for item in proband_observations):
        missing.append(issue("proband_two_candidate_observations_required", "The proband must have adequate supplied present observations for both exact candidate IDs.", "requirement", member_ids=[proband_id], candidate_ids=candidate_ids, record_ids=[target_id]))
        return InheritanceAuditStatus.MISSING_EVIDENCE, "Required proband observations for both candidates are missing."
    supporting.extend(item.observation_id for item in proband_observations)
    if phase_assessment is None or phase_assessment.assessment == "unknown":
        phase_requirements.append(issue("reciprocal_parental_phase_observations_required", "Explicit reviewed phase or complete reciprocal supplied parental observations are required; two positive-only parental observations are insufficient.", "requirement", member_ids=[proband_id], candidate_ids=candidate_ids, record_ids=[target_id]))
        return InheritanceAuditStatus.MISSING_EVIDENCE, "Required phase evidence is missing."
    if phase_assessment.assessment == "confirmed_in_cis":
        mendelian.append(issue("compound_heterozygous_confirmed_in_cis", "The supplied confirmed-in-cis phase record conflicts with the supplied compound-heterozygous hypothesis.", "conflict", member_ids=[proband_id], candidate_ids=candidate_ids, record_ids=[phase_assessment.assessment_id]))
        return InheritanceAuditStatus.INCONSISTENT, "The supplied confirmed-in-cis state is inconsistent with the supplied compound-heterozygous hypothesis."
    if phase_assessment.assessment == "presumed_in_trans":
        return InheritanceAuditStatus.PARTIALLY_CONSISTENT, "The supplied presumed-in-trans state is partially consistent and is not promoted to confirmed phase."
    if phase_assessment.assessment in {"confirmed_in_trans", "supported_in_trans_by_supplied_parental_observations"}:
        supporting.extend(phase_assessment.supporting_observation_ids)
        return InheritanceAuditStatus.CONSISTENT, "The supplied records are consistent with the proposed compound-heterozygous hypothesis under the bounded available records."
    return InheritanceAuditStatus.CANNOT_EVALUATE, "The supplied phase representation cannot be evaluated under the bounded rule."


def _phase_assessment(target, request, observations, parents_by_child, proband_id) -> PhaseAssessment | None:
    declaration = next((item for item in request.phase_declarations if item.phase_declaration_id == target.phase_declaration_id), None)
    candidate_ids = sorted(target.candidate_variant_ids)
    supplied_state = declaration.state.value if declaration else "not_supplied"
    supporting_ids: list[str] = []
    if declaration and sorted(declaration.candidate_variant_ids) != candidate_ids:
        assessment = "cannot_evaluate"
    elif (
        declaration
        and declaration.state == PhaseState.CONFIRMED_IN_TRANS
        and declaration.evidence_basis == PhaseEvidenceBasis.DIRECTLY_SUPPLIED
        and declaration.review_state.value == "confirmed"
    ):
        assessment = "confirmed_in_trans"
    elif (
        declaration
        and declaration.state == PhaseState.CONFIRMED_IN_CIS
        and declaration.evidence_basis == PhaseEvidenceBasis.DIRECTLY_SUPPLIED
        and declaration.review_state.value == "confirmed"
    ):
        assessment = "confirmed_in_cis"
    elif declaration and declaration.state == PhaseState.PRESUMED_IN_TRANS:
        assessment = "presumed_in_trans"
    elif declaration and declaration.state == PhaseState.UNKNOWN:
        assessment = "unknown"
    elif declaration and declaration.state == PhaseState.CANNOT_EVALUATE:
        assessment = "cannot_evaluate"
    elif declaration:
        assessment = "unknown"
    else:
        parental_support = _parental_in_trans_support(candidate_ids, proband_id, observations, parents_by_child)
        if parental_support:
            assessment = "supported_in_trans_by_supplied_parental_observations"
            supporting_ids = parental_support
        else:
            assessment = "unknown"
    return PhaseAssessment(
        assessment_id=stable_identifier("phase-assessment", target.audit_target_id, declaration.phase_declaration_id if declaration else "", supplied_state, assessment, candidate_ids, supporting_ids),
        audit_target_id=target.audit_target_id,
        phase_declaration_id=declaration.phase_declaration_id if declaration else None,
        supplied_state=supplied_state,
        assessment=assessment,  # type: ignore[arg-type]
        involved_candidate_variant_ids=candidate_ids,
        supporting_observation_ids=sorted(supporting_ids),
    )


def _parental_in_trans_support(candidate_ids, proband_id, observations, parents_by_child) -> list[str]:
    if len(candidate_ids) != 2:
        return []
    parents = sorted(set(parents_by_child.get(proband_id, [])))
    if len(parents) != 2:
        return []
    first_candidate, second_candidate = candidate_ids
    for first_parent in parents:
        for second_parent in parents:
            if first_parent == second_parent:
                continue
            first_present = observations.get((first_parent, first_candidate))
            first_absent = observations.get((first_parent, second_candidate))
            second_absent = observations.get((second_parent, first_candidate))
            second_present = observations.get((second_parent, second_candidate))
            if (
                _adequate(first_present)
                and first_present.presence_state == VariantPresenceState.PRESENT
                and _adequate(first_absent)
                and first_absent.presence_state == VariantPresenceState.ABSENT
                and _adequate(second_absent)
                and second_absent.presence_state == VariantPresenceState.ABSENT
                and _adequate(second_present)
                and second_present.presence_state == VariantPresenceState.PRESENT
            ):
                return sorted([first_present.observation_id, first_absent.observation_id, second_absent.observation_id, second_present.observation_id])
    return []


def _observation_index(observations: list[FamilyVariantObservation]) -> dict[tuple[str, str], FamilyVariantObservation]:
    result = {}
    for observation in sorted(observations, key=lambda item: item.observation_id):
        result.setdefault((observation.family_member_id, observation.candidate_variant_id), observation)
    return result


def _adequate(observation: FamilyVariantObservation | None) -> bool:
    return bool(
        observation
        and observation.testing_state == ObservationTestingState.TESTED
        and observation.confirmation_state == ConfirmationState.CONFIRMED
        and observation.presence_state in {VariantPresenceState.PRESENT, VariantPresenceState.ABSENT}
    )


def _missing_observation(code: str, target_id: str, member_id: str, candidate_id: str) -> PedigreeAuditIssue:
    return issue(code, "A required exact supplied member-candidate observation or adequate testing state is missing.", "requirement", member_ids=[member_id], candidate_ids=[candidate_id], record_ids=[target_id])


def _transmission_records(request, relationships, observations) -> list[ParentChildTransmissionRecord]:
    candidate_ids = sorted({candidate_id for target in request.audit_targets for candidate_id in target.candidate_variant_ids})
    records: list[ParentChildTransmissionRecord] = []
    for relationship in relationships:
        for candidate_id in candidate_ids:
            parent = observations.get((relationship.parent_member_id, candidate_id))
            child = observations.get((relationship.child_member_id, candidate_id))
            reason = None
            if parent is None or child is None:
                reason = "required_observation_missing"
            elif parent.testing_state != ObservationTestingState.TESTED or child.testing_state != ObservationTestingState.TESTED:
                reason = "testing_state_not_evaluable"
            elif parent.confirmation_state != ConfirmationState.CONFIRMED or child.confirmation_state != ConfirmationState.CONFIRMED:
                reason = "confirmation_state_not_evaluable"
            elif parent.presence_state not in {VariantPresenceState.PRESENT, VariantPresenceState.ABSENT} or child.presence_state not in {VariantPresenceState.PRESENT, VariantPresenceState.ABSENT}:
                reason = "presence_state_not_evaluable"
            records.append(
                ParentChildTransmissionRecord(
                    transmission_id=stable_identifier(
                        "parent-child-transmission",
                        relationship.relationship_id,
                        relationship.parent_member_id,
                        relationship.child_member_id,
                        candidate_id,
                        parent.presence_state.value if parent else "",
                        child.presence_state.value if child else "",
                        reason or "evaluable",
                    ),
                    relationship_id=relationship.relationship_id,
                    parent_member_id=relationship.parent_member_id,
                    child_member_id=relationship.child_member_id,
                    candidate_variant_id=candidate_id,
                    evaluable=reason is None,
                    parent_presence_state=parent.presence_state.value if parent else None,
                    child_presence_state=child.presence_state.value if child else None,
                    non_evaluable_reason_code=reason,
                )
            )
    return sorted(records, key=lambda item: (item.relationship_id, item.candidate_variant_id, item.transmission_id))


def _transmission_summary(relationships, records) -> AvailableParentChildTransmissionSummary:
    reasons = Counter(item.non_evaluable_reason_code for item in records if item.non_evaluable_reason_code)
    evaluable = sum(1 for item in records if item.evaluable)
    return AvailableParentChildTransmissionSummary(
        supplied_biological_parent_relationship_count=len(relationships),
        candidate_parent_child_transmission_count=len(records),
        evaluable_transmission_count=evaluable,
        non_evaluable_transmission_count=len(records) - evaluable,
        non_evaluable_reason_counts={key: reasons[key] for key in sorted(reasons)},
    )


def _converted_intake_issues(items: Iterable[ClinicalIntakeIssue], severity: str) -> list[PedigreeAuditIssue]:
    return [issue(item.code, item.message, severity, record_ids=[item.record_id] if item.record_id else (), supplied_facts={"field": item.field} if item.field else {}) for item in items]


def _policy_blocks(items: Iterable[ClinicalPolicyBlock]) -> list[PedigreeAuditPolicyBlock]:
    explanation = "The requested action is outside the bounded clinical genetics research-curation scope."
    blocks = [
        PedigreeAuditPolicyBlock(
            issue_id=stable_identifier("pedigree-policy-block", item.code, item.category, explanation),
            code=item.code,
            category=item.category,
            explanation=explanation,
        )
        for item in items
    ]
    return sorted({item.issue_id: item for item in blocks}.values(), key=lambda item: (item.code, item.issue_id))
