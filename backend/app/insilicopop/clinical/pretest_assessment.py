from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any, Iterable

from app.insilicopop.clinical.models import ClinicalCaseIntake, ClinicalIntakeIssue, ClinicalPolicyBlock
from app.insilicopop.clinical.pretest_models import (
    AccessReviewStatus,
    CheckpointStatus,
    CheckpointType,
    ClinicalHistoryReviewStatus,
    InformationStatus,
    MissingInformationCategory,
    MissingInformationPlanItem,
    MissingInformationStatus,
    PedigreeReviewStatus,
    PreTestAssessmentResult,
    PreTestLinkageIssue,
    PreTestWorkflowOutcome,
    ReadinessImpact,
    RecordAvailability,
    ReferralSource,
    ReferralUrgencyContext,
    SampleAvailabilityReview,
)


_VALIDATION_WARNING_MAPPINGS = {
    "machine_translation_requires_expert_review": (
        MissingInformationCategory.CLINICAL_HISTORY,
        ReadinessImpact.HUMAN_REVIEW_REQUIRED,
        "Review the machine-translated clinical wording against the supplied source wording.",
    ),
    "reported_relationship_context_requires_expert_review": (
        MissingInformationCategory.PEDIGREE,
        ReadinessImpact.HUMAN_REVIEW_REQUIRED,
        "Review the supplied relationship or consanguinity context without inferring a family relationship.",
    ),
}


def map_readiness_relevant_upstream_findings(
    case_id: str,
    *,
    validation_warnings: Iterable[ClinicalIntakeIssue] = (),
    validation_missing_information: Iterable[ClinicalIntakeIssue] = (),
    phenotype_curation: Any | None = None,
    pedigree_audit: Any | None = None,
) -> list[MissingInformationPlanItem]:
    """Map an explicit allowlist of upstream findings into bounded readiness items."""
    mapped: list[MissingInformationPlanItem] = []

    def add(code, category, impact, needed, why, linked_ids=()):
        links = sorted(set(str(item) for item in linked_ids if item))
        mapped.append(
            MissingInformationPlanItem(
                request_id=_stable_id("PREMAP", case_id, code, *links),
                category=category,
                code=code,
                information_needed=needed,
                why_needed=why,
                source="system_identified",
                linked_record_ids=links,
                readiness_impact=impact,
            )
        )

    for issue in validation_warnings:
        rule = _VALIDATION_WARNING_MAPPINGS.get(issue.code)
        if rule:
            category, impact, needed = rule
            add(
                f"upstream_{issue.code}",
                category,
                impact,
                needed,
                issue.message,
                [issue.record_id],
            )

    # Only core phenotype absence is readiness-relevant. Variant/build and other
    # post-test context is intentionally excluded from this allowlist.
    for issue in validation_missing_information:
        if issue.code == "phenotypes_not_supplied":
            add(
                "upstream_phenotypes_not_supplied",
                MissingInformationCategory.PHENOTYPE,
                ReadinessImpact.BLOCKING,
                "Supply or explicitly review the core phenotype information for this referral.",
                issue.message,
                [issue.record_id],
            )

    if phenotype_curation is not None:
        for contradiction in getattr(phenotype_curation, "contradictions", ()):
            add(
                "upstream_phenotype_contradiction",
                MissingInformationCategory.PHENOTYPE,
                ReadinessImpact.HUMAN_REVIEW_REQUIRED,
                "Resolve the conflicting supplied phenotype states.",
                "The deterministic phenotype curation found incompatible supplied states and did not resolve them.",
                [getattr(contradiction, "contradiction_id", None), *getattr(contradiction, "involved_record_ids", ())],
            )

    if pedigree_audit is not None:
        for collection_name, code, needed in (
            ("relationship_issues", "upstream_pedigree_relationship_issue", "Review the supplied pedigree relationship conflict."),
            ("mendelian_inconsistencies", "upstream_pedigree_inconsistency", "Review the supplied-record inheritance inconsistency."),
        ):
            for issue in getattr(pedigree_audit, collection_name, ()):
                add(
                    code,
                    MissingInformationCategory.PEDIGREE,
                    ReadinessImpact.HUMAN_REVIEW_REQUIRED,
                    needed,
                    getattr(issue, "explanation", "The pedigree audit requires human review."),
                    [getattr(issue, "issue_id", None), *getattr(issue, "involved_record_ids", ())],
                )
        for audit in getattr(pedigree_audit, "inheritance_audits", ()):
            if getattr(getattr(audit, "status", None), "value", None) == "inconsistent":
                add(
                    "upstream_inheritance_audit_inconsistent",
                    MissingInformationCategory.PEDIGREE,
                    ReadinessImpact.HUMAN_REVIEW_REQUIRED,
                    "Review the inconsistent bounded inheritance audit.",
                    getattr(audit, "bounded_explanation", "The supplied inheritance records are inconsistent."),
                    [getattr(audit, "audit_id", None), getattr(audit, "audit_target_id", None)],
                )

    return sorted({item.request_id: item for item in mapped}.values(), key=lambda item: item.request_id)


