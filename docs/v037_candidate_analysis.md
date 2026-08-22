# InSilicoPop v0.37 Explainable Candidate Analysis

v0.37 is one bounded, reviewable milestone layered on the existing v0.36
controlled result gateway and v0.35 handoff. It provides deterministic
candidate prioritization for research curation. It does not provide a
diagnosis, pathogenicity conclusion, treatment recommendation, final ACMG
classification, clinical sign-out, or autonomous test order.

## Scope and architecture

The v0.37 builder consumes typed records already accepted by the v0.36
gateway, the existing typed phenotype/HPO curation result, the existing
pedigree/inheritance audit result, and explicitly supplied v0.37 context and
evidence. It does not parse raw genomic files, call variants, retrieve
annotations, browse, execute a shell command, or call an external API.

The result is embedded in the existing clinical intake result and `AgentState`
as `candidate_analysis`. The v0.35 bundle width remains ten and the handoff
navigator remains eighteen stages. The candidate-analysis stage points to the
existing intake artifact plus the specialist workspace when v0.37 data is
present; legacy specialist-only runs keep their prior manifest shape.

## Public contracts

`CandidateAnalysisRequest` is the typed input contract. It contains:

- versioned ranking-rule and weight identifiers;
- candidate contexts bound to v0.36 `source_record_id` values;
- supplied HPO context and pinned relation records;
- supporting, contradicting, missing, or unresolved evidence with source references;
- optional family-member-to-sample bindings, supplied phase, and supplied de novo context;
- optional expected package, phenotype, family, and assay/coverage identities for stale-input detection.

Candidate contexts are not identity authorities. The builder derives a
domain-separated canonical candidate ID from a frozen source-binding payload
containing the v0.36 gateway record ID and underlying source-record key,
package/version and package/manifest identities, invocation identity, source
hash/file, coordinates, REF/ALT, ALT index, source gene/transcript when
present, and the v0.37 schema version. Arbitrary aliases, invented gene or
transcript values, altered coordinates, and source-hash mismatches are
retained only as `invalid_source_binding` exclusions.

`CandidateAnalysisResult` is a deeply immutable Pydantic contract. Nested
collections are tuples, extra fields are rejected, and the JSON representation
uses ordinary arrays. It includes:

- `ranked_candidates`, each with a stable identity, source record identity,
  phenotype, inheritance, frequency, consequence, transcript, quality,
  coverage/assay, evidence, missing information, unresolved uncertainty, and
  visible ranking components;
- `excluded_candidates` and `exclusion_trace`, including out-of-scope records;
- a family/segregation summary with observations and explicit missing states;
- a negative/unresolved result that never converts assay or coverage limits into
  disease absence;
- v0.36 package, manifest, phenotype, family, assay, evidence, input, output,
  and analysis identities, plus a result-integrity digest and canonical input
  payload;
- explicit safety flags: research-only, human review required, draft not
  clinically approved, no diagnosis, no final ACMG classification, no external
  API/LLM/tool execution.

The current contract identifiers are:

| Contract | Value |
| --- | --- |
| schema | `0.37` |
| algorithm | `insilicopop-candidate-analysis-0.37.0` |
| ranking rule | `insilicopop-candidate-ranking-0.37.0` |
| ranking weights | `insilicopop-candidate-ranking-weights-0.37.0` |

## Deterministic ranking

The ranking is an explainable weighted sum. Each component records its input,
typed normalized value, state, rule, fixed weight, raw contribution, weighted
contribution, provenance, and explanation. A component can be positive,
negative, neutral, missing, or not assessed. Missing and unresolved components
have no numerical contribution. The immutable v0.37 component-rule registry is
the single calculation path used when building and reloading a result.

| Component | Weight | Bounded input rule |
| --- | ---: | --- |
| phenotype match | 4.0 | exact supplied HPO terms; pinned supplied relations only for related terms |
| phenotype specificity | 1.0 | supplied specificity value only |
| onset compatibility | 0.5 | supplied onset state only |
| inheritance compatibility | 3.0 | existing typed inheritance-audit state |
| segregation | 2.0 | supplied or deterministically supported observations |
| frequency | 2.0 | supplied frequency; `<= 0.01` is a prioritization signal |
| consequence | 2.0 | supplied consequence text only |
| transcript relevance | 1.5 | supplied relevance state only |
| gene-disease validity | 1.5 | supplied established/limited/conflicting state only |
| variant quality | 1.0 | supplied VCF filter/quality fields |
| QC | 0.5 | supplied QC state; warnings remain visible |
| coverage/assay scope | 1.0 | supplied coverage and reportable scope |
| supporting evidence | 1.0 | linked supplied supporting evidence |
| contradicting evidence | 1.0 | linked contradictory evidence is retained and bounded negatively |
| missing information | 0.0 | visible only; never treated as negative evidence |
| unresolved uncertainty | 0.0 | visible only; never treated as negative evidence |

The fixed support threshold is `8.0` and the fixed tie epsilon is `0.000001`.
Callers cannot override either value or the component registry. Candidates are
sorted by score, canonical candidate ID, and source record ID. Ties use
competition ranking: every member of a tie group has `tied=true`, shares the
same rank and `tie_group_id`, and the next group receives the competition rank
after the skipped positions. Candidate-ID order is only a stable presentation
aid, never scientific superiority.

