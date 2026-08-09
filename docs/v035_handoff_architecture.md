# v0.35 Structured Human-Review Handoff

This document freezes the v0.35 implementation boundary against the v0.34
checkout at `a3576b6`.

## Scope

v0.35 adds a deterministic human-review handoff layer over the existing v0.27
through v0.34 clinical research-curation artifacts. It does not add raw
genomic parsing, clinical result calling, unrestricted retrieval, external LLM
execution, tool execution, diagnosis, treatment, final ACMG classification,
clinical sign-out, or patient-facing return.

## Frozen bundle contract

The existing builders remain unchanged:

| Builder | Width | New item |
| --- | ---: | --- |
| `build_clinical_case_full_bundle` | 5 | none |
| `build_clinical_case_strategy_bundle` | 6 | none |
| `build_clinical_case_result_evidence_bundle` | 7 | none |
| `build_clinical_case_specialist_agent_bundle` | 8 | none |
| `build_clinical_case_v034_bundle` | 9 | none |
| `build_clinical_case_v035_bundle` | 10 | `HandoffWorkspaceResult` at index 9 |

The v0.35 result has `schema_version="0.35"`, is deterministic for identical
inputs, and retains `report_status="draft_not_clinically_approved"`.

## Handoff state machine

```text
assembled -> under_human_review -> ready_for_external_handoff
                                      -> externally_handed_off

assembled, under_human_review, ready_for_external_handoff
    -> deferred
    -> withdrawn
```

`externally_handed_off`, `deferred`, and `withdrawn` are terminal. Mutations
against a terminal workspace are rejected. Mutations include the expected
revision and snapshot hash and are rejected atomically when either is stale.

## Handoff workspace

`HandoffWorkspaceResult` contains:

- the ordered 18-stage navigator;
- review readiness, blockers, acknowledgement-required uncertainties, and
  pending human decisions;
- pseudonymous reviewer references and external handoff events;
- requested actions, applied actions, rejected action results, and audit history;
- a deterministic artifact manifest, source hashes, schema versions, claim
  pointers, and evidence pointers;
- a deterministic handoff packet and a receipt whose status is `not_issued`
  until an external handoff event is recorded;
- revision and snapshot hash for stale-state protection;
- permanent research-use and safety flags.

Accepted uncertainty acknowledgements and blocker resolutions are review
actions only while the workspace is `under_human_review`. Stale, rejected, and
terminal actions are retained in audit history without mutating the active
state. The active receipt is regenerated after every accepted action so its
`handoff_state` always matches the workspace; a receipt becomes `issued` only
with a recorded external handoff event. Safety-policy blockers such as
diagnosis, treatment, test-order, clinical-sign-out, or final-classification
requests cannot be cleared by a handoff action.

The stage IDs and order are frozen:

1. `referral`
2. `clinical_history`
3. `phenotype_hpo`
4. `pedigree_family`
5. `previous_investigations`
6. `readiness`
7. `test_strategy`
8. `external_checkpoint`
9. `result_intake`
10. `qc_assay_scope`
11. `candidate_analysis`
12. `evidence`
13. `candidate_acmg`
14. `synthesis_critics`
15. `draft_report`
16. `human_review`
17. `external_handoff`
18. `reanalysis`

## API additions

The existing run and artifact endpoints remain compatible. v0.35 adds:

- `GET /insilicopop/agent/runs/{run_id}/handoff`
- `POST /insilicopop/agent/runs/{run_id}/handoff/actions`

The POST endpoint accepts one typed handoff action and returns the updated
workspace plus the typed applied/rejected result. It only mutates the selected
generated run directory, never source clinical artifacts or arbitrary paths.

## Artifact additions

The allowlisted reproducibility artifacts are:

- `reproducibility/handoff_workspace.json`
- `reproducibility/handoff_packet.json`
- `reproducibility/handoff_receipt.json`

They are included in the existing checksum and provenance flows.

## Artifact hash semantics

Each manifest item names its persisted path in `artifact_name`, currently an
allowlisted path under `reproducibility/`, and declares
`media_type="application/json"` and `hash_algorithm="sha256"`.

- `sha256` is the SHA-256 digest of the exact persisted file bytes for an
  available artifact.
- `digest_scope="file_bytes"` identifies that persisted-byte digest.
- `canonical_payload_sha256` is a separate in-memory identity digest over
  canonical JSON: UTF-8, sorted keys, compact separators, and no implicit
  filesystem newline.
- Persisted JSON uses UTF-8 bytes, sorted keys, two-space indentation, default
  JSON escaping, and no trailing newline. The writer and the manifest use the
  same serialization definition.
- An unavailable artifact has no persisted file, uses
  `digest_scope="not_available"`, and has `sha256=null`; its canonical payload
  digest remains explicit for the `null` payload.

The independent `reproducibility/checksums.sha256` ledger hashes the same
exact bytes for every generated file. Packet and snapshot hashes remain
canonical in-memory hashes and are not substituted for file-byte hashes.
