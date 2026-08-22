# InSilicoPop v0.37 Release Manifest

## Release identity and scope

- Release: `v0.37`
- Milestone: **Explainable Candidate and Family Analysis**
- Release date: `2026-08-22`
- Previous frozen version: `v0.36`
- Baseline commit: `2665785f6a13fcdf4b9426fecf640348d7d9f23e`
- Baseline branch: `main`
- Final release commit: `SELF` — the commit containing this manifest and the
  peeled target of the annotated local tag `v0.37`.
- Final release parent: the baseline commit above.
- Final release tag object: recorded after candidate reconstruction in the
  final release report.

The final commit is identified symbolically because a Git commit cannot embed
its own final object hash without changing that hash. The authoritative
resolved commit is the peeled target of the annotated `v0.37` tag.

This release freezes the independently accepted, deterministic v0.37
candidate-analysis implementation over the typed v0.36 result gateway. It is
a local source release only. Remote publication, a GitHub release, and all
v0.38 work are outside scope and were not authorized or performed.

## Intended committed-file inventory

The accepted implementation inventory contains exactly 20 v0.37 files. The
two release-only metadata files are listed separately. The hashes below are
the initial accepted working-tree snapshot taken before release metadata was
prepared.

| File | Initial bytes | Initial SHA-256 |
|---|---:|---|
| `README.md` | 19797 | `fdf89b11d84f0b884687f48ba661d2632b6f6565aadf93b3dc93f9376dff20ee` |
| `backend/app/insilicopop/agent/interpreter.py` | 91018 | `1f27cc23f5f4b018ce7a1c8a8473a9dc517e300f5e29536268242f95f8b7ce1a` |
| `backend/app/insilicopop/agent/loop.py` | 45071 | `abdba475734d85397f8d021919e869f128af565c5db6d7423b448256b049f16a` |
| `backend/app/insilicopop/agent/reproducibility.py` | 58074 | `c57b17af015854bf945eeb9a01d42d76fceb8dc152d7ac412da2cc8bd7f776c8` |
| `backend/app/insilicopop/agent/state.py` | 4989 | `ddbdc43f4b8228f077a0da5b1627a04204d86bb44bcee3ea5439a3fc7a2ede47` |
| `backend/app/insilicopop/agent/trace.py` | 7125 | `b63f931bf49d9bb9e49bcbf04b31f9957273e1e2d9496e4c61c773b92b6b855f` |
| `backend/app/insilicopop/agent/workbench.py` | 48242 | `b49d1b5dff2371b77de9ffc59bac939731f93dc01d8acc84bb83e86bbb666e83` |
| `backend/app/insilicopop/cli.py` | 22229 | `2176afdfa0e3b1e61fb594270af387ea70a4b7bff09b003af0e7da105d9f13e1` |
| `backend/app/insilicopop/clinical/__init__.py` | 6768 | `de7466c63ba9a249d4571b042ed553a61e8c21643475432c0f12ef6fe945315a` |
| `backend/app/insilicopop/clinical/candidate_analysis.py` | 107957 | `3c894b63fd1f20ba233cc9242b541148d14150dfa86dc579c061913f5a72d73f` |
| `backend/app/insilicopop/clinical/candidate_analysis_models.py` | 60901 | `2fbaf06197f86bb16ca28384ee8d2cd10509578a642defce8a0074da2a278cb4` |
| `backend/app/insilicopop/clinical/handoff.py` | 56562 | `15721c17e1e00f73eb0144f74f00661652daaf4b4c07978907f30ad461c483d6` |
| `backend/app/insilicopop/clinical/models.py` | 11121 | `356217cd287bdd7ab8a9e51e9a35808c783e52b2bdbf1df5527dbfe489f996b4` |
| `backend/app/insilicopop/clinical/service.py` | 19275 | `28ce5bfaef982f1e1a775a0b0026e4b442d329abfbcd31a13c3fc202f2787d61` |
| `backend/app/insilicopop/workbench_static/index.html` | 216935 | `efe3cd4e844fa3c458778e40c4a83c076cadce126450a2a7e58ab1bcdd21a19b` |
| `backend/tests/test_candidate_analysis_v037.py` | 48019 | `616d7389e63bd954d571120dc5f8bd25b9f33993ed06baf6d58c87980bd74560` |
| `docs/v037_candidate_analysis.md` | 11651 | `8b94775f1d01731cfcc8ebc1ad29c2017b3760438b8cf76b595ee6cd5477dd11` |
| `examples/insilicopop_demo/README.md` | 2793 | `a0bb649c9ee241d1a17cab30c4999034ece713279b5e8f1c634284e55e25730a` |
| `examples/insilicopop_demo/canonical_v037_candidate_analysis.json` | 11772 | `6970ffdccab9946cce286aa9feffd8e44287125409a45525a3021bd16e70ea09` |
| `examples/insilicopop_demo/expected_v037_candidate_analysis_output.json` | 4200 | `7644eecd376311584c10c0ddf44d264346ce40c4dc56139990b2b5a8efff2e65` |

