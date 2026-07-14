# InSilicoPop Recipe Architecture Draft for v0.18

This document describes the v0.18 recipe architecture and registry foundation. The v0.18 implementation adds deterministic recipe models, a local JSON catalog, five first recipe specs, and tests for recipe loading and safety invariants. It does not wire recipes into runtime workflow selection, report generation, command preview generation, or tool execution.

Current recipe policy:

```text
Recipes are dry-run only.
LLM output is advisory.
Deterministic recipe validation controls workflow selection, command previews, claim blocking, and report structure.
Human expert review is mandatory.
```

## v0.18 Implementation Status

Implemented in v0.18:

- `backend/app/insilicopop/recipes/models.py`
- `backend/app/insilicopop/recipes/registry.py`
- `backend/app/insilicopop/recipes/catalog.json`
- `backend/app/insilicopop/recipes/specs/*.json`
- `backend/tests/test_recipe_registry_v018.py`

The registry is internally queryable through:

```text
load_recipe_catalog()
load_recipe(recipe_id)
load_all_recipes()
get_recipes_for_workflow_family(workflow_family)
validate_recipe(recipe)
```

v0.19 integrates the registry into user-visible planning output by attaching a selected deterministic dry-run recipe preview after the existing workflow-family selector runs. It surfaces recipe metadata in agent state, `final_report.md`, `reproducibility/selected_recipe.json`, provenance/runtime lock metadata, and local workbench run details. It still does not execute recipes, execute genomics tools, parse raw genomic files, or make clinical/consumer genetics claims.

v0.20 refines command preview rendering so the selected deterministic recipe shapes dry-run previews through `dry_run_steps` and `command_preview_templates`. The rendered previews use inventory placeholders, keep shell lines commented, preserve `external_tools_executed=false` and `raw_genomic_files_parsed=false`, and require human expert review before any real-world command use.

v0.21 adds a recipe-aware claim audit artifact and report section. It makes blocked interpretation categories, unsupported claim categories, required scientific caveats, human-review flags, and the source selected recipe ID explicit. It still does not execute genomics tools, parse raw genomic files, or determine ancestry, disease risk, caste, community, religion, treatment meaning, genetic purity, or identity.

v0.22 adds structured results-only audit artifacts for declared existing population-genetics outputs. It introduces schema-only declared result artifact records and `reproducibility/results_audit.json` for `results_only_audit` runs. It still does not parse raw genomic files, deeply parse result files, execute tools, or interpret PCA/ADMIXTURE/PLINK outputs as biological, clinical, ancestry, caste/community/religion, purity, superiority, or identity conclusions.

v0.23 adds a deterministic data governance audit layer separate from biological claim auditing. It records declared research-use scope, dataset access model, consent/DUA compatibility, credential model, secondary-use ambiguity, cross-border/export declarations, and human-review gates in `reproducibility/data_governance_audit.json`. It does not verify legal compliance or replace institutional ethics committee, data access committee, PI, clinician, data privacy officer, or legal review.

v0.24 locks the product identity to two permitted research lanes: population genetics and clinical genetics research curation. It adds a deterministic metadata registry audit for declared project, sample, sequencing, clinical, and population-genetics metadata completeness, plus local-only RAG evidence scaffolding for internal guidance snippets. It records `reproducibility/metadata_registry_audit.json` and does not add online retrieval, external LLM calls, raw genomic parsing, final ACMG classification, diagnosis, treatment recommendation, or uncontrolled web/API calls.

v0.25 adds a local evidence retrieval layer around that scaffold. Retrieval is ordered safety-first: deterministic safety keyword retrieval, local source-grounded keyword retrieval, optional local Chroma vector retrieval through an optional LangChain adapter, then merge/deduplication. The bundle records `reproducibility/evidence_retrieval.json` with retrieval mode, source IDs, snippets, caveats, and local-only invariants. Chroma and LangChain are optional; missing packages fall back to deterministic keyword retrieval. The layer does not call external databases/APIs, ingest raw genomic files, ingest clinical notes unless explicitly redacted text is supplied later, or make final biological/clinical interpretations.

