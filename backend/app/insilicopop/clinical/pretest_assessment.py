from __future__ import annotations

import hashlib
from collections import Counter

from app.insilicopop.clinical.models import ClinicalCaseIntake, ClinicalIntakeIssue, ClinicalPolicyBlock
from app.insilicopop.clinical.pretest_models import (
    AccessReviewStatus,
    CheckpointStatus,
    CheckpointType,
    InformationStatus,
    MissingInformationCategory,
    MissingInformationPlanItem,
    MissingInformationStatus,
    PreTestAssessmentResult,
    PreTestLinkageIssue,
    PreTestWorkflowOutcome,
    ReferralSource,
    ReferralUrgencyContext,
    SampleAvailabilityReview,
)


def build_pretest_assessment(
    case: ClinicalCaseIntake,
    *,
    validation_errors: list[ClinicalIntakeIssue],
    policy_blocks: list[ClinicalPolicyBlock],
) -> PreTestAssessmentResult | None:
    request = case.pre_test_assessment
    if request is None:
        return None

    linkage_issues: list[PreTestLinkageIssue] = []
    system_missing: list[MissingInformationPlanItem] = []

    def add_missing(
        code: str,
        category: MissingInformationCategory,
        information_needed: str,
        why_needed: str,
        linked_record_ids: list[str] | None = None,
    ) -> None:
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
            )
        )

    referral = request.referral_packet
    if referral is None:
        add_missing(
            "referral_packet_not_supplied",
            MissingInformationCategory.REFERRAL,
            "Supply the bounded referral source, reason, and supplied urgency context.",
            "The pre-test assessment must retain why and how the case entered clinical-genetics review.",
        )
    else:
        if referral.source == ReferralSource.UNKNOWN:
            add_missing(
                "referral_source_unknown",
                MissingInformationCategory.REFERRAL,
                "Clarify the supplied referral source.",
                "Referral provenance is required before readiness can be reviewed.",
                [referral.referral_id],
            )
        if not referral.reason_exact:
            add_missing(
                "referral_reason_not_supplied",
                MissingInformationCategory.REFERRAL,
                "Supply the redacted referral reason.",
                "The assessment cannot organize the clinical question without a supplied referral reason.",
                [referral.referral_id],
            )
        if referral.urgency_context in {ReferralUrgencyContext.UNKNOWN, ReferralUrgencyContext.NOT_ASSESSED}:
            add_missing(
                "referral_urgency_context_not_assessed",
                MissingInformationCategory.REFERRAL,
                "Clarify the supplied referral urgency context.",
                "Urgency is preserved as supplied context only and requires clinician review.",
                [referral.referral_id],
            )

    history = request.clinical_history
    known_phenotypes = {item.observation_id for item in case.phenotypes}
    known_members = {item.family_member_id for item in case.pedigree}
    known_sources = {item.source_id for item in case.provenance}
    if history is None:
        add_missing(
            "clinical_genetics_history_not_supplied",
            MissingInformationCategory.CLINICAL_HISTORY,
            "Supply a bounded clinical-genetics history with symptoms, onset, course, birth, and development review statuses.",
            "A pre-test assessment requires supplied clinical context before any test-strategy review.",
        )
    else:
        if not history.summary_exact and not history.phenotype_observation_ids:
            add_missing(
                "symptoms_and_history_not_supplied",
                MissingInformationCategory.CLINICAL_HISTORY,
                "Supply a redacted history summary or link structured phenotype observations.",
                "Symptoms must be linked to the assessment rather than inferred.",
                [history.history_id],
            )
        if not history.onset_exact:
            add_missing(
                "onset_not_supplied",
                MissingInformationCategory.CLINICAL_HISTORY,
                "Clarify symptom onset or explicitly record that onset is unknown.",
                "Onset is a core part of the supplied clinical course.",
                [history.history_id],
            )
        if history.disease_course.value in {"unknown", "not_assessed"}:
            add_missing(
                "disease_course_not_assessed",
                MissingInformationCategory.CLINICAL_HISTORY,
                "Review the supplied disease course.",
                "Static, progressive, episodic, variable, resolved, or unknown course should be explicitly reviewed.",
                [history.history_id],
            )
        for field_name, status in (
            ("birth_history", history.birth_history_status),
            ("development_history", history.development_history_status),
        ):
            if status == InformationStatus.NOT_ASSESSED:
                add_missing(
                    f"{field_name}_not_assessed",
                    MissingInformationCategory.CLINICAL_HISTORY,
                    f"Review and explicitly record {field_name.replace('_', ' ')} status.",
                    "An explicit supplied, none-reported, or unknown state avoids treating absent data as normal.",
                    [history.history_id],
                )
        if not history.phenotype_observation_ids:
            add_missing(
                "phenotype_linkage_not_supplied",
                MissingInformationCategory.PHENOTYPE,
                "Link the history to reviewed phenotype/HPO observations.",
                "The pre-test assessment must connect to structured phenotype evidence without generating new phenotype claims.",
                [history.history_id],
            )
        if not history.pedigree_member_ids:
            add_missing(
                "pedigree_linkage_not_supplied",
                MissingInformationCategory.PEDIGREE,
                "Link relevant supplied pedigree members or document why pedigree information is unavailable.",
                "Family-history review must be explicit and relationship-safe.",
                [history.history_id],
            )
        if history.review_status != CheckpointStatus.CONFIRMED:
            add_missing(
                "clinical_history_review_not_confirmed",
                MissingInformationCategory.HUMAN_REVIEW,
                "Complete clinician review of the supplied clinical-genetics history.",
                "Unreviewed or revision-needed history cannot support readiness for test-strategy review.",
                [history.history_id],
            )
        for linked_id in sorted(set(history.phenotype_observation_ids) - known_phenotypes):
            linkage_issues.append(_linkage_issue(case.pseudonymous_case_id, "unknown_phenotype_link", "clinical_history.phenotype_observation_ids", history.history_id, linked_id, "Linked phenotype observation was not found in the supplied case."))
        for linked_id in sorted(set(history.pedigree_member_ids) - known_members):
            linkage_issues.append(_linkage_issue(case.pseudonymous_case_id, "unknown_pedigree_link", "clinical_history.pedigree_member_ids", history.history_id, linked_id, "Linked pedigree member was not found in the supplied case."))

    _review_collection_status(
        request.previous_investigations_review_status,
        request.previous_investigations,
        "previous_investigations",
        MissingInformationCategory.PREVIOUS_INVESTIGATION,
        add_missing,
    )

    for investigation in request.previous_investigations:
        if investigation.report_availability.value in {"partial", "requested", "unknown", "not_assessed"}:
            add_missing(
                "previous_investigation_report_incomplete",
                MissingInformationCategory.PREVIOUS_INVESTIGATION,
                "Retrieve or review the available previous-investigation report and exact result context.",
                "Incomplete prior-investigation evidence can alter what information should be gathered before strategy review.",
                [investigation.investigation_id],
            )
    for family_report in request.known_family_reports:
        if family_report.report_availability.value in {"partial", "requested", "unknown", "not_assessed"}:
            add_missing(
                "known_family_report_incomplete",
                MissingInformationCategory.FAMILY_REPORT,
                "Retrieve or review the known family report.",
                "A supplied relative report should be reviewed directly rather than reconstructed from memory.",
                [family_report.family_report_id, family_report.family_member_id],
            )
    _review_collection_status(
        request.known_family_reports_review_status,
        request.known_family_reports,
        "known_family_reports",
        MissingInformationCategory.FAMILY_REPORT,
        add_missing,
    )

    for report in request.known_family_reports:
        if report.family_member_id not in known_members:
            linkage_issues.append(_linkage_issue(case.pseudonymous_case_id, "unknown_family_report_member", "known_family_reports.family_member_id", report.family_report_id, report.family_member_id, "Family report refers to a pedigree member not found in the supplied case."))

    for record_type, record_id, source_ids in _record_source_links(request):
        for source_id in sorted(set(source_ids) - known_sources):
            linkage_issues.append(_linkage_issue(case.pseudonymous_case_id, "unknown_provenance_source", f"{record_type}.provenance_source_ids", record_id, source_id, "Referenced provenance source was not found in case-level provenance."))

    global_context = case.global_intake_context
    sample_context_present = bool(global_context and global_context.family_sample_contexts)
    global_access = global_context.testing_access_context if global_context else None
    access_context_present = bool(
        global_access
        and (
            global_access.constraints
            or global_access.other_constraint_exact
            or global_access.prior_authorization_status_exact
            or global_access.estimated_turnaround_time_exact
        )
    )
    context = request.context_review
    if context.sample_availability == SampleAvailabilityReview.NOT_ASSESSED and not sample_context_present:
        add_missing(
            "sample_availability_not_assessed",
            MissingInformationCategory.SAMPLE_AVAILABILITY,
            "Review proband and relevant family-sample availability.",
            "Sample availability affects feasibility but does not authorize or select a test.",
        )
    if context.access_review_status == AccessReviewStatus.NOT_ASSESSED and not access_context_present:
        add_missing(
            "access_and_affordability_not_assessed",
            MissingInformationCategory.ACCESS_AND_AFFORDABILITY,
            "Review supplied access and affordability constraints.",
            "The later test-strategy review must be cost- and access-aware without inferring ability to pay.",
        )

    supplied_missing = [
        MissingInformationPlanItem(
            request_id=item.request_id,
            category=item.category,
            code="user_supplied_missing_information",
            information_needed=item.information_needed_exact,
            why_needed=item.why_needed_exact or "User-supplied missing-information request; rationale not supplied.",
            source="user_supplied",
            linked_record_ids=sorted(set(item.linked_record_ids)),
            status=item.status,
        )
        for item in request.supplied_missing_information_requests
    ]
    missing_plan = sorted(system_missing + supplied_missing, key=lambda item: item.request_id)
    open_count = sum(item.status == MissingInformationStatus.OPEN for item in missing_plan)

    checkpoint_counts = Counter(item.status.value for item in request.clinician_checkpoints)
    readiness_confirmed = any(
        item.checkpoint_type == CheckpointType.PRE_TEST_ASSESSMENT_REVIEW
        and item.status == CheckpointStatus.CONFIRMED
        for item in request.clinician_checkpoints
    )
    outcome, rationale = _assessment_outcome(
        requested=request.testing_status,
        has_blocking_input=bool(validation_errors or policy_blocks),
        open_missing_count=open_count,
        linkage_issue_count=len(linkage_issues),
        readiness_confirmed=readiness_confirmed,
    )
    return PreTestAssessmentResult(
        pseudonymous_case_id=case.pseudonymous_case_id,
        referral_packet=referral,
        clinical_history=history,
        previous_investigation_timeline=sorted(
            request.previous_investigations,
            key=lambda item: (
                item.timeline_order is None,
                item.timeline_order if item.timeline_order is not None else 0,
                item.occurred_on_or_period_exact or "",
                item.investigation_id,
            ),
        ),
        known_family_reports=sorted(request.known_family_reports, key=lambda item: item.family_report_id),
        context_review=context,
        testing_status_as_supplied=request.testing_status,
        assessment_outcome=outcome,
        outcome_rationale_codes=rationale,
        linkage_issues=sorted(linkage_issues, key=lambda item: item.issue_id),
        missing_information_plan=missing_plan,
        open_missing_information_count=open_count,
        clinician_checkpoint_status_counts={key: checkpoint_counts[key] for key in sorted(checkpoint_counts)},
        ready_for_test_strategy_review=outcome == PreTestWorkflowOutcome.READY_FOR_TEST_STRATEGY_REVIEW,
    )