The two release-only metadata files are:

- `RELEASE_MANIFEST_v0.37.md`
- `RELEASE_FIXTURES_v0.37.md`

`README.md` receives only the minimal release/version wording and manifest
link authorized by the v0.35/v0.36 convention. Its final release-metadata
working-tree hash is `094cb387b1b14fcf8a9a4daa76109113597e5e9286f0940c024a084d1b5eb7d8`
and its final size is 19826 bytes. No other accepted file is changed after
the initial snapshot.

## Bounded accepted capability

v0.37 adds a deterministic, explainable candidate-analysis result over the
typed v0.36 package. It binds candidate identity to the complete supplied
source record, source bytes, package, manifest, invocation, coordinates,
alleles, ALT index, source gene/transcript and schema. It rejects caller
aliases and mismatched representations rather than silently reconciling them.

The fixed ranking registry uses strict finite bounded numeric inputs,
canonical unordered-input identities, deterministic score ordering, complete
tie-group marking, and visible component explanations. The result records
supplied phenotype evidence, family observations, bounded de novo
prerequisites, missing information, unresolved questions, coverage gaps,
unavailable adapters, and explicit source labels. Family and compound-pair
states remain based on actual supplied v0.36 header/sample/selected-ALT/GQ
records, with safe `phase_unknown` handling and no relationship inference.

Candidate results are embedded additively through the existing ten-item
clinical bundle, AgentState/API, 18-stage handoff, Workbench, decision trace,
provenance index, runtime lock, and allowlisted
`reproducibility/candidate_analysis.json` artifact. Persisted results are
recomputed and fail closed when ranking inputs, component values, aggregates,
ranks, ties, normalized values, analysis identity or result-integrity values
are forged.

## Research and clinical safety boundaries

Every v0.37 result remains research use only and requires human expert review.
The release preserves all of these boundaries:

- `research_use_only=true`;
- `human_review_required=true`;
- `draft_not_clinically_approved=true`;
- no autonomous diagnosis;
- no treatment recommendation;
- no autonomous test ordering;
- no final ACMG classification;
- no clinical sign-out;
- no external LLM, annotation-service, database, network or tool call;
- no unsupported raw-read, CNV, mitochondrial, repeat or mosaic calling;
- no ancestry, caste, community, religion, ethnicity or identity inference;
- no relationship inference from omitted family records;
- candidate ranking is explainable prioritization for review, not a clinical
  conclusion.

## Acceptance finding closure

The final independent acceptance review returned `ACCEPT` with no P0, P1, P2
or P3 findings. The previously identified blockers are closed without
altering the accepted product during release preparation:

- compound identity and source-allele binding;
- same-gene and phase-family rules;
- strict finite unit-bounded frequency validation on every path;
- deterministic recomputation and forgery rejection for raw values, weighted
  contributions, weights, aggregates, ranks, ties and normalized values;
- stale replay protection, persisted integrity validation, safety flags and
  provenance integration.

## Accepted deterministic identities

The canonical synthetic v0.37 demo produces the following exact identities:

| Identity | SHA-256 |
|---|---|
| v0.36 package identity | `da0dcd7422c2af062a47ec5949a32fc80eb5da7cb54a2b9a66d535a430c49810` |
| v0.36 manifest identity | `2071c8fcb3ea17b10ff8d3c909c9a3fb3b077e0d171ab0ea3ff66acc48a5ce05` |
| phenotype snapshot identity | `22891cc88f71bbd98c686c8af6636bd0c4c635df2276e3e5817d5f0561a36ac5` |
| family snapshot identity | `c0efb2a81188d5fdf6302ba0361c68dde021d5fe0b78c298cb2ce2ac4a50e9fd` |
| assay/coverage identity | `6bcc6ec3fd2d5fae1ce772432e3654aaa5b530d1e4407a5edc87aa7b1395c482` |
| evidence-input identity | `f78bcf9c40218d2a2efc43d72a3319430c3d731cf0c3cb897d31bceaf8c685f8` |
| ranking-input identity | `282c008a51ebb286141ed1fb614ebfcb3e54eff32087bddc598fbe803a85274c` |
| ranking-output identity | `f9aa7575fbc6c2f0087ed3970019375c2de7143d234684eec0ca3805a15cf56d` |
| analysis identity | `3869c18397d8a9b6e84c1ba10fbeadbb57185878e6752987b28e98caf39f3068` |
| result-integrity identity | `6bef1037bac4d0949d45d2c810b59c0280fcf0d24e75ef3b4b75259d622f32a9` |

