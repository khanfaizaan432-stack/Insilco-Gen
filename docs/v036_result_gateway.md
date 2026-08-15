# v0.36 Controlled Clinical Result and Bioinformatics Gateway

v0.36 is a local, deterministic gateway for supplied clinical-result packages. It is a research-curation surface, not a diagnostic, clinical-interpretation, accreditation-verification, treatment, or sign-out system.

## Fail-closed package contract

One package must contain exactly one manifest entry and one supplied byte object for each fixed role:

1. `vcf`
2. `structured_laboratory_report`
3. `qc`
4. `coverage`
5. `assay_metadata`

These five strings are the exact canonical serialized values. Role values are not trimmed, case-converted, or promoted through aliases: values such as `variant`, `VCF`, `vcf `, `lab_report`, and `laboratory_report` are rejected before role multiplicity checks, parsing, or adapter execution. Paths are normalized to Unicode NFC and then compared with case folding. Absolute paths, traversal components, URLs, backslashes, control characters, symlinks, duplicate paths, Unicode-equivalent paths, and case-colliding paths are rejected. VCF roles require an allowlisted VCF media type and a `.vcf` path; the four structured roles require `application/json` and `.json`. Minimal content signatures prevent a correctly hashed QC document, for example, from being relabelled as coverage or assay metadata.

The gateway verifies the complete path/role set, media type, extension, exact byte size, and exact SHA-256 before a domain parser can run. Any structural error produces a blocked result with typed errors, `manifest_verified=false`, no parsed models, and no adapter results. Multiple structural errors are returned together. Scientific handling such as retaining an explicitly supplied CNV out of scope occurs only after the whole package passes structural verification.

Raw package bytes and `content_base64` are never persisted in the gateway result or reproducibility artifact.

## Complete package identity and replay

`input_manifest_sha256` remains the manifest-only hash. `package_identity_sha256` is a separate hash of canonical JSON for `insilicopop.package-identity.v0.36.1` and is the replay identity.

The identity payload includes:

- package identifier, package schema and package version;
- declared reference build;
- domain-separated SHA-256 bindings for the expected pseudonymous sample and declared case (never their raw values in the identity payload);
- the human-review and draft-approval boundaries;
- all configured limits that can affect analysis;
- every manifest semantic field: normalized path, role, media type, exact SHA-256, optional canonical hash, byte size, parser version, and schema version;
- independently calculated exact file hashes and sizes;
- an explicit assay-metadata byte/canonical/schema/parser binding;
- typed analysis intent, parameter schema identifier/version, budgets, approval state, and record selector;
- every typed adapter invocation and selector, sorted by invocation identifier.

Manifest order and supplied-file order do not change an otherwise identical package identity. Requested selector order is preserved and is semantically relevant. Package version, build, sample/case binding, manifest metadata, assay metadata or bytes, adapter intent, typed parameters, approval, and requested record selection do change the identity. Replay-control values and runtime timestamps are excluded.

Each adapter execution has a distinct `insilicopop.adapter-invocation-identity.v0.36.1` canonical payload exposed by `adapter_invocation_identity_payload`. It directly binds `package_identity_sha256`, `input_manifest_sha256`, adapter and parameter-schema identity/version, canonical typed parameters, exact original requested selectors, validated selected selectors, selector validation issues, file-byte hashes, budgets, approval, network/work-directory policy, and the remaining execution-affecting fields. The low-level adapter entry point requires the package identity and has no manifest-hash fallback. Package, manifest, file-byte, canonical-file-payload, and invocation hashes remain separate concepts.

Use `previous_package_identity_sha256`, `expected_package_identity_sha256`, and `duplicate_of_package_identity_sha256` for new integrations. Legacy `previous_input_manifest_sha256` and `duplicate_of_input_manifest_sha256` are retained as fail-closed aliases but are compared with the complete package identity, not the manifest-only digest.

## VCF FORMAT, genotype, phase, and INFO behavior

The parser preserves source and parsed representations separately. Each record retains:

- FORMAT key order and the exact source FORMAT token;
- sample-column order and identifiers after the existing identifier-redaction policy;
- each complete source sample token;
- each FORMAT key/value source token, including unknown keys, plus deterministic provenance;
- the unchanged source GT token, nullable allele indices, separator sequence, ploidy, complete/partial-missing states, and phased, unphased, or unknown phase state;
- the exact PS source token when supplied;
- the source INFO token and immutable typed INFO entries.

Examples include `GT:DP:PS` with `0|1:10:123`, unphased `0/1`, haploid, diploid and polyploid calls, `./.`, `.|.`, partial missing calls such as `1/.`, missing FORMAT values, and multiple samples. A sample-value count different from the FORMAT-key count, an invalid allele index, duplicate/empty FORMAT key, or record/header column mismatch is an explicit parser error. Unsupported FORMAT data is never silently dropped.

For multiallelic decomposition, every ALT-specific record carries the same unchanged source genotype and allele indices plus its one-based `source_alt_index`. No misleading biallelic genotype is synthesized. `selected_alt_presence` has these exact semantics:

- `present` when the selected ALT index occurs in the supplied GT, even if another allele is missing;
- `absent` only when GT is supplied, all alleles are known, and the selected index is absent;
- `unknown` when GT is absent, wholly missing, or partially missing without a deterministic occurrence of that ALT.

INFO header definitions are parsed. `.` is the sole missing INFO representation. An empty, whitespace-only, absent, or trailing-tab-empty INFO field is malformed. Duplicate keys, empty/malformed tokens, a value assigned to a declared Flag, and a bare key that is not a declared `Type=Flag` are rejected. Unknown but well-formed `KEY=value` fields are retained with source provenance. Values are never overwritten by a later duplicate.

All `##reference` and `##assembly` declarations are collected. Conflicting declarations block parsing. Repeated identical declarations are accepted with the deterministic `repeated_reference_declaration` warning.

Out-of-scope records carry both a typed scope and typed reason code. Repeat and mosaic states require explicit source support such as `SVTYPE=STR`, a repeat symbolic allele, or a declared `MOSAIC` Flag; low allele fraction alone does not trigger either inference. Mitochondrial, generic symbolic, structural/breakend, CNV, and greater-than-50-base indel reasons are distinct.

No reference-dependent left normalization or external annotation retrieval occurs.

## Typed adapter policy and selectors

The immutable registry contains:

- `deterministic_supplied_result_summary` with `insilicopop.summary.parameters` version `1.0`;
- unavailable `bcftools_left_normalization` with its fixed schema;
- unavailable `vep_supplied_annotation_reconciliation` with its fixed schema.

Every definition declares the parameter-schema identifier/version and an immutable typed default model. The summary schema contains only the literal `mode="summary_only"`. Unknown keys, wrong types, coercible-but-wrong values, schema-version changes, commands, URLs, images, containers, executables, paths, and arbitrary extensions fail validation. Unavailable adapters pass the same typed request and selector checks before returning `unavailable`.

`input_record_ids` semantics are explicit:

- omitted (`null`) selects all eligible SNV/small-indel records;
- an explicit empty list selects no records and returns a deterministic zero-record summary;
- duplicates block the invocation before execution;
- unknown IDs and supplied out-of-scope IDs block the invocation;
- `requested_input_record_ids` preserves the exact immutable typed request, including order and duplicates, while `selected_input_record_ids` contains only validated eligible IDs;
- selector validation issues and rejection reasons remain distinct in normalized invocation and provenance;
- every adapter-output field, including counts and decomposition status, is derived only from selected eligible records. Package-wide context remains package-level provenance and cannot influence the selected-record summary.

The available built-in action requires an explicit human-review approval flag. It runs only in-process. No subprocess, shell, network, external tool, container, installation, database download, or arbitrary working-directory path exists in the implementation.

## Deep immutability

Persisted gateway collections are tuples. Former mapping-shaped internals use typed immutable entries for file hashes, database versions, metrics, INFO/FORMAT values, variant-scope counts, and output summaries. Adapter parameters are frozen per-adapter models. Validation defensively reconstructs caller-supplied values, so later mutation of the source object cannot alter a request or result.

