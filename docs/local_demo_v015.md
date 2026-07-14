# Local Demo v0.15

This demo pack is for a local researcher-facing evaluation of the existing backend. It does not add a frontend, authentication, a database, cloud mode, or SaaS behavior.

## Setup

Use PowerShell from the active repo:

```powershell
cd "C:\dev\Insillico OS"
$env:TEMP = "C:\dev\pytest-tmp"
$env:TMP = "C:\dev\pytest-tmp"
```

Validate the backend:

```powershell
python -m pytest backend
python scripts/pre_tar_check.py
```

Expected baseline:

```text
155 passed, 66 warnings
PRE_TAR_CHECK_PASSED
```

## Scenario 1: Insufficient inputs

Goal:

```text
Run a population structure analysis, but no files are provided.
```

Safe CLI demo:

```powershell
cd "C:\dev\Insillico OS\backend"
$env:TEMP = "C:\dev\pytest-tmp"
$env:TMP = "C:\dev\pytest-tmp"
python -m app.insilicopop.cli agent-run `
  --goal "Run a population structure analysis, but no files are provided" `
  --llm-provider mock
```

Expected behavior:

- `workflow_family = insufficient_inputs`
- Missing inputs are clearly listed.
- No tools execute.
- Human review is required.

## Scenario 2: Results-only audit

Goal:

```text
Audit existing PCA/ADMIXTURE output claims for safety and reproducibility.
```

Safe CLI demo using existing small result examples:

```powershell
cd "C:\dev\Insillico OS\backend"
$env:TEMP = "C:\dev\pytest-tmp"
$env:TMP = "C:\dev\pytest-tmp"
python -m app.insilicopop.cli agent-run `
  --goal "Audit existing PCA and ADMIXTURE output claims for safety and reproducibility" `
  --metadata examples/indian_metadata.csv `
  --pca examples/pca_results.csv `
  --admixture examples/admixture_cv_errors.csv `
  --llm-provider mock
```

Expected behavior:

- `workflow_family = results_only_audit`
- Claims are audited conservatively.
- Unsupported identity, ancestry, caste, religion, and community claims are blocked.
- Human review is required.

## Scenario 3: VCF population structure dry run

Goal:

```text
Plan a PCA/ADMIXTURE population structure workflow from a VCF.
```

For a local demo, use a placeholder inventory file rather than real genomic data:

```powershell
cd "C:\dev\Insillico OS\backend"
$env:TEMP = "C:\dev\pytest-tmp"
$env:TMP = "C:\dev\pytest-tmp"
New-Item -ItemType Directory -Force -Path "C:\dev\pytest-tmp\insilicopop_demo_inventory" | Out-Null
Set-Content -Path "C:\dev\pytest-tmp\insilicopop_demo_inventory\cohort.vcf.gz" -Value "inventory placeholder only"
python -m app.insilicopop.cli agent-run `
  --goal "Plan a PCA and ADMIXTURE population structure workflow from a VCF" `
  --metadata examples/indian_metadata.csv `
  --vcf "C:\dev\pytest-tmp\insilicopop_demo_inventory\cohort.vcf.gz" `
  --llm-provider mock
```

Expected behavior:

- `workflow_family = vcf_population_structure`
- VCF is inventoried only.
- Dry-run command previews are generated.
- No PLINK, ADMIXTURE, smartpca, vcftools, or other genomics tool executes.
- A reproducibility bundle is generated.

## Scenario 4: Hard-called SNP workflow

Goal:

```text
Plan population genetics QC and PCA from hard-called SNP data.
```

Safe placeholder-file demo:

```powershell
cd "C:\dev\Insillico OS\backend"
$env:TEMP = "C:\dev\pytest-tmp"
$env:TMP = "C:\dev\pytest-tmp"
New-Item -ItemType Directory -Force -Path "C:\dev\pytest-tmp\insilicopop_demo_inventory" | Out-Null
Set-Content -Path "C:\dev\pytest-tmp\insilicopop_demo_inventory\cohort.bed" -Value "inventory placeholder only"
Set-Content -Path "C:\dev\pytest-tmp\insilicopop_demo_inventory\cohort.bim" -Value "inventory placeholder only"
Set-Content -Path "C:\dev\pytest-tmp\insilicopop_demo_inventory\cohort.fam" -Value "inventory placeholder only"
python -m app.insilicopop.cli agent-run `
  --goal "Plan population genetics QC and PCA from hard-called SNP data" `
  --metadata examples/indian_metadata.csv `
  --plink-bed "C:\dev\pytest-tmp\insilicopop_demo_inventory\cohort.bed" `
  --plink-bim "C:\dev\pytest-tmp\insilicopop_demo_inventory\cohort.bim" `
  --plink-fam "C:\dev\pytest-tmp\insilicopop_demo_inventory\cohort.fam" `
  --llm-provider mock
