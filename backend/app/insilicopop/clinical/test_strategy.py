from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from pydantic import TypeAdapter

from app.insilicopop.clinical.models import ClinicalCaseIntake
from app.insilicopop.clinical.pretest_models import (
    MissingInformationCategory,
    PreTestAssessmentResult,
    PreTestWorkflowOutcome,
    RecordAvailability,
    SampleAvailabilityReview,
)
from app.insilicopop.clinical.test_strategy_models import (
    FamilySampleMode,
    StrategyFeasibilityStatus,
    StrategyLinkageIssue,
    StrategyMechanism,
    StrategyRuleReviewItem,
    StrategyRuleReviewState,
    StrategyTriggerFact,
    StrategyWorkspaceStatus,
    SuppliedStrategyContext,
    TestCatalogueEntry,
    TestClass,
    TEST_STRATEGY_CATALOGUE_VERSION,
    TEST_STRATEGY_RULE_SPEC_VERSION,
    TestStrategyOption,
    TestStrategyWorkspaceResult,
)


_COMPARISON_DIMENSIONS = [
    "why_surfaced",
    "explicit_trigger_facts",
    "general_detection_scope",
    "important_blind_spots",
    "proband_sample_requirements",
    "family_sample_requirements",
    "supplied_availability_and_cost_context",
    "prerequisites",
    "reasons_to_defer",
    "after_negative_result",
]

_GENOMIC_TEST_CLASSES = {
    TestClass.KNOWN_FAMILIAL_VARIANT_TESTING,
    TestClass.SINGLE_GENE_TESTING,
    TestClass.DELETION_DUPLICATION_ANALYSIS,
    TestClass.REPEAT_EXPANSION_TESTING,
    TestClass.KARYOTYPE,
    TestClass.CHROMOSOMAL_MICROARRAY,
    TestClass.FOCUSED_MULTIGENE_PANEL,
    TestClass.MITOCHONDRIAL_TESTING,
    TestClass.SINGLETON_WES,
    TestClass.TRIO_WES,
    TestClass.WGS,
}
_READINESS_GATED_TEST_CLASSES = {
    TestClass.NON_GENETIC_INVESTIGATION_FIRST,
    TestClass.BIOCHEMICAL_OR_METABOLIC_INVESTIGATION,
    *_GENOMIC_TEST_CLASSES,
}


@lru_cache(maxsize=1)
def load_test_strategy_catalogue() -> tuple[TestCatalogueEntry, ...]:
    path = Path(__file__).with_name("data") / "test_strategy_catalogue_v0313.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("catalogue_version") != TEST_STRATEGY_CATALOGUE_VERSION:
        raise ValueError("Test-strategy catalogue version does not match the runtime contract.")
    if payload.get("rule_spec_version") != TEST_STRATEGY_RULE_SPEC_VERSION:
        raise ValueError("Test-strategy rule-spec version does not match the runtime contract.")
    entries = TypeAdapter(list[TestCatalogueEntry]).validate_python(payload["entries"])
    if len({item.catalogue_entry_id for item in entries}) != len(entries):
        raise ValueError("Test-strategy catalogue entry identifiers must be unique.")
    if {item.test_class for item in entries} != set(TestClass):
        raise ValueError("Test-strategy catalogue must contain each bounded test class exactly once.")
    return tuple(sorted(entries, key=lambda item: item.catalogue_entry_id))