Explicit field serializers retain practical API compatibility: JSON still exposes file hashes, database versions, metrics, and variant-scope counts as objects, while tuples serialize as JSON arrays. Reverse validators reconstruct immutable tuples from those public mappings with strict keys and integer counts. Missing adapter output serializes as JSON `null`, not `{}`. A public or persisted `ResultGatewayResult` round-trips through standard JSON and typed validation to stable public JSON. A serialized copy is detached; mutating it cannot alter the model, package identity, invocation hash, or output hash.

## Accreditation trust separation

Package accreditation wording is represented only as `SuppliedAccreditationClaim`. Values including `verified`, `VERIFIED`, `independently_verified`, spelling/casing variants, or package-supplied “trusted evidence” remain `supplied_but_unverified`. Missing claims remain `not_supplied`; explicit `not_applicable` remains `not_applicable`.

`AccreditationEvidence` defines the separate trusted schema for NABL or ISO 15189 evidence: standard/body, certificate/reference, supplied scope, evidence digest/type, verifier provenance, timestamp, reviewer/action identifier, status, reason, and trusted-channel type. v0.36 has no authorized action that populates this channel, so package-originating claims can never create an independently verified state and `trusted_accreditation_evidence` remains empty.

## Workbench stages 9 and 10

The Workbench now provides a pre-submission workflow, not only a post-run panel:

- package file selection and local synthetic-fixture loading;
- authoritative preview through the existing gateway backend;
- manifest, role, media, byte/hash, typed-error, redacted-sample, and build review;
- explicit build confirmation and package rejection;
- laboratory/accreditation trust labels, QC, poor coverage, reportable scope, blind spots, supplied limitations, and separate CNV/mitochondrial/repeat/mosaic scope fields;
- allowlisted adapter/version/availability selection;
- controls generated from the adapter’s typed default schema, with no free-form command or parameter JSON;
- actual eligible-record selection and selected-record provenance;
- human-approval gating and clear unavailable/blocked reasons;
- execution status and hashes.

The visible safety boundary remains: draft not clinically approved, research use only, human review required, no diagnosis, and no clinical sign-out. At narrow widths the primary grids collapse, all children use `min-width: 0`, and technical tables scroll inside labelled containers. Natural DOM tab order is used; focus is visible, errors are announced/focused, and no code intercepts Tab.

## Fixture and integration

The compact fixture is [canonical_v036_result_package.json](../examples/insilicopop_demo/canonical_v036_result_package.json). It includes two sample columns; phased `0|1` with PS; DP, AD, GQ and an unknown FORMAT key; a multiallelic `1/2`; a symbolic CNV retained out of scope; poor coverage; assay blind spots; hostile supplied NABL/ISO wording that remains unverified; typed parameter schemas; an explicit two-record selector; a successful built-in adapter; a version-blocked invocation; and an unavailable registered adapter.

Malformed INFO, conflicting build headers, missing/duplicate/unknown or aliased roles, media/content spoofing, selector attacks, and mutation attempts are demonstrated by the v0.36 adversarial tests rather than by making the canonical success fixture invalid. The second correction pass changed the fixture's former `laboratory_report` role to the required `structured_laboratory_report` canonical value; that deliberate input-contract correction changes the package and invocation identities while leaving all exact file-byte hashes unchanged.

Run the deterministic fixture from the active repository:

```powershell
cd "C:\dev\Insillico OS\backend"
python -m app.insilicopop.cli v036-demo
```

When supplied through structured clinical intake, the result is present in the existing API response, `AgentState.result_gateway`, stages 9/10 of the v0.35 handoff, the Workbench, `reproducibility/result_gateway.json`, runtime lock, and decision trace. JSON widths and v0.27-v0.35 meanings remain compatible. v0.36 adds requested/selected selector and selector-issue provenance, strict canonical roles, package/manifest-bound invocation identity, selected-only summary derivation, symmetric JSON reload, explicit empty-selector behavior, and rejection of formerly accepted arbitrary adapter parameter objects.

## Remaining v0.36 limits

- No independent accreditation-verification action is authorized.
- No raw reads or raw CNV, mitochondrial, repeat, or mosaic calling is performed.
- No reference-dependent left normalization or external annotation database is available.
- The built-in adapter is a deterministic supplied-result summary, not a clinical interpretation.
- Every result remains a draft requiring qualified human review.

No v0.37 behavior is defined or implemented here.