v0.26 adds controlled orchestration preview metadata around the existing deterministic loop. The bundle records `reproducibility/orchestration_trace.json` with only allowlisted node declarations, executed node summaries, blocked nodes, backend/fallback status, optional LangGraph availability, and safety flags. The deterministic audits remain authoritative; this does not add autonomous tool execution, arbitrary nodes/tools, external LLM/API calls, raw genomic parsing, final ACMG classification, diagnosis, treatment recommendation, consumer ancestry/caste/community/religion inference, purity claims, or final biological interpretation.

## Goals

- Convert repeated workflow-family behavior into versioned deterministic recipe specs.
- Keep scientific workflow structure outside free-form prompts.
- Make input requirements, missing-input behavior, command previews, claim auditing, data governance auditing, metadata registry auditing, local evidence retrieval scaffolding, and reproducibility artifacts testable.
- Preserve existing v0.10-v0.17 behavior: mock default, BYOK opt-in, no external calls in tests, no real genomics execution, no raw genomic parsing, local-only workbench.

## Non-Goals

- Do not implement real PLINK, ADMIXTURE, smartpca, vcftools, ANGSD, PCAngsd, NGSadmix, or other tool execution.
- Do not parse raw VCF, BAM, CRAM, BED/BIM/FAM, PGEN/PVAR/PSAM, PED/MAP, or similar raw genomic contents.
- Do not add clinical, treatment, consumer ancestry, caste/community/religion, genetic-purity, or unsupported population-identity inference.
- Do not add frontend, auth, database, cloud, or SaaS behavior as part of v0.18 recipes.

## Recipe Object

Proposed fields:

```text
recipe_id
version
workflow_family
status
maturity_tier
intent_triggers
declared_input_requirements
missing_input_rules
preflight_checks
dry_run_steps
command_preview_templates
expected_outputs
reproducibility_artifacts
claim_audit_rules
blocked_interpretations
scientific_validity_notes
human_review_checklist
provenance_sources
tests_required
```

### Field Semantics

- `recipe_id`: Stable identifier, for example `population_structure_vcf_dry_run`.
- `version`: Semver-like recipe version independent from app version, for example `0.1.0`.
- `workflow_family`: Must map to an existing deterministic workflow family such as `vcf_population_structure`, `hard_called_snp`, `genotype_likelihood_low_depth`, `results_only_audit`, or `insufficient_inputs`.
- `status`: Lifecycle state such as `draft`, `active`, `deprecated`, or `blocked`.
- `maturity_tier`: One of the controlled tiers below.
- `intent_triggers`: Goal/query cues that make the recipe a candidate. These are hints, not the final authority.
- `declared_input_requirements`: Inventory-only data requirements grouped into required, optional, and mutually exclusive sets.
- `missing_input_rules`: Deterministic behavior when inputs are absent, ambiguous, contradictory, or unsafe.
- `preflight_checks`: Non-parsing checks such as file-name inventory, extension class, paired-file consistency, generated-result allowlists, and unsafe-goal detection.
- `dry_run_steps`: Ordered conceptual workflow steps with no execution side effects.
- `command_preview_templates`: Rendered command strings that remain previews only and must not be passed to a shell.
- `expected_outputs`: Expected generated artifacts or user-supplied result artifacts, with formats, descriptions, and review notes.
- `reproducibility_artifacts`: Files to emit in generated run folders, such as recipe snapshot, workflow selection, command previews, runtime lock, checksums of generated artifacts, and final report.
- `claim_audit_rules`: Deterministic checks that decide which claims can be reported, softened, or blocked.
- `blocked_interpretations`: Safety blocks for diagnosis, treatment, caste/community/religion, genetic purity, consumer ancestry, unsupported selection, unsupported endogamy, and similar claims.
- `scientific_validity_notes`: Limitations and assumptions that must appear in researcher-facing output.
- `human_review_checklist`: Expert review items the final report should surface.
- `provenance_sources`: Source URLs, docs, papers, and license notes used to justify the recipe.
- `tests_required`: Unit and fixture tests needed before increasing maturity.