def build_test_strategy_workspace(
    case: ClinicalCaseIntake,
    *,
    pretest_assessment: PreTestAssessmentResult | None,
    phenotype_curation: Any | None = None,
    pedigree_audit: Any | None = None,
) -> TestStrategyWorkspaceResult | None:
    request = case.test_strategy_workspace
    if request is None:
        return None

    catalogue = load_test_strategy_catalogue()
    entries_by_class = {entry.test_class: entry for entry in catalogue}
    entries_by_mechanism: dict[StrategyMechanism, list[TestCatalogueEntry]] = {}
    for entry in catalogue:
        for mechanism in entry.approved_trigger_mechanisms:
            entries_by_mechanism.setdefault(mechanism, []).append(entry)

    known_ids = _known_record_ids(case, pretest_assessment, phenotype_curation, pedigree_audit)
    known_provenance_ids = {item.source_id for item in case.provenance}
    supplied_context = _supplied_context(case)
    linkage_issues: list[StrategyLinkageIssue] = []
    review_items: list[StrategyRuleReviewItem] = []
    option_inputs: list[tuple[TestCatalogueEntry, list[StrategyTriggerFact], list[str]]] = []
    readiness_outcome = pretest_assessment.assessment_outcome if pretest_assessment else None
    readiness_allows_genomic_options = readiness_outcome == PreTestWorkflowOutcome.READY_FOR_TEST_STRATEGY_REVIEW

    automatic_inputs = _automatic_option_inputs(case, pretest_assessment, entries_by_class)
    option_inputs.extend(automatic_inputs)

    for rule_input in sorted(request.rule_inputs, key=lambda item: item.rule_input_id):
        if rule_input.review_state != StrategyRuleReviewState.CONFIRMED:
            review_items.append(
                _review_item(
                    case.pseudonymous_case_id,
                    "rule_input_not_confirmed",
                    "Only confirmed, explicitly human-reviewed rule inputs may surface a catalogue option.",
                    rule_input.rule_input_id,
                )
            )
            continue
        if rule_input.mechanism == StrategyMechanism.OTHER:
            review_items.append(
                _review_item(
                    case.pseudonymous_case_id,
                    "mechanism_requires_approved_rule",
                    "The supplied mechanism has no approved v0.31.3 rule specification.",
                    rule_input.rule_input_id,
                )
            )
            continue

        facts: list[StrategyTriggerFact] = []
        unresolved = False
        for fact in sorted(rule_input.trigger_facts, key=lambda item: item.fact_id):
            missing_ids = sorted(set(fact.source_record_ids) - known_ids)
            missing_provenance_ids = sorted(set(fact.provenance_source_ids) - known_provenance_ids)
            for record_id in missing_ids:
                unresolved = True
                linkage_issues.append(
                    StrategyLinkageIssue(
                        issue_id=_stable_id(
                            "TSLINK",
                            case.pseudonymous_case_id,
                            rule_input.rule_input_id,
                            fact.fact_id,
                            record_id,
                        ),
                        code="unknown_strategy_fact_record",
                        rule_input_id=rule_input.rule_input_id,
                        fact_id=fact.fact_id,
                        source_record_id=record_id,
                        message="The trigger fact references a record not represented in the supplied case or deterministic upstream artifacts.",
                    )
                )
            for source_id in missing_provenance_ids:
                unresolved = True
                linkage_issues.append(
                    StrategyLinkageIssue(
                        issue_id=_stable_id(
                            "TSLINK",
                            case.pseudonymous_case_id,
                            rule_input.rule_input_id,
                            fact.fact_id,
                            source_id,
                        ),
                        code="unknown_strategy_fact_provenance",
                        rule_input_id=rule_input.rule_input_id,
                        fact_id=fact.fact_id,
                        source_record_id=source_id,
                        message="The trigger fact references provenance not represented in case-level provenance.",
                    )
                )
            facts.append(
                StrategyTriggerFact(
                    fact_id=fact.fact_id,
                    fact_summary_exact=fact.fact_summary_exact,
                    source_path=fact.source_path,
                    source_record_ids=fact.source_record_ids,
                    provenance_source_ids=fact.provenance_source_ids,
                    rule_input_id=rule_input.rule_input_id,
                )
            )
        if unresolved:
            review_items.append(
                _review_item(
                    case.pseudonymous_case_id,
                    "trigger_fact_linkage_requires_review",
                    "Resolve trigger-fact record links before this rule input can surface an option.",
                    rule_input.rule_input_id,
                )
            )
            continue

        matching_entries = entries_by_mechanism.get(rule_input.mechanism, [])
        if not matching_entries:
            review_items.append(
                _review_item(
                    case.pseudonymous_case_id,
                    "mechanism_requires_approved_rule",
                    "The supplied mechanism has no approved v0.31.3 catalogue mapping.",
                    rule_input.rule_input_id,
                )
            )
            continue
        if not readiness_allows_genomic_options and any(
            entry.test_class in _READINESS_GATED_TEST_CLASSES for entry in matching_entries
        ):
            review_items.append(
                _review_item(
                    case.pseudonymous_case_id,
                    "investigation_option_deferred_by_pretest_readiness",
                    "Test and investigation classes are not surfaced until deterministic pre-test readiness is confirmed.",
                    rule_input.rule_input_id,
                )
            )
            continue
        for entry in matching_entries:
            option_inputs.append((entry, facts, [rule_input.rationale_exact]))

    if not request.rule_inputs and readiness_allows_genomic_options:
        review_items.append(
            _review_item(
                case.pseudonymous_case_id,
                "no_approved_rule_input_supplied",
                "Supply a human-reviewed mechanism input with linked structured facts; the system will not invent a disease-specific test-selection rule.",
            )
        )

    options = _build_options(
        case,
        option_inputs,
        supplied_context=supplied_context,
        readiness_allows_genomic_options=readiness_allows_genomic_options,
    )
    if readiness_outcome is None:
        rationale_codes = ["pre_test_assessment_not_supplied"]
    elif not readiness_allows_genomic_options:
        rationale_codes = ["pre_test_readiness_not_confirmed", readiness_outcome.value]
    else:
        rationale_codes = ["pre_test_readiness_confirmed"]
    if review_items:
        rationale_codes.append("rule_review_items_open")
    if linkage_issues:
        rationale_codes.append("strategy_fact_linkage_issues")

    if not readiness_allows_genomic_options:
        workspace_status = StrategyWorkspaceStatus.DEFERRED_PENDING_PREREQUISITES
    elif review_items and not options:
        workspace_status = StrategyWorkspaceStatus.REQUIRES_RULE_REVIEW
    elif review_items or linkage_issues:
        workspace_status = StrategyWorkspaceStatus.AWAITING_HUMAN_REVIEW
    else:
        workspace_status = StrategyWorkspaceStatus.PROPOSED_OPTIONS_FOR_REVIEW

    constrained_count = sum(item.feasibility_status == StrategyFeasibilityStatus.CONSTRAINED for item in options)
    deferred_count = sum(
        item.feasibility_status == StrategyFeasibilityStatus.DEFERRED_PENDING_PREREQUISITES for item in options
    )
    return TestStrategyWorkspaceResult(
        pseudonymous_case_id=case.pseudonymous_case_id,
        pre_test_assessment_outcome=readiness_outcome.value if readiness_outcome else None,
        workspace_status=workspace_status,
        status_rationale_codes=sorted(set(rationale_codes)),
        comparison_note_exact=request.comparison_note_exact,
        comparison_dimensions=_COMPARISON_DIMENSIONS,
        options=options,
        rule_review_items=sorted(review_items, key=lambda item: item.review_item_id),
        linkage_issues=sorted(linkage_issues, key=lambda item: item.issue_id),
        proposed_option_count=len(options),
        constrained_option_count=constrained_count,
        deferred_option_count=deferred_count,
        test_strategy_generated=bool(options),
    )