def build_pretest_assessment(
    case: ClinicalCaseIntake,
    *,
    validation_errors: list[ClinicalIntakeIssue],
    policy_blocks: list[ClinicalPolicyBlock],
    validation_warnings: list[ClinicalIntakeIssue] | None = None,
    validation_missing_information: list[ClinicalIntakeIssue] | None = None,
    phenotype_curation: Any | None = None,
    pedigree_audit: Any | None = None,
) -> PreTestAssessmentResult | None:
    request = case.pre_test_assessment
    if request is None:
        return None

    linkage_issues: list[PreTestLinkageIssue] = []
    effective_warnings = list(validation_warnings or [])
    language = case.global_intake_context.language_context if case.global_intake_context else None
    if language and getattr(language.translation_review_state, "value", None) == "human_reviewed":
        effective_warnings = [item for item in effective_warnings if item.code != "machine_translation_requires_expert_review"]
    system_missing = map_readiness_relevant_upstream_findings(
        case.pseudonymous_case_id,
        validation_warnings=effective_warnings,
        validation_missing_information=validation_missing_information or [],
        phenotype_curation=phenotype_curation,
        pedigree_audit=pedigree_audit,
    )

    def add_missing(code, category, information_needed, why_needed, linked_record_ids=None, impact=ReadinessImpact.BLOCKING):
        links = sorted(set(linked_record_ids or []))
        system_missing.append(
            MissingInformationPlanItem(
                request_id=_stable_id("PREMISS", case.pseudonymous_case_id, code, *links),
                category=category,
                code=code,
                information_needed=information_needed,
                why_needed=why_needed,
                source="system_identified",
                linked_record_ids=links,
                readiness_impact=impact,
            )
        )

    referral = request.referral_packet
    if referral is None:
        add_missing("referral_packet_not_supplied", MissingInformationCategory.REFERRAL, "Supply the bounded referral source, reason, and supplied urgency context.", "The pre-test assessment must retain why and how the case entered clinical-genetics review.")
    else:
        if referral.source == ReferralSource.UNKNOWN:
            add_missing("referral_source_unknown", MissingInformationCategory.REFERRAL, "Clarify the supplied referral source.", "Referral provenance is required before readiness can be reviewed.", [referral.referral_id])
        if not referral.reason_exact:
            add_missing("referral_reason_not_supplied", MissingInformationCategory.REFERRAL, "Supply the redacted referral reason.", "The assessment cannot organize the clinical question without a supplied referral reason.", [referral.referral_id])
        if referral.urgency_context in {ReferralUrgencyContext.UNKNOWN, ReferralUrgencyContext.NOT_ASSESSED}:
            add_missing("referral_urgency_context_not_assessed", MissingInformationCategory.REFERRAL, "Clarify the supplied referral urgency context.", "Urgency is preserved as supplied context only and requires clinician review.", [referral.referral_id], ReadinessImpact.ADVISORY)

    history = request.clinical_history
    known_phenotypes = {item.observation_id for item in case.phenotypes}
    known_members = {item.family_member_id for item in case.pedigree}
    known_sources = {item.source_id for item in case.provenance}
    if history is None:
        add_missing("clinical_genetics_history_not_supplied", MissingInformationCategory.CLINICAL_HISTORY, "Supply a bounded clinical-genetics history with symptoms, onset, and course.", "A pre-test assessment requires supplied clinical context before any test-strategy review.")
    else:
        item_phenotypes = {linked for item in history.items for linked in item.phenotype_links}
        item_pedigree = {linked for item in history.items for linked in item.pedigree_person_links}
        if not history.summary_exact and not history.items and not history.phenotype_observation_ids:
            add_missing("symptoms_and_history_not_supplied", MissingInformationCategory.CLINICAL_HISTORY, "Supply a redacted history summary, structured history item, or linked phenotype observation.", "Symptoms must be linked to the assessment rather than inferred.", [history.history_id])
        if not history.onset_exact and not any(item.onset_exact for item in history.items):
            add_missing("onset_not_supplied", MissingInformationCategory.CLINICAL_HISTORY, "Clarify symptom onset or explicitly record that onset is unknown.", "Onset is a core part of the supplied clinical course.", [history.history_id])
        if history.disease_course.value in {"unknown", "not_assessed"} and not any(item.progression_exact for item in history.items):
            add_missing("disease_course_not_assessed", MissingInformationCategory.CLINICAL_HISTORY, "Review the supplied disease course.", "The clinical course should be explicitly reviewed.", [history.history_id])
        for field_name, status in (("birth_history", history.birth_history_status), ("development_history", history.development_history_status)):
            if status == InformationStatus.NOT_ASSESSED:
                add_missing(f"{field_name}_not_assessed", MissingInformationCategory.CLINICAL_HISTORY, f"Review and explicitly record {field_name.replace('_', ' ')} status.", "Absent data is not interpreted as a normal history.", [history.history_id], ReadinessImpact.ADVISORY)
        if not history.phenotype_observation_ids and not item_phenotypes:
            add_missing("phenotype_linkage_not_supplied", MissingInformationCategory.PHENOTYPE, "Link the history to reviewed phenotype/HPO observations.", "The assessment must connect to structured phenotype evidence without generating new claims.", [history.history_id])
        if history.review_status != CheckpointStatus.CONFIRMED:
            add_missing("clinical_history_review_not_confirmed", MissingInformationCategory.HUMAN_REVIEW, "Complete clinician review of the supplied clinical-genetics history.", "Unreviewed or revision-needed history requires clinician judgment.", [history.history_id], ReadinessImpact.HUMAN_REVIEW_REQUIRED)
        for item in history.items:
            if item.review_status != ClinicalHistoryReviewStatus.REVIEWED:
                add_missing("clinical_history_item_requires_review", MissingInformationCategory.HUMAN_REVIEW, "Review the supplied history claim without changing its source or assertion type.", f"History item {item.item_id} is {item.review_status.value}.", [history.history_id, item.item_id], ReadinessImpact.HUMAN_REVIEW_REQUIRED)
        for linked_id in sorted((set(history.phenotype_observation_ids) | item_phenotypes) - known_phenotypes):
            linkage_issues.append(_linkage_issue(case.pseudonymous_case_id, "unknown_phenotype_link", "clinical_history.phenotype_links", history.history_id, linked_id, "Linked phenotype observation was not found in the supplied case."))
        for linked_id in sorted((set(history.pedigree_member_ids) | item_pedigree) - known_members):
            linkage_issues.append(_linkage_issue(case.pseudonymous_case_id, "unknown_pedigree_link", "clinical_history.pedigree_person_links", history.history_id, linked_id, "Linked pedigree member was not found in the supplied case."))

    pedigree_relevant = _pedigree_is_relevant(case, request)
    supplied_pedigree_links = set(history.pedigree_member_ids) | {link for item in history.items for link in item.pedigree_person_links} if history else set()
    if request.pedigree_review_status == PedigreeReviewStatus.NOT_RELEVANT and pedigree_relevant:
        add_missing("pedigree_relevance_conflict", MissingInformationCategory.PEDIGREE, "Review the conflict between supplied familial context and the not-relevant declaration.", "Pedigree relevance cannot be removed by inference.", impact=ReadinessImpact.HUMAN_REVIEW_REQUIRED)
    elif pedigree_relevant and not supplied_pedigree_links:
        supplied_family_records_exist = bool(case.pedigree or request.known_family_reports)
        impact = ReadinessImpact.BLOCKING if supplied_family_records_exist or request.pedigree_review_status not in {PedigreeReviewStatus.UNAVAILABLE, PedigreeReviewStatus.DEFERRED} else ReadinessImpact.ADVISORY
        add_missing("pedigree_linkage_not_supplied", MissingInformationCategory.PEDIGREE, "Link relevant supplied pedigree members or document the reviewed limitation.", "The referral contains structured familial context that requires relationship-safe linkage.", impact=impact)
    elif not pedigree_relevant:
        if request.pedigree_review_status == PedigreeReviewStatus.UNKNOWN:
            add_missing("pedigree_relevance_not_reviewed", MissingInformationCategory.PEDIGREE, "Record whether pedigree review is relevant to this referral.", "The system does not infer that pedigree is not relevant.", impact=ReadinessImpact.HUMAN_REVIEW_REQUIRED)
        elif request.pedigree_review_status in {PedigreeReviewStatus.UNAVAILABLE, PedigreeReviewStatus.NOT_COLLECTED, PedigreeReviewStatus.DEFERRED}:
            add_missing("pedigree_context_limited", MissingInformationCategory.PEDIGREE, "Retain the reviewed limitation on pedigree availability.", "No familial dependency was supplied, so this limitation is non-blocking.", impact=ReadinessImpact.ADVISORY)

    _review_collection_status(request.previous_investigations_review_status, request.previous_investigations, "previous_investigations", MissingInformationCategory.PREVIOUS_INVESTIGATION, add_missing)
    for investigation in request.previous_investigations:
        if investigation.report_availability in {RecordAvailability.PARTIAL, RecordAvailability.REQUESTED, RecordAvailability.UNKNOWN, RecordAvailability.NOT_ASSESSED}:
            add_missing("previous_investigation_report_incomplete", MissingInformationCategory.PREVIOUS_INVESTIGATION, "Retrieve or review the available previous-investigation report and exact result context.", "Incomplete prior-investigation evidence can alter the information gathered before strategy review.", [investigation.investigation_id])

    _review_collection_status(request.known_family_reports_review_status, request.known_family_reports, "known_family_reports", MissingInformationCategory.FAMILY_REPORT, add_missing)
    for report in request.known_family_reports:
        _add_family_report_item(report, add_missing)
        if report.family_member_id not in known_members:
            linkage_issues.append(_linkage_issue(case.pseudonymous_case_id, "unknown_family_report_member", "known_family_reports.family_member_id", report.family_report_id, report.family_member_id, "Family report refers to a pedigree member not found in the supplied case."))

    for record_type, record_id, source_ids in _record_source_links(request):
        for source_id in sorted(set(source_ids) - known_sources):
            linkage_issues.append(_linkage_issue(case.pseudonymous_case_id, "unknown_provenance_source", f"{record_type}.provenance_source_ids", record_id, source_id, "Referenced provenance source was not found in case-level provenance."))

    global_context = case.global_intake_context
    sample_context_present = bool(global_context and global_context.family_sample_contexts)
    global_access = global_context.testing_access_context if global_context else None
    access_context_present = bool(global_access and (global_access.constraints or global_access.other_constraint_exact or global_access.prior_authorization_status_exact or global_access.estimated_turnaround_time_exact))
    context = request.context_review
    if context.sample_availability == SampleAvailabilityReview.NOT_ASSESSED and not sample_context_present:
        add_missing("sample_availability_not_assessed", MissingInformationCategory.SAMPLE_AVAILABILITY, "Review proband and relevant family-sample availability.", "Sample availability affects feasibility but does not authorize or select a test.", impact=ReadinessImpact.ADVISORY)
    if context.access_review_status == AccessReviewStatus.NOT_ASSESSED and not access_context_present:
        add_missing("access_and_affordability_not_assessed", MissingInformationCategory.ACCESS_AND_AFFORDABILITY, "Review supplied access and affordability constraints.", "This is useful feasibility context and does not infer ability to pay.", impact=ReadinessImpact.ADVISORY)

    supplied_missing = [MissingInformationPlanItem(request_id=item.request_id, category=item.category, code="user_supplied_missing_information", information_needed=item.information_needed_exact, why_needed=item.why_needed_exact or "User-supplied missing-information request; rationale not supplied.", source="user_supplied", linked_record_ids=item.linked_record_ids, status=item.status, readiness_impact=item.readiness_impact) for item in request.supplied_missing_information_requests]
    missing_plan = sorted({item.request_id: item for item in [*system_missing, *supplied_missing]}.values(), key=lambda item: item.request_id)
    blocking = _items_with_impact(missing_plan, ReadinessImpact.BLOCKING)
    advisory = _items_with_impact(missing_plan, ReadinessImpact.ADVISORY)
    human = _items_with_impact(missing_plan, ReadinessImpact.HUMAN_REVIEW_REQUIRED)
    informational = _items_with_impact(missing_plan, ReadinessImpact.INFORMATIONAL)
    open_count = sum(item.status == MissingInformationStatus.OPEN for item in missing_plan)
    open_blocking = sum(item.status == MissingInformationStatus.OPEN for item in blocking)
    open_human = sum(item.status == MissingInformationStatus.OPEN for item in human)

    checkpoint_counts = Counter(item.status.value for item in request.clinician_checkpoints)
    readiness_confirmed = any(item.checkpoint_type == CheckpointType.PRE_TEST_ASSESSMENT_REVIEW and item.status == CheckpointStatus.CONFIRMED for item in request.clinician_checkpoints)
    outcome, rationale = _assessment_outcome(requested=request.testing_status, has_blocking_input=bool(validation_errors or policy_blocks), open_blocking_count=open_blocking, open_human_count=open_human, linkage_issue_count=len(linkage_issues), readiness_confirmed=readiness_confirmed)
    return PreTestAssessmentResult(
        pseudonymous_case_id=case.pseudonymous_case_id,
        referral_packet=referral,
        clinical_history=history,
        previous_investigation_timeline=sorted(request.previous_investigations, key=lambda item: (item.timeline_order is None, item.timeline_order if item.timeline_order is not None else 0, item.occurred_on_or_period_exact or "", item.investigation_id)),
        known_family_reports=sorted(request.known_family_reports, key=lambda item: item.family_report_id),
        context_review=context,
        testing_status_as_supplied=request.testing_status,
        assessment_outcome=outcome,
        outcome_rationale_codes=rationale,
        linkage_issues=sorted(linkage_issues, key=lambda item: item.issue_id),
        missing_information_plan=missing_plan,
        blocking_items=blocking,
        advisory_items=advisory,
        human_review_items=human,
        informational_items=informational,
        open_missing_information_count=open_count,
        open_blocking_information_count=open_blocking,
        open_human_review_count=open_human,
        clinician_checkpoint_status_counts={key: checkpoint_counts[key] for key in sorted(checkpoint_counts)},
        clinician_decisions=sorted(request.clinician_checkpoints, key=lambda item: item.checkpoint_id),
        ready_for_test_strategy_review=outcome == PreTestWorkflowOutcome.READY_FOR_TEST_STRATEGY_REVIEW,
    )


