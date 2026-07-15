# InSilicoPop v0.30 Release Manifest

## Release identity

- Release: `v0.30`
- Milestone: **Variant Intelligence Foundation**
- Release date: `2026-07-15`
- Baseline version: `v0.29`
- Baseline commit: `5a745fe79d053b780258bc8b66a312ddcc7a4308`
- Reviewed implementation commit: `acb9ef3d35142ac0c2b857508b5d97829087b1e4`
- Final release-manifest commit: `SELF` — the commit containing this manifest and the peeled target of annotated tag `v0.30`

The final release commit is identified symbolically above because a Git commit cannot embed its own final object hash without changing that hash. The authoritative resolved hash is the peeled `v0.30` tag target and is recorded in the release handoff and tag annotation.

## Versioned contracts

- Clinical top-level schema: `0.27`
- Nested variant-intelligence schema: `0.30`
- Variant algorithm: `insilicopop-variant-intelligence-0.30.1`
- Canonical allele format: `insilicopop-canonical-allele-0.30.1`
- Reference registry: `insilicopop-reference-windows-0.30.1`
- Required reproducibility artifact: `reproducibility/variant_intelligence.json`
- Required researcher-report section: `## Variant Intelligence Preview`

## Bounded capability

v0.30 provides deterministic research-curation support for explicitly supplied, structured simple variant classes:

- SNV;
- MNV;
- deletion;
- insertion;
- simple tandem duplication where the exact supplied relationship is `ALT == REF + REF`;
- delins.

Bounded operations include:

- exact supplied-value preservation and deterministic request snapshots;
- bounded schema and context validation;
- explicit coordinate-system conversion;
- authoritative pinned-reference-window identity, digest, bounds, and allele checks;
- minimal allele representation;
- left normalization within the resolved pinned bounded window;
- versioned internal canonical allele generation;
- bounded normalized genomic HGVS and SPDI generation only when the structured allele resolves against the authoritative fixture window;
- deterministic operation hashes, provenance, review findings, and reproducibility output.

Supplied CAIDs may be preserved but are not looked up or fabricated. VRS generation and semantic validation are unavailable. Syntax-only HGVS or SPDI recognition does not establish equivalence or authorize normalized output.

## Reference limitation

The active reference registry is **synthetic and fixture-only**. It exists to demonstrate deterministic architecture and testing. InSilicoPop v0.30 does **not** provide genome-wide human reference normalization. Generated normalized representations apply only when the supplied structured allele resolves against the pinned synthetic fixture window.

Caller-supplied inline sequence, accession, build, contig, or verification booleans are preserved as supplied evidence but are not authoritative. Only the immutable pinned registry can authorize reference-dependent normalization.

## Structured refusal boundaries

v0.30 refuses or leaves unresolved requests involving:

- omitted, `unknown`, or `other` variant classes;
- unsupported structural, CNV, inversion, translocation, repeat-expansion, breakend, fusion, chromosomal, mosaic, somatic, complex mitochondrial, complex rearrangement, pharmacogenomic haplotype, HLA, star-allele, or polygenic-score representations;
- missing or conflicting build, accession, coordinate, allele, candidate, or pinned-reference context;
- reference digest, window-boundary, or allele mismatch;
- incompatible representation fields;
- formatting anomalies that would require silent cleanup;
- raw genomic files;
- arbitrary transcript selection or semantic HGVS interpretation;
- unavailable CAID lookup or VRS generation.

No unsupported, missing, ambiguous, conflicting, or syntax-only input is silently converted into an exact or normalized equivalence claim.

## Research and clinical safety boundary

This release is for **research use only** and requires **human expert review**. It supports clinical-genetics research curation and evidence preparation; it does not provide:

- diagnosis;
- treatment recommendations;
- clinical report sign-out;
- pathogenicity conclusions or final pathogenicity classification;
- final ACMG/AMP classification;
- autonomous transcript relevance conclusions;
- recurrence-risk, penetrance, or segregation-strength conclusions;
- autonomous external tools, network retrieval, or raw-genomic parsing.

Outputs do not establish clinical significance, pathogenicity, causality, diagnosis, treatment relevance, or final transcript relevance.

## Validation record

- v0.30 focused: `102 passed, 38 warnings`
- Full backend: `435 passed, 91 warnings`
- Embedded pre-tar backend: `435 passed, 91 warnings`
- Final pre-tar marker: `PRE_TAR_CHECK_PASSED`
- CLI audit smoke check: passed
- Agent-run smoke check: passed; `external_llm_called=false`, `external_tools_executed=false`
- Memory benchmark smoke check: passed; winner `domain_aware_ultra_compact`
- Agent-memory benchmark smoke check: passed; winner `domain_aware_governed_memory`
- Final inspection verdict: `READY_TO_MERGE_AND_TAG_V0.30`

## Reviewed commit chain

1. `f3eb202acf57814ecaab99f42f11769f948184b2` — initial v0.30 Variant Intelligence Foundation implementation
2. `231a31d2cf5b34ce9dbe40deaf43d0ae32decad4` — normalization-boundary hardening
3. `c66db848d5fa18372f3d25adafb92fcf0ae6aa90` — research-alignment corrections
4. `acb9ef3d35142ac0c2b857508b5d97829087b1e4` — final unresolved-state presentation correction

The annotated `v0.30` tag targets the release commit containing this manifest. Historical archives remain outside Git tracking and are not part of this release commit.