def _automatic_option_inputs(case, pretest, entries_by_class):
    inputs: list[tuple[TestCatalogueEntry, list[StrategyTriggerFact], list[str]]] = []
    if pretest is None or pretest.assessment_outcome != PreTestWorkflowOutcome.READY_FOR_TEST_STRATEGY_REVIEW:
        outcome = pretest.assessment_outcome.value if pretest else "not_supplied"
        fact = _upstream_fact(
            case.pseudonymous_case_id,
            "pretest_readiness",
            f"Deterministic pre-test assessment outcome: {outcome}.",
            "pre_test_assessment.assessment_outcome",
            [case.pseudonymous_case_id],
        )
        inputs.append(
            (
                entries_by_class[TestClass.NO_GENOMIC_TEST_YET],
                [fact],
                ["The pre-test workspace has not confirmed readiness for genomic test-strategy review."],
            )
        )
    if pretest is None:
        return inputs

    incomplete_reports = [
        item
        for item in [*pretest.previous_investigation_timeline, *pretest.known_family_reports]
        if item.report_availability
        in {RecordAvailability.PARTIAL, RecordAvailability.REQUESTED, RecordAvailability.UNKNOWN, RecordAvailability.NOT_ASSESSED}
    ]
    if incomplete_reports:
        item = sorted(
            incomplete_reports,
            key=lambda value: getattr(value, "investigation_id", getattr(value, "family_report_id", "")),
        )[0]
        record_id = getattr(item, "investigation_id", getattr(item, "family_report_id", "report"))
        fact = _upstream_fact(
            case.pseudonymous_case_id,
            "incomplete_existing_report",
            f"Supplied report availability for {record_id}: {item.report_availability.value}.",
            "pre_test_assessment.previous_investigation_timeline_or_known_family_reports",
            [record_id],
        )
        inputs.append(
            (
                entries_by_class[TestClass.OBTAIN_OR_REVIEW_EXISTING_REPORT],
                [fact],
                ["A represented previous-investigation or family report is incomplete, requested, unknown, or not yet assessed."],
            )
        )

    missing_categories = {
        item.category for item in [*pretest.blocking_items, *pretest.human_review_items, *pretest.advisory_items]
    }
    if missing_categories & {MissingInformationCategory.CLINICAL_HISTORY, MissingInformationCategory.PHENOTYPE}:
        ids = sorted(
            item.request_id
            for item in [*pretest.blocking_items, *pretest.human_review_items, *pretest.advisory_items]
            if item.category in {MissingInformationCategory.CLINICAL_HISTORY, MissingInformationCategory.PHENOTYPE}
        )
        fact = _upstream_fact(
            case.pseudonymous_case_id,
            "clinical_context_incomplete",
            "The deterministic pre-test plan contains unresolved clinical-history or phenotype context.",
            "pre_test_assessment.missing_information_plan",
            ids or [case.pseudonymous_case_id],
        )
        inputs.append(
            (
                entries_by_class[TestClass.ADDITIONAL_CLINICAL_ASSESSMENT],
                [fact],
                ["Additional structured clinical context is required before or alongside strategy review."],
            )
        )
    if pretest.human_review_items:
        ids = sorted(item.request_id for item in pretest.human_review_items)
        fact = _upstream_fact(
            case.pseudonymous_case_id,
            "human_review_items_open",
            f"Deterministic pre-test assessment has {len(ids)} open human-review item(s).",
            "pre_test_assessment.human_review_items",
            ids,
        )
        inputs.append(
            (
                entries_by_class[TestClass.SPECIALIST_REVIEW],
                [fact],
                ["Open human-review items require accountable clinical judgment; no test class is selected automatically."],
            )
        )
    return inputs


