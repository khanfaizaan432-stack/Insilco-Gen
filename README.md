# InSilicoPop

InSilicoPop is an offline-first AI ResearchOps workbench for population genetics and clinical genetics research workflows.

The current backend supports a controlled local research workflow:

```text
researcher goal + file inventory
-> workflow-family selector
-> dry-run command planning
-> deterministic guardrails
-> reproducibility bundle
-> researcher-facing report
-> local workbench API inspection
-> human final decision
```

Core principle:

```text
LLM proposes.
Deterministic InSilicoPop core verifies.
Unsafe interpretations are blocked.
Human expert makes final decisions.
```

InSilicoPop is not diagnosis software, a treatment recommendation system, a consumer ancestry app, a caste/community/religion inference system, or a public SaaS product.

Permitted research lanes:

- `population_genetics`
- `clinical_genetics_research_curation`

AI may assist with intake, metadata checks, governance audits, evidence retrieval scaffolding, recipe planning, result audits, claim audits, reproducibility bundles, and safe report drafting. Final scientific and clinical decisions remain with qualified humans.

## Current milestone

Completed baseline:

- v0.10 BYOK provider support, with `mock` default and OpenAI-compatible opt-in support.
- v0.11 deterministic workflow-family selector.
- v0.12 reproducibility/provenance bundle.
- v0.13 researcher-facing final report.
- v0.14 local workbench API readiness.
- v0.15 researcher demo documentation pack.
- v0.16 tiny localhost workbench UI skeleton.
- v0.17 workbench UI hardening and polish.
- v0.17.5 prior-art mining and deterministic recipe architecture design.
- v0.18 deterministic population-genetics recipe registry foundation.
- v0.19 deterministic recipe preview surfaced in reports, reproducibility artifacts, and local workbench output.
- v0.20 recipe-aware dry-run command planner refinement.
- v0.21 recipe-aware claim audit refinement.
- v0.22 results-only audit artifact/schema refinement.
- v0.23 data governance auditor.
- v0.24 dual-lane metadata registry audit and local RAG evidence scaffolding.
- v0.25 local evidence retrieval scaffold with optional local Chroma store and LangChain adapter fallback.
- v0.26 controlled orchestration preview with optional LangGraph availability detection and deterministic fallback.
- v0.27 typed, deterministic clinical case intake for research curation, activated only by an explicit structured declaration.
- v0.28 bounded local phenotype/HPO curation proposals with explicit reviewer decisions and deterministic promotion.
- v0.29 bounded deterministic pedigree and supplied-inheritance consistency auditing with mandatory human review.

Supported workflow families today:

- `insufficient_inputs`
- `results_only_audit`
- `vcf_population_structure`
- `hard_called_snp`
- `genotype_likelihood_low_depth`

## Local demo: v0.15 researcher demo pack

Use PowerShell from the active repo:

```powershell
cd "C:\dev\Insillico OS"
$env:TEMP = "C:\dev\pytest-tmp"
$env:TMP = "C:\dev\pytest-tmp"
```

Run validation:

```powershell
python -m pytest backend
python scripts/pre_tar_check.py
```

Run a safe mock local agent example using existing result-output examples:

```powershell
cd "C:\dev\Insillico OS\backend"
$env:TEMP = "C:\dev\pytest-tmp"
$env:TMP = "C:\dev\pytest-tmp"
python -m app.insilicopop.cli agent-run `
  --query "Audit existing PCA and ADMIXTURE claims for safety and reproducibility" `
  --metadata examples/indian_metadata.csv `
  --pca examples/pca_results.csv `
  --admixture examples/admixture_cv_errors.csv `
  --memory-mode compact `
  --llm-provider mock
```

This uses the mock provider by default, does not call an external LLM, and does not execute PLINK, ADMIXTURE, smartpca, vcftools, ANGSD, PCAngsd, NGSadmix, or other genomics tools.

Generated agent artifacts appear under:

```text
backend/app/generated/agents/{run_id}/
```

Important generated files:

- `final_report.md`
- `workflow_selection.json`
- `reproducibility/selected_recipe.json`
- `reproducibility/data_governance_audit.json`
- `reproducibility/metadata_registry_audit.json`
- `reproducibility/evidence_retrieval.json`
- `reproducibility/orchestration_trace.json`
- `reproducibility/clinical_case_intake.json` when structured clinical intake is supplied
- `reproducibility/phenotype_hpo_curation.json` when bounded phenotype snippets are explicitly supplied
- `reproducibility/pedigree_inheritance_audit.json` when an explicit typed v0.29 audit declaration is supplied
- `agent_state.json`
- `agent_trace.json`
- `command_previews.yaml`
- `validated_actions.json`
- `reproducibility/runtime_lock.json`
- `reproducibility/checksums.sha256`

