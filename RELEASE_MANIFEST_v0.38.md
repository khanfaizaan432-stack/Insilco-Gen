# InSilicoPop v0.38 Release Manifest

## Release identity

- Release: `v0.38`
- Milestone: **Integrated Evidence and Controlled Tool Workspace**
- Release date: `2026-08-24`
- Previous frozen version: `v0.37`
- Baseline commit: `e4eccee0a4a65cc95449b6872c0c5e855abda37c`
- Baseline branch: `main`
- Final release commit: `SELF` — the commit containing this manifest and the
  peeled target of the annotated `v0.38` tag.
- Planned commit message:
  `release: freeze InSilicoPop v0.38 integrated evidence and tool workspace`
- Planned annotated tag title:
  `InSilicoPop v0.38 — Integrated Evidence and Controlled Tool Workspace`

The commit is identified symbolically because it cannot embed its own object
hash. The peeled annotated tag target is authoritative.

## Frozen scope

v0.38 adds one immutable integrated-analysis workspace over the frozen v0.36
result gateway and v0.37 candidate analysis. It preserves the ten-item bundle,
18-stage navigator, previous schemas and candidate ordering while adding:

- source-bound SNV/small-indel summaries with supplied and normalized allele
  representations kept distinct;
- supplied CNV, mitochondrial and mosaic measurements retained for review;
- deterministic candidate/evidence binding without reranking v0.37;
- controlled PubMed, ClinVar and Ensembl retrieval with fixture replay and
  explicit human authorization for live public retrieval;
- an unavailable-by-default BCFtools adapter and one exact, typed, pinned WSL
  maintenance authorization for the canonical synthetic VCF;
- evidence lifecycle, conflicts, provenance and human-review proposals;
- India-specific NABL, access, affordability, TAT, shipping, IndiGenomes,
  GenomeIndia/IBDC and MoHFW referral context without inference;
- a 12-panel summary-first accessible Workbench surface and checksum-covered
  `reproducibility/integrated_analysis_workspace.json` artifact.

The accepted implementation inventory is the 25 v0.38 source, test,
architecture and fixture paths present in the staged diff, plus these three
release metadata paths:

- `README.md`;
- `RELEASE_MANIFEST_v0.38.md`;
- `RELEASE_FIXTURES_v0.38.md`.

The unrelated PPTX, the untracked v0.37 checksum sidecar, historical archives,
generated runs, caches and environments are excluded.

## Safety boundary

Every workspace remains research-use-only, human-review-required and a draft
not clinically approved. v0.38 does not diagnose, recommend treatment, order
tests, assign a final ACMG/CNV classification, sign out a case, infer ancestry,
caste, community, religion, ethnicity, paternity, family relationships or
sample swaps, or persist raw package/tool/HTTP bytes, credentials or approval
records. The default path performs no external tool, network or LLM call.

## Acceptance finding closure

The final rendered-browser correction pass closes both P1 findings:

1. the integrated SNV projection now uses the canonical v0.36
   `reference_allele`, `alternate_allele` and `filter_status` fields and retains
   supplied/normalized identities; all canonical records render their alleles;
2. long QC/coverage entries are responsively contained; all 12 panels have no
   page-level horizontal overflow at 390×844.

No P0, P1, P2 or P3 product finding remains after correction and revalidation.

## Deterministic identities

Default blocked-workspace replay:

- direct Windows CLI output bytes: `4913`;
- output SHA-256:
  `ef540e587afb365cbec1c8b578604261d89f9508b587530bf5f53f4cc156d765`;
- integrated workspace identity:
  `731a2a3ae9c70c048d546151c153892dd117a68c88b2757ad27a1b141939ee84`;
- final integrity:
  `7168ceae31853c0b780fa66711751f3b6bde46211e4de1befbdbc596e40089aa`.

Explicitly authorized pinned WSL BCFtools replay:

- output bytes: `13795`;
- output SHA-256:
  `bd3c3b47fcb3991dc837ab546f40f9d0a7f8d1d4ec0345479398fe315c9122cf`;
- five completed operations: version, validation, stats, sample names and
  multiallelic decomposition;
- external-tool execution identity:
  `1292c72366ce44bce00b7c54e80e2fbc575d9b6156e7c0ff5729d86655cef469`;
- integrated workspace identity:
  `4e296c095a34733f4ac3ee8fa45053834eb02c1817ec039e68f72833bcc24ba5`;
- final integrity:
  `3e9df76f0634425142deeb884c173ca0c7dae9f3f8d1f1976722a1fd99d6ca3e`.

## Final validation record

| Gate | Result |
|---|---|
| Focused v0.38/Workbench suite | `17 passed, 58 warnings` |
| Complete regression | `1028 passed, 2 expected skips, 170 warnings` |
| Pre-tar validation | `PRE_TAR_CHECK_PASSED` |
| Default deterministic replay | two byte-identical outputs; expected fixture match |
| Pinned WSL BCFtools replay | genuine authorized execution completed; all five operations passed; cleanup removed |
| Workbench JavaScript syntax | passed |
| Rendered browser | Codex in-app browser; 12 tabs/panels; ARIA and keyboard checks passed |
| Responsive browser | 1280×720, 768×1024 and all 12 panels at 390×844 passed without page overflow |
| Integrity fail-closed | persisted tampering withheld by tests and prior rendered acceptance |
| Bundle/navigator compatibility | width `10`; stages `18` |
| Whitespace check | `git diff --check` passed |

The two WSL tests skipped in the ordinary sandboxed complete suite are the
explicit host-runtime tests. Their genuine authorized CLI path was run outside
that filesystem sandbox and passed against the pinned runtime; no installation
or environment mutation occurred.

## Freeze, archive and publication policy

Stage only the 28 intended v0.38/release paths by explicit name. Commit once,
create one annotated `v0.38` tag, and build the official source archive from
that tag with `git archive`. The archive must contain only the tagged tracked
tree and exclude Git metadata, credentials, caches, environments, generated
outputs, historical archives and unrelated user files.

The official asset names are:

- `insilicopop_v0.38_integrated_evidence_tool_workspace.tar.gz`;
- `insilicopop_v0.38_integrated_evidence_tool_workspace.tar.gz.sha256`;
- `RELEASE_FIXTURES_v0.38.md`.

After local reconstruction and checksum verification, push only `main` and
the annotated `v0.38` tag without force, create one final non-prerelease GitHub
release, upload exactly the three assets above, download them afresh, validate
the archive and checksum, and confirm remote branch/tag identities. No v0.39
work is part of this release.