def _build_options(
    case,
    option_inputs,
    *,
    supplied_context,
    readiness_allows_genomic_options,
):
    merged: dict[TestClass, dict[str, Any]] = {}
    for entry, facts, reasons in option_inputs:
        bucket = merged.setdefault(entry.test_class, {"entry": entry, "facts": {}, "reasons": set()})
        for fact in facts:
            bucket["facts"][fact.fact_id] = fact
        bucket["reasons"].update(reasons)

    options: list[TestStrategyOption] = []
    for test_class in sorted(merged, key=lambda item: item.value):
        bucket = merged[test_class]
        entry: TestCatalogueEntry = bucket["entry"]
        feasibility, extra_defer = _feasibility(
            case,
            entry,
            readiness_allows_genomic_options=readiness_allows_genomic_options,
        )
        facts = sorted(bucket["facts"].values(), key=lambda item: item.fact_id)
        option_id = _stable_id(
            "TSOPT",
            case.pseudonymous_case_id,
            entry.catalogue_entry_id,
            *(fact.fact_id for fact in facts),
        )
        options.append(
            TestStrategyOption(
                option_id=option_id,
                catalogue_entry_id=entry.catalogue_entry_id,
                test_class=entry.test_class,
                display_name=entry.display_name,
                why_surfaced=sorted(bucket["reasons"]),
                trigger_facts=facts,
                general_detection_scope=entry.general_detection_scope,
                important_blind_spots=entry.important_blind_spots,
                proband_sample_requirements=entry.proband_sample_requirements,
                family_sample_requirements=entry.family_sample_requirements,
                supplied_context=supplied_context,
                prerequisites=entry.prerequisites,
                reasons_to_defer=sorted(set([*entry.reasons_to_defer, *extra_defer])),
                after_negative_result=entry.after_negative_result,
                feasibility_status=feasibility,
            )
        )
    return options