The reproducibility bundle checksums generated artifacts only. Raw VCF/BAM/CRAM/PLINK-style input files remain inventory-only and are not parsed or checksummed.

## Local workbench API

The backend exposes local-workbench-friendly inspection endpoints:

```text
GET /insilicopop/agent/runs
GET /insilicopop/agent/runs/{run_id}
GET /insilicopop/agent/runs/{run_id}/artifacts
GET /insilicopop/agent/runs/{run_id}/artifacts/{artifact_name}
GET /insilicopop/agent/runs/{run_id}/report
GET /insilicopop/agent/runs/{run_id}/workflow-selection
GET /insilicopop/agent/runs/{run_id}/reproducibility
```

Artifact reading is allowlisted and path traversal protected. These endpoints expose generated run artifacts, not arbitrary filesystem files and not raw genomic file contents.

## Tiny localhost workbench UI: v0.16

The v0.16/v0.17 UI is a minimal static page served by FastAPI. It is local-only and intentionally small: no auth, no database, no file storage layer, no frontend build system, and no external network calls beyond the local backend.

Start the backend:

```powershell
cd "C:\dev\Insillico OS\backend"
$env:TEMP = "C:\dev\pytest-tmp"
$env:TMP = "C:\dev\pytest-tmp"
python -m uvicorn app.main:app --reload
```

Open:

```text
http://127.0.0.1:8000/insilicopop/workbench
```

The UI can submit a mock dry-run agent request, display workflow selection, planned actions, blocked actions, dry-run command previews, final report content, reproducibility summary, and allowlisted generated artifacts. Text/path-like inventory fields are converted into tiny placeholder multipart parts for filename inventory only; this does not add raw genomic parsing or real tool execution.

v0.17 hardens the skeleton with clearer run status fields, visible human-review language, friendlier panel-level errors, safer artifact viewing as plain text/JSON, and improved run history metadata.

## Deterministic recipe registry: v0.18

v0.18 introduces the deterministic recipe registry foundation. Recipes are explicit, versioned, source-grounded workflow templates owned by the InSilicoPop core, not hidden LLM behavior.

The bundled v0.18 recipe specs cover:

- `insufficient_inputs_basic`
- `results_only_audit_basic`
- `vcf_population_structure_basic`
- `hard_called_snp_pca_basic`
- `genotype_likelihood_low_depth_basic`

The registry can load and validate recipe metadata internally. All recipes remain dry-run only, raw genomic files are inventory-only, external genomics tools are not executed, and human expert review remains mandatory.

v0.19 surfaces the selected deterministic dry-run recipe preview after the existing workflow-family selector runs. The selected recipe metadata appears in agent state, final reports, `reproducibility/selected_recipe.json`, and local workbench run details. This still does not execute genomics tools, parse raw genomic files, or make clinical/consumer-ancestry/identity claims.

v0.20 uses the selected recipe's `dry_run_steps` and `command_preview_templates` to shape clearer dry-run command previews. The previews use placeholders such as `<declared_vcf>`, `<declared_plink_prefix>`, `<declared_bam_or_cram>`, and `<planned_output_prefix>`; command lines remain commented, non-executing, inventory-only, and require human expert review before any real-world use.

v0.21 adds recipe-aware claim audit artifacts and clearer blocked interpretation reporting. InSilicoPop surfaces blocked interpretation categories and required caveats; it still does not execute genomics tools, parse raw genomic files, or make clinical, consumer ancestry, caste/community/religion, disease-risk, treatment, genetic-purity, or identity-inference claims.

v0.22 adds structured results-only audit artifacts for declared existing population-genetics outputs. InSilicoPop audits declared result artifacts and missing context; it still does not parse raw genomic files, deeply parse result files, execute tools, or make biological, clinical, ancestry, caste/community/religion, purity, superiority, or identity conclusions.

v0.23 adds a deterministic data governance audit artifact for declared research-use scope, dataset access model, consent/DUA compatibility, credential model, secondary-use ambiguity, cross-border/export declarations, and human-review gates. It records `reproducibility/data_governance_audit.json`, but does not verify legal compliance or replace institutional ethics committee, data access committee, PI, clinician, data privacy officer, or legal review.

v0.24 locks InSilicoPop to population genetics research workflows and clinical genetics research curation workflows. It adds `reproducibility/metadata_registry_audit.json` for declared project/sample/sequencing/clinical/population-genetics metadata completeness checks, plus a local-only RAG evidence scaffold for internal guidance snippets. It does not add online retrieval, ChromaDB, LangChain orchestration, external LLM calls, raw genomic parsing, final ACMG classification, diagnosis, or treatment recommendation.