def _pedigree_is_relevant(case, request) -> bool:
    if request.pedigree_relevant_to_referral is True:
        return True
    if case.pedigree or request.known_family_reports:
        return True
    if any(getattr(item.hypothesis_type, "value", item.hypothesis_type) == "inheritance" for item in case.hypotheses):
        return True
    profile = case.global_intake_context.locale_profile if case.global_intake_context else None
    if profile and getattr(profile.consanguinity_status, "value", None) == "reported":
        return True
    history = request.clinical_history
    return bool(history and (history.pedigree_member_ids or any(item.pedigree_person_links for item in history.items)))


def _add_family_report_item(report, add_missing) -> None:
    links = [report.family_report_id, report.family_member_id]
    essential_impact = ReadinessImpact.BLOCKING if report.essential_to_referral else ReadinessImpact.ADVISORY
    if report.report_availability == RecordAvailability.AVAILABLE:
        if not report.supplied_summary_exact and not report.provenance_source_ids:
            add_missing("known_family_report_available_content_not_represented", MissingInformationCategory.FAMILY_REPORT, "Represent the available family report content or its exact provenance link.", "Availability alone does not represent the report content.", links, ReadinessImpact.HUMAN_REVIEW_REQUIRED)
    elif report.report_availability == RecordAvailability.PARTIAL:
        add_missing("known_family_report_partial", MissingInformationCategory.FAMILY_REPORT, "Review the missing sections of the partial family report.", "Only the supplied portions may be used.", links, ReadinessImpact.HUMAN_REVIEW_REQUIRED if report.essential_to_referral else ReadinessImpact.ADVISORY)
    elif report.report_availability == RecordAvailability.REQUESTED:
        add_missing("known_family_report_requested", MissingInformationCategory.FAMILY_REPORT, "Track the requested family report without reconstructing its contents.", "The report has been requested but is not supplied.", links, essential_impact)
    elif report.report_availability == RecordAvailability.UNAVAILABLE:
        add_missing("known_family_report_unavailable", MissingInformationCategory.FAMILY_REPORT, "Retain that the family report is unavailable.", "Unavailable report content is a visible limitation and is blocking only when explicitly essential.", links, essential_impact)
    elif report.report_availability in {RecordAvailability.UNKNOWN, RecordAvailability.NOT_ASSESSED}:
        add_missing("known_family_report_availability_not_reviewed", MissingInformationCategory.FAMILY_REPORT, "Clarify the family report availability.", "Unknown or unassessed availability requires explicit review.", links, ReadinessImpact.HUMAN_REVIEW_REQUIRED)