def _feasibility(case, entry, *, readiness_allows_genomic_options):
    if entry.test_class == TestClass.NO_GENOMIC_TEST_YET:
        return StrategyFeasibilityStatus.DEFERRED_PENDING_PREREQUISITES, []
    if entry.test_class in _READINESS_GATED_TEST_CLASSES and not readiness_allows_genomic_options:
        return StrategyFeasibilityStatus.DEFERRED_PENDING_PREREQUISITES, [
            "Deterministic pre-test readiness is not confirmed."
        ]

    context = case.pre_test_assessment.context_review if case.pre_test_assessment else None
    if entry.test_class in _GENOMIC_TEST_CLASSES and context:
        if context.sample_availability == SampleAvailabilityReview.NONE_AVAILABLE:
            return StrategyFeasibilityStatus.CONSTRAINED, ["No suitable proband sample is reported as available."]
        if context.sample_availability in {
            SampleAvailabilityReview.UNKNOWN,
            SampleAvailabilityReview.NOT_ASSESSED,
        }:
            base_status = StrategyFeasibilityStatus.UNKNOWN
        else:
            base_status = StrategyFeasibilityStatus.REVIEWABLE
    else:
        base_status = StrategyFeasibilityStatus.REVIEWABLE

    if entry.test_class == TestClass.KNOWN_FAMILIAL_VARIANT_TESTING:
        family_reports = case.pre_test_assessment.known_family_reports if case.pre_test_assessment else []
        if not any(item.report_availability == RecordAvailability.AVAILABLE for item in family_reports):
            return StrategyFeasibilityStatus.CONSTRAINED, [
                "No linked family report is represented as available for exact familial-variant verification."
            ]

    if entry.family_sample_mode == FamilySampleMode.TRIO_REQUIRED:
        categories = {
            getattr(item.sample_category, "value", item.sample_category)
            for item in (case.global_intake_context.family_sample_contexts if case.global_intake_context else [])
            if getattr(item.sample_availability, "value", item.sample_availability)
            in {"available", "potentially_available"}
        }
        if not {"maternal", "paternal"} <= categories:
            return StrategyFeasibilityStatus.CONSTRAINED, [
                "Suitable maternal and paternal samples are not both represented as available or potentially available."
            ]
    access_constraints = _access_constraint_values(case)
    if access_constraints and entry.test_class not in {
        TestClass.NO_GENOMIC_TEST_YET,
        TestClass.OBTAIN_OR_REVIEW_EXISTING_REPORT,
        TestClass.ADDITIONAL_CLINICAL_ASSESSMENT,
        TestClass.SPECIALIST_REVIEW,
        TestClass.MULTIDISCIPLINARY_REVIEW,
    }:
        return StrategyFeasibilityStatus.CONSTRAINED, [
            "Supplied access constraints require feasibility review: " + ", ".join(access_constraints)
        ]
    return base_status, []


def _supplied_context(case) -> SuppliedStrategyContext:
    global_context = case.global_intake_context
    pretest_context = case.pre_test_assessment.context_review if case.pre_test_assessment else None
    access = global_context.testing_access_context if global_context else None
    locale = global_context.locale_profile if global_context else None
    laboratories = []
    if global_context:
        for item in global_context.laboratory_contexts:
            laboratories.append(
                " | ".join(
                    part
                    for part in [
                        item.laboratory_source_id,
                        item.source_label,
                        item.test_type_exact,
                        getattr(item.report_completeness, "value", item.report_completeness),
                    ]
                    if part
                )
            )
        for item in getattr(locale, "laboratory_report_context", ()) or ():
            laboratories.append(
                " | ".join(
                    part for part in [item.laboratory_source_id, item.source_label, item.test_type_exact] if part
                )
            )
    family_samples = []
    if global_context:
        for item in global_context.family_sample_contexts:
            family_samples.append(
                " | ".join(
                    part
                    for part in [
                        item.family_member_id,
                        item.relationship_to_proband_exact,
                        getattr(item.sample_category, "value", item.sample_category),
                        getattr(item.sample_availability, "value", item.sample_availability),
                        item.sample_type_exact,
                    ]
                    if part
                )
            )
    constraints = [getattr(item, "value", item) for item in (access.constraints if access else [])]
    if pretest_context:
        constraints.extend(pretest_context.access_constraints_exact)
    if access and access.other_constraint_exact:
        constraints.append(access.other_constraint_exact)
    if locale and getattr(locale, "testing_access_context", None):
        locale_access = locale.testing_access_context
        constraints.extend(getattr(item, "value", item) for item in locale_access.constraints)
        if locale_access.other_constraint_exact:
            constraints.append(locale_access.other_constraint_exact)
    sample_context = []
    if pretest_context and pretest_context.sample_context_exact:
        sample_context.append(pretest_context.sample_context_exact)
    if pretest_context:
        sample_context.append(f"pre-test sample availability: {pretest_context.sample_availability.value}")
    locale_access = getattr(locale, "testing_access_context", None)
    turnaround = (
        access.estimated_turnaround_time_exact
        if access and access.estimated_turnaround_time_exact
        else locale_access.estimated_turnaround_time_exact
        if locale_access
        else None
    )
    return SuppliedStrategyContext(
        care_setting=getattr(global_context.care_setting, "value", None) if global_context else None,
        locale_profile_type=getattr(locale, "profile_type", None),
        laboratory_availability_context=sorted(set(laboratories)),
        access_constraints=sorted(set(str(item) for item in constraints)),
        turnaround_time_exact=turnaround,
        affordability_context_exact=pretest_context.affordability_context_exact if pretest_context else None,
        sample_context=sample_context,
        family_sample_context=sorted(set(family_samples)),
    )