## Phenotype and family boundaries

Exact HPO matching uses supplied present/resolved observations. A related match
is recorded only when the input includes a pinned relation with an ontology
version and source reference. Synonyms, related terms, and ontology expansion
are not retrieved or inferred. Negated supplied observations are shown as
contradictory review context, never as proof that a condition is absent.

The family summary is descriptive. It records singleton, duo, trio, or extended
family shape from supplied member records; it never infers a relationship,
paternity, non-paternity, ancestry, caste, community, religion, or ethnicity.
Deterministic de novo support requires supplied biological-parent relationships,
distinct pedigree roles and sample names, samples present in the v0.36 VCF
header, actual v0.36 sample calls, exact selected-ALT presence, observed GQ at
or above the immutable `20.0` threshold, and package-aligned bindings. Caller
supplied quality flags and thresholds cannot replace observed GQ. Missing or
unavailable samples remain missing/not assessed. Otherwise the result is
`insufficient_information` or `not_assessed`. Phase and compound
heterozygosity require a distinct, source-bound same-gene pair; a caller's
`confirmed_trans` label alone is never promoted to confirmed. X-linked
context, mosaic context, missing relatives, and low-quality members remain
explicit states.

Unordered request collections (candidate contexts, evidence, HPO terms, family
bindings, observations, and source bindings) are canonicalized before input
identity hashing. Ordered presentation collections retain their order.

## Filtering and unresolved output

Only v0.36 SNV and small-indel records are eligible for the ranking calculation.
Symbolic, CNV, structural, mitochondrial, repeat, mosaic, and other unsupported
records are retained with their source identity and an explicit exclusion code.
Other exclusions include outside-reportable-range records, inadequate coverage,
explicit assay exclusions, versioned candidate rules, unavailable adapters, and
stale identities. No record is silently dropped.

The public unresolved summary is builder-controlled and always uses the
bounded wording:

> No sufficiently supported candidate was identified within the supplied analysis scope.

This is a scope-limited unresolved state. It is not a negative clinical result;
coverage gaps, assay blind spots, unavailable adapters, unsupported result
types, missing evidence, and human-review questions remain visible.

## Provenance and replay

Every candidate binds to its v0.36 source record, source-record hash, package
identity, manifest identity, invocation identity, source file, coordinates,
REF/ALT, variant scope, ALT index, and source gene/transcript when present. The
result also records phenotype, family, assay/coverage, evidence-input, ranking
input, ranking output, analysis, and persisted-result integrity identities.
Frequency values accept only strict finite unit-bounded native numeric input;
booleans and numeric strings are rejected at direct, nested, API, JSON, state,
and artifact boundaries. A verified-load path recomputes every raw and
weighted component contribution, fixed weight, aggregate score, ranks, tie
groups, canonical identities, ranking identities, and the integrity digest.
The Workbench fails closed with an integrity error for a tampered agent-state
payload or candidate-analysis artifact. If an expected
identity, rule version, weight version, or package replay state does not match,
the result is `stale` and candidates are excluded pending replay.

The run writes `reproducibility/candidate_analysis.json`, adds a provenance
entry, exposes the identities in `runtime_lock.json`, and records a
`candidate_analysis_completed` event in the decision trace. The artifact is
allowlisted by the Workbench API and is reloadable as the public immutable
contract.

## Workbench and India-aware guardrails

The Workbench displays the ranked table, ties, component arithmetic, evidence,
missing inputs, unresolved questions, family observations, exclusions, source
record IDs, and replay identities. It labels the panel as a deterministic
research-use-only review aid and requires human review.

An Indian-population frequency source can be recorded as a supplied source
label with its version and scope. That label is not an ancestry conclusion and
does not authorize caste, community, religion, ethnicity, identity, or
geographic inference. Frequency absence is never treated as negative evidence.
Laboratory accreditation and access claims remain supplied/unverified unless a
separate trusted channel provides evidence; v0.37 does not create that channel.

## Reproduction

Run the synthetic overlay fixture twice from the backend directory:

```text
python -m app.insilicopop.cli v037-demo
python -m app.insilicopop.cli v037-demo
```

Both outputs must match the checked-in expected summary at
`examples/insilicopop_demo/expected_v037_candidate_analysis_output.json`.
The overlay reuses the frozen v0.36 synthetic package for source bytes and
adds only v0.37 clinical context, evidence, and family declarations. Its
frozen VCF exposes the proband and control samples but no father sample, so the
demo intentionally reports missing father evidence and does not claim
deterministic de novo support.

## Remaining limits

v0.37 is not a variant caller, annotation engine, ontology service, evidence
retriever, ACMG classifier, segregation model, or clinical reporting system.
It cannot establish pathogenicity, causality, penetrance, inheritance, or
clinical utility from ranking alone. It cannot rescue missing, stale, out-of-
scope, poor-quality, or unbound inputs. Independent review is required before
correction, publication, external handoff, or freeze.