```

Expected behavior:

- `workflow_family = hard_called_snp`
- PLINK-like inputs are inventoried only.
- Dry-run commands are previews only.
- Scientific validity notes are included.

## Scenario 5: Low-depth genotype-likelihood workflow

Goal:

```text
Plan population structure analysis for low-depth sequencing data.
```

Safe placeholder-file demo:

```powershell
cd "C:\dev\Insillico OS\backend"
$env:TEMP = "C:\dev\pytest-tmp"
$env:TMP = "C:\dev\pytest-tmp"
New-Item -ItemType Directory -Force -Path "C:\dev\pytest-tmp\insilicopop_demo_inventory" | Out-Null
Set-Content -Path "C:\dev\pytest-tmp\insilicopop_demo_inventory\sample.cram" -Value "inventory placeholder only"
python -m app.insilicopop.cli agent-run `
  --goal "Plan population structure analysis for low-depth sequencing data using genotype likelihoods" `
  --metadata examples/indian_metadata.csv `
  --cram "C:\dev\pytest-tmp\insilicopop_demo_inventory\sample.cram" `
  --llm-provider mock
```

Expected behavior:

- `workflow_family = genotype_likelihood_low_depth`
- ANGSD/PCAngsd/NGSadmix-style paths may be described as dry-run planning only.
- No tools execute.
- Limitations and missing dependencies are clear.

## Inspecting generated artifacts

After a CLI run, note the printed `run_id` and `generated_report` path.

Open:

```text
backend/app/generated/agents/{run_id}/final_report.md
backend/app/generated/agents/{run_id}/workflow_selection.json
backend/app/generated/agents/{run_id}/reproducibility/selected_recipe.json
backend/app/generated/agents/{run_id}/reproducibility/evidence_retrieval.json
backend/app/generated/agents/{run_id}/reproducibility/orchestration_trace.json
backend/app/generated/agents/{run_id}/reproducibility/clinical_case_intake.json  # clinical intake runs only
backend/app/generated/agents/{run_id}/reproducibility/phenotype_hpo_curation.json  # explicit phenotype curation only
backend/app/generated/agents/{run_id}/reproducibility/pedigree_inheritance_audit.json  # explicit v0.29 audit only
backend/app/generated/agents/{run_id}/reproducibility/runtime_lock.json
backend/app/generated/agents/{run_id}/reproducibility/checksums.sha256
```

The report is researcher-facing. The reproducibility bundle is generated-artifact provenance, not a checksum of raw genomic inputs.

v0.19 note: local agent runs now surface the selected deterministic dry-run recipe preview in the final report, reproducibility bundle, and workbench run detail. InSilicoPop selected a deterministic dry-run recipe preview; it did not run the population-genetics workflow, execute genomics tools, or parse raw genomic files.

v0.20 note: local agent runs now use the selected recipe's dry-run steps and command preview templates to render clearer recipe-aware command previews. These previews use placeholders, remain commented out, do not parse raw genomic inputs, do not execute external genomics tools, and require human expert review before any real-world command use.

v0.21 note: local agent runs now generate a recipe-aware claim audit in the final report, workbench run detail, and `reproducibility/claim_audit.json`. InSilicoPop surfaces blocked interpretation categories and required caveats; it does not determine ancestry, disease risk, caste, community, religion, treatment meaning, genetic purity, or identity.

v0.22 note: results-only audit runs now generate `reproducibility/results_audit.json` with schema-only records for declared existing result artifacts and missing context. InSilicoPop audits declared result artifacts and missing context; it does not parse raw genomic files, deeply parse result files, execute tools, or interpret PCA/ADMIXTURE/PLINK outputs as biological conclusions.

v0.23 note: local agent runs now generate `reproducibility/data_governance_audit.json` with declared research-use scope, dataset access model, consent/DUA compatibility, credential model, secondary-use, cross-border/export, and human-review caveats. This audit is not legal compliance verification and does not replace institutional ethics committee, data access committee, PI, clinician, data privacy officer, or legal review.

v0.24 note: local agent runs now generate `reproducibility/metadata_registry_audit.json` with declared metadata completeness checks for the population-genetics and clinical-genetics-research-curation lanes. v0.24 also adds a local-only evidence scaffold for internal guidance snippets; it does not perform online retrieval, call external LLMs, parse raw genomic files, make final ACMG classifications, diagnose, or recommend treatment.

v0.25 note: local agent runs now generate `reproducibility/evidence_retrieval.json` with a source-grounded evidence retrieval preview. Retrieval order is safety-first deterministic keyword matching, local guidance keyword matching, optional local vector retrieval when explicitly available, then merge/deduplication. Chroma and LangChain are optional local adapters; if unavailable, the system falls back to deterministic internal keyword retrieval. It does not call external databases/APIs, ingest raw genomic files, produce final biological interpretation, diagnose, recommend treatment, or classify ACMG.

v0.26 note: local agent runs now generate `reproducibility/orchestration_trace.json` and a `Controlled Orchestration Preview` report section. The trace records allowlisted node declarations/execution summaries, backend/fallback status, optional LangGraph availability, blocked nodes, and safety flags only. It does not add autonomous tool execution, external LLM/API calls, raw genomic parsing, uncontrolled debate, diagnosis, treatment recommendation, final ACMG classification, consumer ancestry, caste/community/religion, purity, or final biological interpretation.

v0.27 note: supplying an explicit structured `clinical_case_intake` JSON declaration selects a deterministic clinical-genetics research-curation intake lane. The workbench displays bounded counts, review status, validation warnings, missing information, and policy blocks and writes `reproducibility/clinical_case_intake.json`. No HPO extraction, inheritance calculation, segregation analysis, variant normalization, clinical retrieval, diagnosis, treatment recommendation, final classification, sign-out, or patient-facing return is performed.

v0.28 note: optional `phenotype_curation.snippets` inside that structured declaration enable deterministic matching against a small bundled HPO registry. The workbench and report display bounded suggestion, support-span, negation, contradiction, review, and promotion summaries. Complete snippets are not copied into the v0.28 artifact or ordinary outputs. Every suggestion requires explicit human review; only confirmed candidates or complete validated modifications can be promoted. No fuzzy NLP, ontology expansion, disease interpretation, external call, retrieval, LLM, command execution, or raw genomic parsing is performed.

v0.29 note: optional `pedigree_inheritance_audit` input inside the same top-level v0.27 declaration enables a bounded deterministic audit of explicit pseudonymous members, biological-parent edges, exact candidate observations, supplied inheritance hypotheses, and phase records. The Workbench and report display only counts, hypothesis types, bounded statuses, issue codes, transmission counts, and review requirements. The audit does not establish inheritance or family relationships, infer missing records, normalize variants or genes, calculate recurrence risk or segregation strength, call retrieval or external services, execute tools, or parse raw genomic files.

## Local workbench API inspection

Start the backend if you want to inspect runs through the local API:

```powershell
cd "C:\dev\Insillico OS\backend"
$env:TEMP = "C:\dev\pytest-tmp"
$env:TMP = "C:\dev\pytest-tmp"
python -m uvicorn app.main:app --reload
```

Then inspect generated runs:

```text
GET http://127.0.0.1:8000/insilicopop/agent/runs
GET http://127.0.0.1:8000/insilicopop/agent/runs/{run_id}
GET http://127.0.0.1:8000/insilicopop/agent/runs/{run_id}/report
GET http://127.0.0.1:8000/insilicopop/agent/runs/{run_id}/workflow-selection
GET http://127.0.0.1:8000/insilicopop/agent/runs/{run_id}/reproducibility
```

These endpoints read allowlisted generated artifacts only.

## Tiny localhost workbench UI

v0.16 adds a small local HTML workbench shell over the same API. v0.17 hardens that shell with clearer status fields, safer artifact viewing, better visible errors, and explicit human-review copy. v0.19 adds selected recipe preview metadata to local run details. v0.20 shows recipe-aware command preview counts and selected recipe context beside the preview JSON. v0.21 shows recipe-aware claim audit summaries. v0.22 shows results-only audit summaries when present. v0.23 shows data governance audit summaries and accepts an optional declared governance-scope JSON field. v0.24 shows metadata registry audit summaries and accepts an optional metadata-registry JSON field. v0.25 shows retrieval mode, snippet count, source IDs, warnings/caveats, and local-only status. v0.26 shows controlled orchestration backend, fallback, executed nodes, blocked nodes, and safety flags. It is not a frontend product, SaaS mode, legal compliance tool, clinical interface, autonomous agent interface, or online RAG interface.

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

The page can start a mock dry-run agent run, display workflow selection, planned actions, blocked actions, command previews, final report text, reproducibility bundle status, run history, and allowlisted generated artifacts. Artifact contents are displayed as plain text/JSON rather than executed as HTML.
