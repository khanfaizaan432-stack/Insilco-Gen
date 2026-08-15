# InSilicoPop v0.36 Release Manifest

## Release identity

- Release: `v0.36`
- Milestone: **Controlled Clinical Result and Bioinformatics Gateway**
- Release date: `2026-08-15`
- Previous frozen version: `v0.35`
- Starting v0.35 commit: `93183e5999680cfb92534ebd502df8a1d75380d5`
- Final release-manifest commit: `SELF` — the commit containing this manifest and the peeled target of annotated tag `v0.36`

The final release commit is identified symbolically above because a Git commit
cannot embed its own final object hash without changing that hash. The
authoritative resolved hash is the peeled `v0.36` tag target and is recorded in
the tag annotation and release handoff.

## Versioned contracts

- Gateway schema: `insilicopop-result-gateway-0.36.0`.
- Parser version: `insilicopop-result-package-parser-0.36.0`.
- Adapter invocation identity: `insilicopop.adapter-invocation-identity.v0.36.1`.
- Exact serialized logical roles: `vcf`, `structured_laboratory_report`, `qc`,
  `coverage`, and `assay_metadata`.
- Workbench controlled result intake: stages 9 and 10 of the existing
  18-stage navigator.
- Previous v0.35 bundle widths and handoff meanings remain unchanged through
  the additive v0.36 gateway fields.

## Bounded capability

v0.36 adds a fail-closed supplied-result gateway for a complete redacted
package. It requires one file for each exact canonical role, verifies safe
paths, role/media/extension/content consistency, byte sizes and SHA-256 values,
and blocks parsing or adapter execution for structural failures. The canonical
fixture is entirely synthetic.

The gateway deterministically preserves VCF FORMAT order, sample order,
genotypes, ploidy, phase, PS, missing values, unknown source fields, and source
INFO tokens. Multiallelic records are decomposed deterministically. Reference-
dependent left normalization is explicitly absent; unsupported and
out-of-scope records are retained with typed reasons rather than interpreted.

The adapter registry is strict and allowlisted. Parameters are typed and
immutable. Invocation identity binds the complete package identity, manifest
identity, exact file-byte hashes, adapter/schema identity, typed parameters,
approval state, budgets, requested selectors, selected selectors, and selector
issues. Adapter summaries use selected eligible records only.

Persisted result models are deeply immutable and symmetric through public JSON
serialization and typed reload. Missing adapter output serializes as JSON
`null`. Package and manifest identity remain separate concepts from exact
persisted-byte and canonical-payload hashes.

Supplied laboratory accreditation claims remain supplied/unverified. No trusted
accreditation-verification action exists in v0.36.

## Accepted deterministic identities

- Canonical package identity:
  `da0dcd7422c2af062a47ec5949a32fc80eb5da7cb54a2b9a66d535a430c49810`.
- Canonical manifest identity:
  `2071c8fcb3ea17b10ff8d3c909c9a3fb3b077e0d171ab0ea3ff66acc48a5ce05`.
- Deterministic CLI stdout SHA-256:
  `ac0f1c2ea3f6176ad054d3641468ba41dbbf089119a7691c595b837029cb910b`.
- Deterministic CLI output length: `2255` UTF-8 bytes.

### Supplied-file persisted and canonical hashes