def _review_collection_status(status, records, field_prefix, category, add_missing) -> None:
    if status == InformationStatus.NOT_ASSESSED:
        add_missing(f"{field_prefix}_not_assessed", category, f"Review {field_prefix.replace('_', ' ')} and record supplied, none reported, or unknown.", "An empty list must not be interpreted as a negative history without an explicit review state.", impact=ReadinessImpact.ADVISORY)
    elif status == InformationStatus.SUPPLIED and not records:
        add_missing(f"{field_prefix}_declared_but_records_missing", category, f"Add the declared {field_prefix.replace('_', ' ')} records.", "The supplied review state and structured record list are inconsistent.")
    elif status == InformationStatus.NONE_REPORTED and records:
        add_missing(f"{field_prefix}_records_conflict_with_none_reported", category, f"Resolve the conflict between the none-reported status and supplied {field_prefix.replace('_', ' ')} records.", "The structured review status and supplied records must agree.", impact=ReadinessImpact.HUMAN_REVIEW_REQUIRED)


def _items_with_impact(items, impact):
    return [item for item in items if item.readiness_impact == impact]


def _record_source_links(request):
    if request.referral_packet:
        yield "referral_packet", request.referral_packet.referral_id, request.referral_packet.provenance_source_ids
    if request.clinical_history:
        yield "clinical_history", request.clinical_history.history_id, request.clinical_history.provenance_source_ids
        for item in request.clinical_history.items:
            yield "clinical_history.items", item.item_id, item.provenance_source_ids
    for item in request.previous_investigations:
        yield "previous_investigations", item.investigation_id, item.provenance_source_ids
    for item in request.known_family_reports:
        yield "known_family_reports", item.family_report_id, item.provenance_source_ids
    for item in request.clinician_checkpoints:
        yield "clinician_checkpoints", item.checkpoint_id, item.provenance_source_ids


