# InSilicoPop Overview

InSilicoPop is a controlled local research workbench for population genetics workflow planning and auditing.

It starts from a narrow job:

```text
researcher goal + declared files
-> deterministic input inventory
-> workflow-family selection
-> dry-run tool planning
-> deterministic guardrails
-> generated report and reproducibility bundle
-> human expert review
```

The design is intentionally conservative. InSilicoPop should help a geneticist or genomics researcher organize safe work, not replace scientific judgment.

## What problem it solves

Population genetics workflows can produce many plausible-looking outputs: PCA plots, ADMIXTURE components, FST values, ROH summaries, selection-scan tables, and QC reports. It is easy for a free-form assistant or an informal workflow note to overstate what those outputs mean.

InSilicoPop makes the workflow inspectable:

- It records the research goal.
- It inventories supplied files.
- It chooses a workflow family before planning steps.
- It generates dry-run command previews rather than executing tools.
- It validates proposed claims through deterministic guardrails.
- It writes a researcher-facing report.
- It writes a reproducibility bundle for later review.

## Current workflow families

### `insufficient_inputs`

Used when no usable raw genotype, genotype-likelihood, or result-output signal is available.

Expected behavior:

- Missing inputs are listed.
- No external tools are executed.
- No strong scientific claims are made.
- Human review remains required.

### `results_only_audit`

Used when existing output files are supplied, such as PCA, ADMIXTURE, FST, ROH, selection-scan, or PLINK QC summaries.

Expected behavior:

- Available result outputs are parsed and audited where supported.
- Unsupported claims are blocked.
- Identity, ancestry, caste, religion, and community interpretations are not inferred from clusters or components.
- Raw-data execution planning is blocked unless raw inputs are actually present.

### `vcf_population_structure`

Used when VCF-like input is supplied.

Expected behavior:

- The VCF is inventoried only.
- Raw VCF contents are not parsed for this planning layer.
- Dry-run command previews may describe QC, conversion, LD pruning, PCA, ADMIXTURE, and related steps.
- No PLINK, ADMIXTURE, smartpca, vcftools, or other external genomics tool is executed.

### `hard_called_snp`

Used when PLINK-style hard-called SNP inputs are supplied, such as BED/BIM/FAM, PED/MAP, or PGEN/PVAR/PSAM.

Expected behavior:

- PLINK-like files are inventoried only.
- Dry-run command previews remain commented or structured previews.
- Scientific validity notes warn against interpreting PCA, FST, ADMIXTURE, or ROH without appropriate QC and metadata.

### `genotype_likelihood_low_depth`

Used when low-depth sequencing, BAM/CRAM, ancient DNA, ANGSD, PCAngsd, NGSadmix, realSFS, PopGLen, or genotype-likelihood signals are present.

Expected behavior:

- BAM/CRAM inputs are inventoried only.
- Genotype-likelihood methods may be recommended as planning paths.
- No ANGSD, PCAngsd, NGSadmix, realSFS, or related tool is executed.
- Limitations and missing context are made explicit.

## LLM provider behavior

The default provider is `mock`.

Default metadata must remain:

```json
{
  "llm_provider": "mock",
  "external_llm_called": false,
  "external_tools_executed": false
}
```

v0.10 added bring-your-own-key OpenAI-compatible support, but that path is opt-in and is not required for local tests or demos.

## Generated outputs

When an explicit structured `clinical_case_intake` declaration is supplied, the run also writes `reproducibility/clinical_case_intake.json` and a bounded `Clinical Case Intake Preview`. This research-curation intake stores safe identifiers, counts, review states, validation records, and policy blocks without diagnosis, treatment recommendation, final classification, inheritance calculation, variant normalization, external calls, or raw genomic parsing.

When that declaration also contains bounded, explicitly redacted `phenotype_curation.snippets`, v0.28 performs local exact HPO canonical-label and synonym matching. The optional `reproducibility/phenotype_hpo_curation.json` artifact stores snippet metadata and digests, exact matched substrings and offsets, narrow deterministic context records, contradictions, reviewer actions, and promoted-observation references. It does not duplicate complete snippets or invoke retrieval, an LLM, external terminology services, commands, ontology traversal, fuzzy matching, disease associations, diagnosis, treatment, or final classification.

When the same top-level v0.27 declaration contains `pedigree_inheritance_audit.schema_version = "0.29"`, the clinical branch performs a deterministic consistency audit over explicitly supplied pseudonymous members, biological-parent edges, exact candidate observations, inheritance hypotheses, and phase records. The optional `reproducibility/pedigree_inheritance_audit.json` artifact contains bounded IDs, counts, statuses, issue codes, requirements, parent-child transmission summaries, and mandatory review flags. It does not establish inheritance or family relationships, infer omitted records, normalize candidates or genes, calculate clinical or segregation strength, call retrieval or external services, execute commands, or parse raw genomic files.

Each agent run writes generated artifacts under:

```text
backend/app/generated/agents/{run_id}/
```

Important artifacts include:

- `agent_state.json`
- `agent_trace.json`
- `workflow_selection.json`
- `validated_actions.json`
- `command_previews.yaml`
- `blocked_actions.md`
- `failure_scope.md`
- `final_report.md`
- `reproducibility/input_inventory.json`
- `reproducibility/runtime_lock.json`
- `reproducibility/checksums.sha256`

Raw genomic inputs are not included in the reproducibility checksums.

## Human review

Human review is not a decoration. It is the decision point.

InSilicoPop can organize files, propose dry-run steps, flag unsupported claims, and preserve provenance. A human scientist must still decide whether a workflow is appropriate, whether sample metadata is adequate, whether assumptions are justified, and whether any interpretation is scientifically defensible.
