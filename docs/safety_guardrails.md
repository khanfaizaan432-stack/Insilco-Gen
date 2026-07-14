# Safety Guardrails

InSilicoPop is built around conservative population genetics workflow support.

It must not be treated as:

- diagnosis software
- treatment recommendation software
- a clinical genetics product
- a consumer ancestry app
- a caste, religion, or community identity inference system
- a public SaaS product
- a fully automated geneticist

## Execution guardrails

The backend generates dry-run command previews only.

It must not execute:

- PLINK
- ADMIXTURE
- smartpca
- EIGENSOFT
- vcftools
- ANGSD
- PCAngsd
- NGSadmix
- realSFS
- VEP
- ANNOVAR
- SnpEff
- ClinVar pipelines
- other external genomics tools

Command previews should remain inspectable and non-executing.

## Data guardrails

Raw genomic files are inventory-only at this layer.

Do not parse raw:

- VCF
- BAM
- CRAM
- PLINK BED/BIM/FAM
- PGEN/PVAR/PSAM
- PED/MAP

Do not checksum raw genomic files for the reproducibility bundle.

The bundle records generated artifacts and runtime context. It does not make raw genomic data safe to expose.

## LLM guardrails

The default LLM provider is `mock`.

Default run metadata should remain:

```json
{
  "llm_provider": "mock",
  "external_llm_called": false,
  "external_tools_executed": false
}
```

OpenAI-compatible BYOK support is opt-in. Tests and local demo behavior must not require API keys or network access.

## Interpretation guardrails

Unsupported claims are blocked or caveated.

Rules of thumb:

- ADMIXTURE components must not be equated with literal ancestry.
- PCA clusters must not be interpreted as caste, religion, or community identity.
- ROH must not be claimed to prove endogamy without caveats.
- FST and selection scans must not be claimed to prove selection without adequate controls.
- Population labels and metadata quality must be inspected before interpretation.
- Tiny groups, missing metadata, and severe imbalance reduce reliability.

## Blocked claim categories

InSilicoPop should block or warn on:

- clinical diagnosis
- treatment recommendation
- consumer ancestry conclusions
- caste inference
- religion inference
- community identity inference
- genetic purity claims
- superiority claims
- unsupported selection claims
- unsupported endogamy claims

## Human review

Human review is mandatory.

The backend can help organize workflow planning, expose missing inputs, flag unsupported claims, and write reproducibility artifacts. It cannot decide that a genetic interpretation is true, clinically actionable, or socially meaningful.