v0.25 makes the retrieval layer visible and testable while keeping it local. It adds `reproducibility/evidence_retrieval.json`, a deterministic safety-first retrieval summary, an optional local Chroma-backed evidence store abstraction, and an optional LangChain retrieval adapter. If Chroma or LangChain is unavailable, InSilicoPop falls back to deterministic internal keyword retrieval. v0.25 does not call external databases/APIs, ingest raw genomic files, make clinical decisions, classify ACMG, recommend treatment, infer consumer ancestry or caste/community/religion, or make final biological interpretations.

v0.26 adds a controlled orchestration preview layer. It records `reproducibility/orchestration_trace.json` with declared allowlisted graph nodes, executed node summaries, blocked nodes, backend/fallback status, optional LangGraph availability, and safety flags. The fallback deterministic graph remains authoritative by default; no autonomous tools, external LLM/API calls, raw genomic parsing, final ACMG classification, diagnosis, treatment recommendation, consumer ancestry, caste/community/religion, purity, or final biological interpretation is added.

v0.27 adds an explicit `clinical_case_intake` lane for typed, redacted clinical-genetics research-curation records. It validates supplied phenotype, candidate-variant, pedigree, provenance, and hypothesis structures and records `reproducibility/clinical_case_intake.json`. It does not extract HPO terms, normalize or classify variants, calculate inheritance or segregation, query clinical sources, diagnose, recommend treatment, sign out reports, or return patient-facing results. Human review is always required.

v0.28 extends only that explicit lane with a small versioned local HPO registry and explainable exact canonical/synonym matching. It records exact support spans, narrow negation/onset/temporal context, typed contradictions, reviewer actions, and reviewer-authorized promoted observations in `reproducibility/phenotype_hpo_curation.json`. Complete snippets are not duplicated into the curation artifact, report, trace, runtime lock, or ordinary API summaries. Suggestions remain proposed, not approved; no ontology expansion, fuzzy NLP, disease association, diagnosis, treatment, final classification, external call, retrieval, or raw genomic parsing is performed.

v0.29 adds an optional `pedigree_inheritance_audit` declaration inside the existing v0.27 clinical intake. It validates explicit pseudonymous members, biological-parent edges, exact candidate observations, supplied inheritance hypotheses, and phase declarations, then writes `reproducibility/pedigree_inheritance_audit.json`. Its `consistent`, `partially_consistent`, `inconsistent`, `cannot_evaluate`, and `missing_evidence` statuses describe only bounded consistency with supplied structured records. It does not establish inheritance, diagnose, classify pathogenicity, calculate recurrence risk or segregation strength, normalize variants or genes, infer omitted relationships, call retrieval or external services, execute tools, or parse raw genomic files.

## Roadmap

- v0.27 Clinical Intake + Case Schema.
- v0.28 Phenotype + HPO Curation.
- v0.29 Pedigree + Inheritance Audit (implemented, not packaged).
- v0.30 ACMG Evidence Suggestion Support.
- v0.31 Evidence Ledger.
- v0.32 Raw-Data Inventory + Header-Only Parsers.
- v0.33 Controlled Local Execution Sandbox.
- v0.34 LIMS/FHIR Integration Layer.
- v0.35 Clinical Decision-Support Validation Framework.

Every roadmap item preserves the core rule: AI automates repeated workflow steps and drafting support, while qualified human experts remain responsible for final scientific or clinical interpretation.

## Why not just ChatGPT?

Free-form ChatGPT can draft plausible genomics workflow plans and interpretations, but those drafts may be unsafe, unreproducible, or scientifically overconfident. InSilicoPop constrains the workflow through deterministic schemas, workflow-family selection, dry-run-only command previews, guardrail validation, generated provenance, reproducibility artifacts, and mandatory human review.

The system does not claim to produce final biological truth. It helps researchers inspect inputs, plan cautious next steps, block unsupported claims, and preserve enough run context for expert review.

## More documentation

- [InSilicoPop Overview](docs/insilicopop_overview.md)
- [Local Demo v0.15](docs/local_demo_v015.md)
- [Safety Guardrails](docs/safety_guardrails.md)
- [Why Not Free-Form ChatGPT](docs/why_not_freeform_chatgpt.md)
- [Prior Art: Agentic Genomics](docs/prior_art_agentic_genomics.md)
- [Recipe Architecture v0.18 Draft](docs/recipe_architecture_v018.md)
- [Model Strategy](docs/model_strategy.md)
- [Demo examples](examples/insilicopop_demo/README.md)