def _review_collection_status(status, records, field_prefix, category, add_missing) -> None:
    if status == InformationStatus.NOT_ASSESSED:
        add_missing(
            f"{field_prefix}_not_assessed",
            category,
            f"Review {field_prefix.replace('_', ' ')} and record supplied, none reported, or unknown.",
            "An empty list must not be interpreted as a negative history without an explicit review state.",
        )
    elif status == InformationStatus.SUPPLIED and not records:
        add_missing(
            f"{field_prefix}_declared_but_records_missing",
            category,
            f"Add the declared {field_prefix.replace('_', ' ')} records.",
            "The supplied review state and structured record list are inconsistent.",
        )
    elif status == InformationStatus.NONE_REPORTED and records:
        add_missing(
            f"{field_prefix}_records_conflict_with_none_reported",
            category,
            f"Resolve the conflict between the none-reported status and supplied {field_prefix.replace('_', ' ')} records.",
            "The structured review status and supplied records must agree before strategy review.",
        )


def _record_source_links(request):
    if request.referral_packet:
        yield "referral_packet", request.referral_packet.referral_id, request.referral_packet.provenance_source_ids
    if request.clinical_history:
        yield "clinical_history", request.clinical_history.history_id, request.clinical_history.provenance_source_ids
    for item in request.previous_investigations:
        yield "previous_investigations", item.investigation_id, item.provenance_source_ids
    for item in request.known_family_reports:
        yield "known_family_reports", item.family_report_id, item.provenance_source_ids
    for item in request.clinician_checkpoints:
        yield "clinician_checkpoints", item.checkpoint_id, item.provenance_source_ids


def _assessment_outcome(*, requested, has_blocking_input, open_missing_count, linkage_issue_count, readiness_confirmed):
    if has_blocking_input:
        return PreTestWorkflowOutcome.AWAITING_HUMAN_REVIEW, ["intake_validation_or_policy_block"]
    if requested == PreTestWorkflowOutcome.NO_TEST_YET:
        return PreTestWorkflowOutcome.NO_TEST_YET, ["no_test_yet_status_supplied"]
    if open_missing_count or linkage_issue_count:
        codes = []
        if open_missing_count:
            codes.append("open_missing_information")
        if linkage_issue_count:
            codes.append("unresolved_record_linkage")
        return PreTestWorkflowOutcome.MORE_INFORMATION_REQUIRED, codes
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
    return PreTestLinkageIssue(
        issue_id=_stable_id("PRELINK", case_id, code, record_id, linked_id),
        code=code,
        field=field,
        record_id=record_id,
        linked_record_id=linked_id,
        message=message,
    )