The demo has 4 ranked candidates and 2 excluded candidates. Compound members
are `candidate-v037-2ce0a1c76d0b8293b384` and
`candidate-v037-3a5d83c0d8322e941a40`; the pair state is `phase_unknown` and
the pair identity is `compound-pair-93b2d0865e98eb708c14`. The deterministic
CLI output is 4446 UTF-8 bytes with SHA-256
`c0ee09fc0b275ff87e27da252802f1fd70f0b9973d4525bf7df93bf49b2efe0a`.

## Final validation record

Validation uses the existing environment and does not install or update
dependencies. The final release gate must reproduce these results:

| Check | Exact command or probe | Result |
|---|---|---|
| Focused v0.37 suite | `python -m pytest backend/tests/test_candidate_analysis_v037.py -q` | `53 passed, 54 warnings` |
| Complete backend suite | `python -m pytest backend` | `1008 passed, 164 warnings` |
| Pre-tar validation | `python scripts/pre_tar_check.py` | `1008 passed, 164 warnings; PRE_TAR_CHECK_PASSED` |
| v0.35 CLI compatibility | `python -B -m app.insilicopop.cli v035-demo --fixture ..\\examples\\insilicopop_demo\\canonical_v035_case.json` from `backend` | exit code `0` |
| v0.36 CLI compatibility | `python -B -m app.insilicopop.cli v036-demo --fixture ..\\examples\\insilicopop_demo\\canonical_v036_result_package.json` from `backend` | exit code `0` |
| Deterministic v0.37 demo | `python -B -m app.insilicopop.cli v037-demo --fixture ..\\examples\\insilicopop_demo\\canonical_v037_candidate_analysis.json` from `backend`, run twice | two exit code `0` runs; byte-identical; 4446 bytes; `c0ee09fc0b275ff87e27da252802f1fd70f0b9973d4525bf7df93bf49b2efe0a` |
| Workbench JS/rendering | focused v0.37 suite, including isolated renderer/accessibility/integrity probes | passed |
| Bundle width | canonical builder probe | `10` |
| Handoff navigator | canonical handoff probe | `18` stages |
| Whitespace/error check | `git diff --check` | passed |
| Production safety scan | source isolation/import scan over v0.37 production files | passed; no new subprocess or network path |
| Raw package-byte serialization | source and persisted-model audit | passed; no raw package-byte field is serialized |

The literal command in the acceptance brief names the fixture as
`examples/...` after changing into `backend`. This repository stores the
fixture at the repository root, so the equivalent correct relative path is
`..\\examples\\...`; the product and result are unchanged.

The direct protected source checkout cannot create legacy generated-output
directories under `backend/app/generated` in this validation environment.
The complete suite, pre-tar validation, compatibility checks and deterministic
demo were therefore reproduced in the fresh writable validation copy
`C:\\Users\\khanf\\OneDrive\\Documents\\Insillico OS\\_v037_precommit_validation_20260822`,
built from the exact baseline Git tree plus the accepted v0.37 files and
authorized metadata. This is an environment permission limitation, not a
product or test failure.

## Reconstruction procedure and archive policy

1. Stage only the 20 accepted v0.37 files and the two authorized release
   metadata files by explicit path, after rechecking the initial source
   hashes and staged diff.
2. Commit with the established release identity and message
   `release: freeze InSilicoPop v0.37 explainable candidate and family analysis`.
3. Before tagging, construct a candidate archive from that commit using the
   established deterministic method: `git archive --format=tar.gz` over the
   commit tree, with no Git metadata and no working-tree files.
4. Extract the candidate archive into a fresh directory outside the
   repository. Verify the exact tracked inventory and SHA-256 values, then
   reproduce the focused suite, complete regression with the external fixture
   copies, pre-tar check, compatibility probes, deterministic demo, safety
   checks, bundle width and navigator checks.
5. Only after candidate reconstruction passes, create the single annotated
   local tag `v0.37` with annotation
   `InSilicoPop v0.37 — Explainable Candidate and Family Analysis`.
6. Construct the official archive from the frozen `v0.37` tag, create its
   SHA-256 sidecar, and extract it into a second fresh directory separate from
   the candidate reconstruction. Independently repeat the required checks
   and verify that both reconstructions represent the same tagged source.

The product archive contains only the committed tagged source tree. It
excludes `.git` metadata, credentials, caches, environments, transient or
generated outputs, all historical release archives, external companion
fixtures, the unrelated PDF and PPTX, and every other untracked user file.
Generated release archives and their sidecars remain outside Git tracking.

## External historical-fixture limitation

The complete legacy regression uses the already available verified v0.25–v0.28
archives listed in `RELEASE_FIXTURES_v0.37.md`. They must remain at the exact
repository-root paths during regression. They are external regression
fixtures, not v0.37 product inputs, are not staged, and are not included in
either reconstruction or the official archive.

## Remote and future-release boundary

No remote reference will be modified. No fetch, pull, merge, rebase, force
operation, GitHub release or remote publication is authorized. No v0.38
branch, tag, commit or implementation exists or will be created during this
release process.
