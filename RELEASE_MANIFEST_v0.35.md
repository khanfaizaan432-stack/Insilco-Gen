# InSilicoPop v0.35 Release Manifest

## Release identity

- Release: `v0.35`
- Milestone: **Structured Human-Review Handoff and Canonical Demo**
- Release date: `2026-08-09`
- Baseline version: `v0.34`
- Baseline commit: `a3576b62611474bca8a96ae0a4ec1e66cb992f78`
- Final release-manifest commit: `SELF` — the commit containing this manifest and the peeled target of annotated tag `v0.35`

The final release commit is identified symbolically because a Git commit cannot
embed its own final object hash without changing that hash. The authoritative
resolved hash is the peeled `v0.35` tag target and is recorded in the release
handoff and tag annotation.

## Versioned contracts

- Clinical bundle widths remain additive: 5, 6, 7, 8, and 9 are unchanged;
  `build_clinical_case_v035_bundle` is width 10 with `HandoffWorkspaceResult`
  at index 9.
- Handoff schema: `0.35`.
- Handoff workspace: `insilicopop-structured-handoff-0.35.0`.
- Handoff packet: `insilicopop-handoff-packet-0.35.0`.
- Handoff receipt: `insilicopop-handoff-receipt-0.35.0`.
- The navigator contains exactly these ordered stages:
  `referral`, `clinical_history`, `phenotype_hpo`, `pedigree_family`,
  `previous_investigations`, `readiness`, `test_strategy`,
  `external_checkpoint`, `result_intake`, `qc_assay_scope`,
  `candidate_analysis`, `evidence`, `candidate_acmg`, `synthesis_critics`,
  `draft_report`, `human_review`, `external_handoff`, and `reanalysis`.

## Bounded capability

v0.35 adds a deterministic structured human-review handoff layer over the
validated v0.27–v0.34 clinical research-curation artifacts. It provides:

- aggregate readiness, blockers, uncertainties, pending human decisions, and
  typed reviewer actions;
- the bounded state machine
  `assembled -> under_human_review -> ready_for_external_handoff -> externally_handed_off`;
- `deferred` and `withdrawn` terminal branches, stale revision/snapshot
  protection, and retained rejected-action audit history;
- deterministic handoff packets, receipts, artifact manifests, source hashes,
  schema versions, claim/evidence pointers, provenance, and audit events;
- a deterministic synthetic canonical fixture and exact `v035-demo` output;
- a Workbench 18-stage navigator, handoff dashboard, integrity display, and
  API-backed review controls.

`externally_handed_off` records an external event only. It never means clinical
approval.

## Handoff and integrity boundaries

- An active receipt is synchronized with the authoritative workspace state and
  current packet after every accepted action.
- A receipt is `not_issued` until a typed external handoff event references the
  current packet hash; it is `issued` only after that event.
- Available manifest entries carry SHA-256 over exact persisted file bytes.
  `canonical_payload_sha256` is a separate deterministic canonical-JSON digest.
- The reproducibility checksum ledger covers the same generated artifact bytes.
- Handoff artifacts are written under the generated run directory and use
  allowlisted paths only.

## Research and clinical safety boundary

This release is **research use only** and requires **human expert review**.
Every v0.35 workspace retains:

- `report_status="draft_not_clinically_approved"`;
- `human_review_required=true`;
- `research_use_only=true`;
- `clinical_approval_granted=false`;
- `diagnosis_made=false`;
- `treatment_recommendation_made=false`;
- `final_acmg_classification_made=false`;
- `clinical_sign_out_made=false`;
- `external_llm_called=false`;
- `external_tools_executed=false`;
- `unrestricted_browsing_used=false`;
- `raw_genomic_files_parsed=false`.

The release does not add diagnosis, treatment recommendations, test-ordering
authority, final ACMG classification, clinical sign-out, counselling,
patient-facing return, unsupported identity or relationship inference,
unrestricted retrieval, arbitrary command execution, external LLM execution,
or autonomous clinical decisions.

## Deterministic canonical demonstration

The canonical synthetic fixture is
`examples/insilicopop_demo/canonical_v035_case.json`. Its expected CLI record is
`examples/insilicopop_demo/expected_v035_demo_output.json`. The journey records
uncertainty acknowledgement, human decisions, blocker resolution, readiness
before the external event, the external event, and the issued receipt while
retaining the non-clinical safety flags.

## Validation record

- Complete v0.35/API/Workbench/compatibility/safety selection: `614 passed,
  111 warnings`.
- Full backend regression: `882 passed, 152 warnings`.
- Pre-tar backend and smoke checks: `882 passed, 152 warnings` and
  `PRE_TAR_CHECK_PASSED`.
- All v0.35 handoff tests: `11 passed`.
- Workbench rendered-DOM suite: `7 passed`.
- Embedded Workbench JavaScript syntax: passed.
- Canonical `v035-demo` fixture comparison: passed.
- Manifest file-byte/canonical hash and checksum reconstruction: passed.
- Legacy bundle-width compatibility and permanent safety-boundary checks:
  passed.

## Known non-blocking limitations

- Operational timestamps remain runtime metadata and are not expected to be
  identical across live runs; the canonical fixture uses deterministic values.
- Pixel-level browser and accessibility auditing was not part of v0.35
  acceptance; rendered-DOM behavior and JavaScript syntax were validated.

Historical source archives remain outside Git tracking. The official v0.35
archive and checksum are generated from the exact tagged release commit and
recorded in the release handoff.