def _known_record_ids(case, pretest, phenotype_curation, pedigree_audit) -> set[str]:
    identifiers = {case.pseudonymous_case_id}
    identifiers.update(item.source_id for item in case.provenance)
    identifiers.update(item.observation_id for item in case.phenotypes)
    identifiers.update(item.candidate_id for item in case.candidate_variants)
    identifiers.update(item.family_member_id for item in case.pedigree)
    identifiers.update(item.hypothesis_id for item in case.hypotheses)
    if case.pre_test_assessment:
        request = case.pre_test_assessment
        if request.referral_packet:
            identifiers.add(request.referral_packet.referral_id)
        if request.clinical_history:
            identifiers.add(request.clinical_history.history_id)
            identifiers.update(item.item_id for item in request.clinical_history.items)
        identifiers.update(item.investigation_id for item in request.previous_investigations)
        identifiers.update(item.family_report_id for item in request.known_family_reports)
        identifiers.update(item.request_id for item in request.supplied_missing_information_requests)
        identifiers.update(item.checkpoint_id for item in request.clinician_checkpoints)
    if pretest:
        identifiers.update(item.request_id for item in pretest.missing_information_plan)
        identifiers.update(item.issue_id for item in pretest.linkage_issues)
    if phenotype_curation:
        for name in ("source_snippets", "hpo_suggestions", "contradictions", "promoted_observations"):
            for item in getattr(phenotype_curation, name, ()) or ():
                for attribute in ("snippet_id", "suggestion_id", "contradiction_id", "observation_id"):
                    value = getattr(item, attribute, None)
                    if value:
                        identifiers.add(value)
    if pedigree_audit:
        for name in ("inheritance_audits", "relationship_issues", "mendelian_inconsistencies"):
            for item in getattr(pedigree_audit, name, ()) or ():
                for attribute in ("audit_id", "issue_id", "audit_target_id"):
                    value = getattr(item, attribute, None)
                    if value:
                        identifiers.add(value)
    return identifiers


def _access_constraint_values(case) -> list[str]:
    values: list[str] = []
    global_context = case.global_intake_context
    if global_context and global_context.testing_access_context:
        access = global_context.testing_access_context
        values.extend(getattr(item, "value", item) for item in access.constraints)
        if access.other_constraint_exact:
            values.append(access.other_constraint_exact)
    locale = global_context.locale_profile if global_context else None
    if locale and getattr(locale, "testing_access_context", None):
        access = locale.testing_access_context
        values.extend(getattr(item, "value", item) for item in access.constraints)
        if access.other_constraint_exact:
            values.append(access.other_constraint_exact)
    if case.pre_test_assessment:
        values.extend(case.pre_test_assessment.context_review.access_constraints_exact)
    return sorted(set(str(item) for item in values))


def _upstream_fact(case_id, suffix, summary, source_path, record_ids):
    return StrategyTriggerFact(
        fact_id=_stable_id("TSFACT", case_id, suffix, *record_ids),
        fact_summary_exact=summary,
        source_path=source_path,
        source_record_ids=sorted(set(record_ids)),
    )


def _review_item(case_id, code, message, rule_input_id=None):
    return StrategyRuleReviewItem(
        review_item_id=_stable_id("TSRULE", case_id, code, rule_input_id or "workspace"),
        code=code,
        rule_input_id=rule_input_id,
        message=message,
    )


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"