| Relative path | Exact persisted-byte SHA-256 | Canonical-payload SHA-256 |
|---|---|---|
| `metadata/assay_scope.json` | `190ee9bf0db343cbb4ddbb942d638e19e87ed14f6f8a8a995fa305e043fa9a1f` | `dfd0a9c9106a4de9b36c0395645d060c6162aa3a2bc32647e4da6c00a66aa416` |
| `qc/coverage.json` | `f7f7a3d9d8febd27acdd11880277b3ed478555962f4fc83ffe2567d906d233c8` | `d3123ecdd55a519cf2c55622078340b4a5ae75e557b58f3f70db718f79fd3fee` |
| `qc/qc_summary.json` | `35f4a5048aa2ad8b0fdbdf9538354807ad14602f63a877fcfdd0205af061663b` | `a6b9852c39d2897a4bc80aabd012114471713ae9bda96932cdc541d75c4d4cef` |
| `reports/laboratory_report.json` | `4e81eda814712d924f0b95ebd4dd38fd76917f128c107bbb3d93e6533bf27b15` | `487e454790cb03c78f35e15ad0d1594cbe55cfc37576f659c7acb8079e647b30` |
| `results/synthetic.vcf` | `a91159bc637239c1f519f80b2dacf49a40017b5c42dc2e01b2d7971536b5510b` | `09b697630419828f4d66515e90300f0f485e6c06a12eaf5f10651b0bf59fa17e` |

## Accepted implementation manifest

The following SHA-256 values are the accepted v0.36 working-tree values before
release-only metadata updates. They cover the 14 modified tracked files and 8
new v0.36 files present at the frozen acceptance baseline.

| File | Bytes | SHA-256 |
|---|---:|---|
| `README.md` | 17987 | `3afe35314bff86056a425a43342faeb7d961e38426406394db792e3c535b5217` |
| `backend/app/insilicopop/agent/interpreter.py` | 88874 | `461b696e9c14b578f0efbf6d267b6fbadd1a7ea5024aae9d0dd202c95018f660` |
| `backend/app/insilicopop/agent/loop.py` | 42626 | `e2ce30d3686d081cebfc530908b0d7e536d11c8b3b146c4de1efc879ce6fcb12` |
| `backend/app/insilicopop/agent/reproducibility.py` | 54522 | `ff18c0d06d3954fd302d90509d085b889c65b7c3b53bb2ca86255c3f8d8e84d6` |
| `backend/app/insilicopop/agent/state.py` | 4840 | `0e48bf5ee9a59234be5d38fe675a35bf2778fef1dffac62bbc43d099b3c16e5d` |
| `backend/app/insilicopop/agent/trace.py` | 7011 | `b1caecfa5e0d730a7a5830344d11e73aa3b67bec55cbd2060d1449a93f76cf20` |
| `backend/app/insilicopop/agent/workbench.py` | 43067 | `a12308414fe8ec608cecc16f2a7efdf376c06f54398e59f3ab4584e7fa8253ab` |
| `backend/app/insilicopop/cli.py` | 16854 | `337a026c3e8268ef082e98e9f1bae2a681d0ca7442adb7496fa605b37fc6627b` |
| `backend/app/insilicopop/clinical/__init__.py` | 6256 | `2289e2fca7868012f2b40902a10b8ec11e435d8de05d05f45fc43cd710cb26e9` |
| `backend/app/insilicopop/clinical/handoff.py` | 55913 | `5f1f9ee1c8a49cf53208c5ec4a5c9fef7469aa4c8271a53add0ad72cbcadc01e` |
| `backend/app/insilicopop/clinical/models.py` | 10626 | `cd88e65c0fba174ab11f75f4aab4cbb5701b9f34a6e6e586649a39558562590b` |
| `backend/app/insilicopop/clinical/service.py` | 17979 | `266897be9c0c5f3d2150ed4787e5e9e20099ff6bc48114ab35a215ced70c623e` |
| `backend/app/insilicopop/workbench_static/index.html` | 196791 | `c4de29d7c35de487438e07237322677aac8d26f575f5976fcc9629345ad6b5c2` |
| `backend/app/main.py` | 24923 | `744c200b37367a45ad5eb091fbd74df7b06a98be6665517804d97388b6953106` |
| `backend/app/insilicopop/clinical/result_gateway.py` | 26401 | `87bff09fceeff46fd72d838a7b8a92fb2a28ebef64afc810805eb5bcc36bf50b` |
| `backend/app/insilicopop/clinical/result_gateway_execution.py` | 19242 | `4c3c34cb69ab571bd9d23762a995ae2d018655b7d5b5c72246a1d075bf9588ff` |
| `backend/app/insilicopop/clinical/result_gateway_models.py` | 44669 | `03b4bf88e5b24f8186e45d2439992304b798aa6b9173df2887004308dcd984b5` |
| `backend/app/insilicopop/clinical/result_gateway_parser.py` | 46010 | `78674f62668840afca4860c563400b027b8b9acb100c033a801e78bd3a5b97ba` |
| `backend/app/insilicopop/clinical/result_gateway_validation.py` | 10254 | `5b4b6f2712d1551f6f1efd6aa0aa6f60482e19627aa12437c8b8561bbea6fee7` |
| `backend/tests/test_result_gateway_v036.py` | 52604 | `9447c27321775b1b335cec00afd2a029fb3cc51cc44752302ce2e7f71fb1bb1d` |
| `docs/v036_result_gateway.md` | 14526 | `519d10de26ba5aab5936186524138a9906cc2fec1a365705d3e6041a7f5332a6` |
| `examples/insilicopop_demo/canonical_v036_result_package.json` | 9405 | `840df6c009775cbf0e53ab1ba1aaa5914f37ede7e84591cee755a9d3c0a45a17` |