def _assessment_outcome(*, requested, has_blocking_input, open_blocking_count, open_human_count, linkage_issue_count, readiness_confirmed):
    if has_blocking_input:
        return PreTestWorkflowOutcome.AWAITING_HUMAN_REVIEW, ["intake_validation_or_policy_block"]
    if requested == PreTestWorkflowOutcome.NO_TEST_YET:
        return PreTestWorkflowOutcome.NO_TEST_YET, ["no_test_yet_status_supplied"]
    if open_blocking_count or linkage_issue_count:
        codes = []
        if open_blocking_count:
            codes.append("open_blocking_information")
        if linkage_issue_count:
            codes.append("unresolved_record_linkage")
        return PreTestWorkflowOutcome.MORE_INFORMATION_REQUIRED, codes
    if open_human_count:
        return PreTestWorkflowOutcome.AWAITING_HUMAN_REVIEW, ["open_human_review_items"]
    if requested == PreTestWorkflowOutcome.MORE_INFORMATION_REQUIRED:
        return PreTestWorkflowOutcome.MORE_INFORMATION_REQUIRED, ["more_information_required_status_supplied"]
    if requested == PreTestWorkflowOutcome.READY_FOR_TEST_STRATEGY_REVIEW and readiness_confirmed:
        return PreTestWorkflowOutcome.READY_FOR_TEST_STRATEGY_REVIEW, ["readiness_status_supplied", "clinician_checkpoint_confirmed"]
    if requested == PreTestWorkflowOutcome.READY_FOR_TEST_STRATEGY_REVIEW:
        return PreTestWorkflowOutcome.AWAITING_HUMAN_REVIEW, ["pre_test_assessment_checkpoint_not_confirmed"]
    return PreTestWorkflowOutcome.AWAITING_HUMAN_REVIEW, ["awaiting_human_review_status_supplied"]


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _linkage_issue(case_id: str, code: str, field: str, record_id: str, linked_id: str, message: str) -> PreTestLinkageIssue:
    return PreTestLinkageIssue(issue_id=_stable_id("PRELINK", case_id, code, record_id, linked_id), code=code, field=field, record_id=record_id, linked_record_id=linked_id, message=message)
