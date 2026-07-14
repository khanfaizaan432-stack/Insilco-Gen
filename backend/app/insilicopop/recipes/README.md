# InSilicoPop Recipes

This directory contains the deterministic recipe registry foundation. v0.19 surfaces selected recipe previews in agent state, final reports, reproducibility artifacts, and local workbench output. v0.20 uses selected recipe steps and command preview templates to shape commented dry-run command previews. v0.21 uses selected recipe safety metadata to shape deterministic claim-audit output. v0.22 adds schema-only results-audit artifacts for the `results_only_audit` lane. v0.23 adds data-governance audit artifacts for declared research-use scope and human-review gates. v0.24 adds dual-lane metadata registry audit artifacts and local-only RAG evidence scaffolding. v0.25 adds a local evidence retrieval preview artifact with optional Chroma/LangChain adapter scaffolding and deterministic fallback.

Recipes are deterministic, versioned specs for population-genetics workflow planning. They must stay dry-run only until a later milestone explicitly designs sandboxing, allowlists, and human approval for any real execution.

Current files:

- `models.py`: Pydantic models and safety validation for recipe specs.
- `registry.py`: Standard-library JSON loader helpers for the local catalog and specs.
- `catalog.json`: Static recipe catalog.
- `specs/*.json`: First deterministic recipe specs for existing workflow families.
- `recipe_schema_draft.json`: v0.17.5 draft schema retained as architecture reference.

Current invariants:

- LLM output is advisory.
- Deterministic InSilicoPop validation is authoritative.
- Unsafe interpretations are blocked.
- Human expert review is mandatory.
- Raw genomic files are inventory-only.
- Command previews are not executed.
- Tests must not call external LLMs.

v0.18 recipes:

- `insufficient_inputs_basic`
- `results_only_audit_basic`
- `vcf_population_structure_basic`
- `hard_called_snp_pca_basic`
- `genotype_likelihood_low_depth_basic`

v0.19 integration is preview-only: the existing workflow-family selector chooses the workflow family, then the registry attaches the default deterministic dry-run recipe metadata for that family. Recipes are not executed.

v0.20 command preview refinement is still preview-only: recipe-aware previews use inventory placeholders, remain commented out, do not parse raw genomic files, do not execute PLINK/ADMIXTURE/smartpca/vcftools/ANGSD/PCAngsd/NGSadmix, and require human expert review.

v0.21 claim audit refinement is still research-only and non-clinical: InSilicoPop surfaces blocked interpretation categories, unsupported claim categories, required caveats, and human-review flags. It does not determine ancestry, disease risk, caste, community, religion, treatment meaning, genetic purity, or identity.

v0.22 results-only audit refinement is still schema-only: InSilicoPop audits declared result artifacts and missing context, but does not parse raw genomic files, deeply parse result files, execute tools, or interpret PCA/ADMIXTURE/PLINK outputs as biological, clinical, ancestry, caste/community/religion, purity, superiority, or identity conclusions.

v0.23 data governance auditing is declaration-only: InSilicoPop records governance blocks and caveats for dataset access scope, consent/DUA compatibility, credential model, secondary-use ambiguity, cross-border/export declarations, and human-review gates. It does not verify legal compliance or replace institutional ethics committee, data access committee, PI, clinician, data privacy officer, or legal review.

v0.24 metadata registry auditing keeps InSilicoPop locked to population genetics and clinical genetics research curation lanes. It records missing metadata and caveats in `reproducibility/metadata_registry_audit.json`. The local evidence scaffold returns internal guidance snippets only; it does not call the network, call external LLMs, send raw genomic data, diagnose, recommend treatment, or make final ACMG classifications.

v0.25 evidence retrieval remains scaffold-only and source-grounded. It records `reproducibility/evidence_retrieval.json` with retrieval mode, source IDs, snippets, warnings/caveats, and local-only status. Optional Chroma and LangChain adapters must fall back to deterministic keyword retrieval when unavailable. The retrieval layer does not execute recipes, call external APIs, ingest raw genomic files, produce final biological interpretation, diagnose, recommend treatment, classify ACMG, or infer consumer ancestry/caste/community/religion.