The only accepted-file change made after that manifest was release metadata in
`README.md`: the v0.36 roadmap/status text now identifies the release as
locally frozen and links this manifest. No product source, test, fixture, or
v0.36 technical documentation changed. The resulting final release-commit
SHA-256 for `README.md` is
`b382472948a8ef73e432ee933ec317f870abf40ddf4452e5b12b1550aa30fc74`.

## Validation record

- Focused v0.36 tests: `73 passed, 58 warnings`.
- Full backend regression: `955 passed, 153 warnings`.
- Pre-tar validation: `PRE_TAR_CHECK_PASSED`.
- Fresh six-defect probes: `17/17 passed`.
- Independent matrix: `123/123 passed`.
- JavaScript syntax validation: passed.
- Deterministic `v036-demo`: two zero-exit byte-identical runs.
- Package/manifest identity reconstruction and persisted JSON reload: passed.
- Workbench rendered-DOM, responsive layout, accessibility semantics, safety,
  compatibility, and execution-isolation checks: passed.

## Research and clinical safety boundary

This release is **research use only** and requires **human expert review**.
Every v0.36 result retains `draft_not_clinically_approved=true`,
`human_review_required=true`, and `research_use_only=true`. The release does
not provide diagnosis, treatment recommendations, test ordering, final ACMG or
AMP classification, clinical sign-out, patient-facing return, external
annotation retrieval, raw-read ingestion, arbitrary command execution,
external LLM execution, or autonomous clinical decisions.

## Compatibility

The v0.27–v0.35 additive bundle widths remain unchanged. The 18-stage navigator
and v0.35 handoff receipt remain compatible. v0.36 adds the controlled result
gateway through existing API, Workbench, state, trace, runtime-lock, and
reproducibility surfaces.

## Accepted limitations

- bcftools/VEP-style external adapters remain unavailable by design.
- No external annotation retrieval occurs.
- No trusted accreditation-verification action exists in v0.36; supplied claims
  remain unverified.
- Unsupported scientific records are retained, not interpreted.
- Complete physical keyboard traversal could not be verified because genuine
  Tab events were unavailable in the installed environment.
- After explicit package rejection, some local record/approval widgets may
  remain visually interactive, but submission gates and the backend remain
  blocked.
- Full historical regression requires the unchanged external v0.25–v0.28
  archive fixtures. Those fixtures are regression dependencies, not v0.36
  product inputs, and are not included in the official source archive.

The official v0.36 archive and checksum are generated from the exact tagged
release commit and retained outside Git tracking. No remote publication is
authorized.