## Maturity Tiers

- `spec_only`: Design exists. No generated command templates are trusted yet.
- `dry_run_template`: Recipe can produce deterministic dry-run steps and command previews with fixture inputs.
- `guardrail_tested`: Recipe has tests for unsafe claims, missing inputs, forbidden tools, path traversal, and no execution.
- `demo_tested`: Recipe is covered by local demo examples and researcher-facing report checks.
- `execution_ready_later`: Reserved future state. This must still require a separate milestone, sandbox design, explicit allowlists, and human approval before any real execution.

Current v0.18 target should stop at `spec_only`, `dry_run_template`, or `guardrail_tested`.

## Registry Shape

The v0.18 registry is file-backed and deterministic:

```text
backend/app/insilicopop/recipes/
  README.md
  __init__.py
  models.py
  registry.py
  catalog.json
  recipe_schema_draft.json
  specs/
    insufficient_inputs_basic.json
    results_only_audit_basic.json
    vcf_population_structure_basic.json
    hard_called_snp_pca_basic.json
    genotype_likelihood_low_depth_basic.json
```

v0.19 wires this into report/reproducibility/workbench preview only. The existing workflow-family selector remains the source of workflow-family truth, and recipe selection follows that family rather than overriding it. v0.20 adds recipe-aware command preview rendering without adding execution. v0.21 adds recipe-aware claim-audit rendering and `reproducibility/claim_audit.json`. v0.22 adds schema-only results-audit rendering and `reproducibility/results_audit.json` for results-only runs. v0.23 adds data-governance audit rendering and `reproducibility/data_governance_audit.json` for declared research-use scope review. v0.24 adds metadata-registry audit rendering and `reproducibility/metadata_registry_audit.json`. v0.25 adds local evidence retrieval rendering and `reproducibility/evidence_retrieval.json`, while retrieval remains advisory, source-grounded, and offline-only. v0.26 adds controlled orchestration trace rendering and `reproducibility/orchestration_trace.json`, while orchestration remains bounded, summary-only, and fallback-deterministic.

## Deterministic Selection Flow

Recommended v0.18 flow:

```text
research goal + inventory
-> existing workflow-family selector
-> recipe registry candidate lookup by workflow_family
-> deterministic input/preflight checks
-> recipe selection or insufficient-input response
-> dry-run step rendering
-> command preview rendering
-> claim audit
-> final report + reproducibility bundle
```

The LLM may propose intent hints or summarize results, but it must not choose a recipe in a way that bypasses deterministic checks.

## Input Requirement Patterns

Use inventory-only classes rather than parsing raw files:

- `vcf`: VCF or compressed VCF path/name.
- `plink_binary`: BED/BIM/FAM trio path/name inventory.
- `plink2_binary`: PGEN/PVAR/PSAM trio path/name inventory.
- `ped_map`: PED/MAP pair path/name inventory.
- `alignment`: BAM or CRAM path/name inventory.
- `metadata`: Allowed small tabular metadata or already-supported parser output.
- `existing_results`: Generated or user-provided PCA, ADMIXTURE, FST, ROH, selection, and QC summary outputs supported by current parsers.

Missing-input rules should be specific. Example:

```text
If VCF is present but metadata is absent, allow dry-run QC/structure preview but block population-label interpretation.
If PCA result is present without sample metadata, allow technical audit but block group-level population claims.
If BAM/CRAM is present, inventory only and recommend appropriate low-depth workflow family; do not parse or execute.
```

## Command Preview Rules

Command previews must:

- Be plain strings or structured preview objects.
- Include a visible `dry_run_only: true` marker.
- Use placeholder paths where needed.
- Never be passed to shell execution.
- Never install dependencies.
- Never download data.
- Never infer that the command has already succeeded.

Command previews must not:

- Contain command separators for hidden extra actions.
- Read arbitrary paths outside the declared inventory.
- Include credentials, API keys, or network upload destinations.
- Suggest clinical or identity-inference outputs.

## Claim Audit Rules

Every recipe should define claim rules in three classes:

- `allowed_with_review`: cautious technical statements, such as "PCA can be inspected for batch effects after metadata review."
- `soften`: overconfident statements that can be converted to uncertainty-aware language.
- `block`: unsafe or unsupported interpretations that must not appear in final output.

Universal blocks:

- Diagnosis or treatment recommendation.
- Consumer ancestry claim.
- Caste/community/religion inference.
- Genetic purity or superiority claim.
- Unsupported selection claim.
- Unsupported endogamy claim.
- Population labels treated as biological essence.
- Claims based on raw genomic content parsing when no parser was run.
- Claims based on command previews as if execution occurred.

## Provenance and Reproducibility

Each selected recipe should add a recipe snapshot to the generated run bundle:

```text
recipe_selection.json
recipe_snapshot.json
command_previews.yaml
claim_audit.json
final_report.md
reproducibility/runtime_lock.json
reproducibility/checksums.sha256
```

The checksums should continue to cover generated artifacts only unless a later milestone explicitly designs raw-data handling.

## Testing Requirements

For every recipe promoted beyond `spec_only`, require:

- Schema validation test.
- Workflow-family compatibility test.
- Missing-input fixture test.
- Unsafe-claim blocking test.
- Dry-run command preview snapshot test.
- No-execution invariant test.
- No raw genomic parsing invariant test.
- Reproducibility artifact presence test.
- Human-review copy presence test.
- Path traversal and artifact allowlist tests where artifacts are exposed through the workbench API.

## First v0.18 Recipe Candidates

v0.18 implements population-genetics recipes already implied by the current backend:

- `insufficient_inputs_basic`: deterministic missing-input response recipe.
- `results_only_audit_basic`: existing PCA/ADMIXTURE/FST/ROH/selection result review with strong claim blocking.
- `vcf_population_structure_basic`: inventory VCF, metadata, and dry-run previews for QC and population-structure planning.
- `hard_called_snp_pca_basic`: inventory PLINK-style hard-called SNP sets and preview QC/structure workflow.
- `genotype_likelihood_low_depth_basic`: inventory BAM/CRAM or low-depth inputs and preview a low-depth-aware workflow path without execution.

## Next Milestone Recommendation

v0.20 refines recipe-aware dry-run command planner behavior while preserving dry-run-only behavior. It does not implement real execution.

v0.21 refines recipe-aware claim audit behavior. It surfaces blocked interpretation categories and required caveats while preserving dry-run-only, inventory-only, non-clinical, non-consumer-ancestry, non-identity-inference behavior.

v0.22 refines the results-only audit lane. It inventories declared existing result artifacts and missing context without reading raw files, deeply parsing result files, or making biological conclusions.

v0.23 adds data governance auditing. It blocks unsafe declared governance requests such as managed-access human genomic data without scope, shared service account use, re-identification, raw genomic data network upload/export, clinical diagnosis, treatment recommendation, caste/community/religion inference, and genetic purity/superiority claims. Caveats remain declaration-based and require human review.

v0.24 adds metadata registry auditing and local evidence scaffolding. Metadata gaps are caveated for the population-genetics lane and clinical-genetics-research-curation lane; high-risk out-of-scope requests are blocked. The local evidence scaffold uses built-in internal guidance and exact keyword matching only, with `network_called=false`, `external_llm_called=false`, and `raw_genomic_data_sent=false`.

v0.25 adds an optional local Chroma store abstraction and optional LangChain retrieval adapter. Both are scaffolded as local-only infrastructure. When they are not installed or not explicitly available, deterministic keyword retrieval remains the default. Retrieved snippets are provenance context for human review, not clinical decision support or final biological interpretation.

v0.26 adds controlled LangGraph orchestration preview metadata only. LangGraph is optional; if unavailable, the deterministic controlled graph fallback is recorded. Only allowlisted nodes are declared, node records contain input/output summaries only, and no arbitrary tool execution, external calls, raw parsing, diagnosis, treatment, final ACMG classification, consumer ancestry, caste/community/religion, purity, or final interpretation behavior is introduced.
