# Sample CLI Commands

All commands are Windows-friendly PowerShell examples. They use the mock provider and do not execute external genomics tools.

Start from the active repo:

```powershell
cd "C:\dev\Insillico OS"
$env:TEMP = "C:\dev\pytest-tmp"
$env:TMP = "C:\dev\pytest-tmp"
```

## Validate

```powershell
python -m pytest backend
python scripts/pre_tar_check.py
```

## Insufficient inputs

```powershell
cd "C:\dev\Insillico OS\backend"
python -m app.insilicopop.cli agent-run `
  --goal "Run a population structure analysis, but no files are provided" `
  --llm-provider mock
```

## Results-only audit

```powershell
cd "C:\dev\Insillico OS\backend"
python -m app.insilicopop.cli agent-run `
  --goal "Audit existing PCA and ADMIXTURE output claims for safety and reproducibility" `
  --metadata examples/indian_metadata.csv `
  --pca examples/pca_results.csv `
  --admixture examples/admixture_cv_errors.csv `
  --llm-provider mock
```

## VCF population structure dry run

This uses a placeholder file for inventory only. It is not real genomic data.

```powershell
cd "C:\dev\Insillico OS\backend"
New-Item -ItemType Directory -Force -Path "C:\dev\pytest-tmp\insilicopop_demo_inventory" | Out-Null
Set-Content -Path "C:\dev\pytest-tmp\insilicopop_demo_inventory\cohort.vcf.gz" -Value "inventory placeholder only"
python -m app.insilicopop.cli agent-run `
  --goal "Plan a PCA and ADMIXTURE population structure workflow from a VCF" `
  --metadata examples/indian_metadata.csv `
  --vcf "C:\dev\pytest-tmp\insilicopop_demo_inventory\cohort.vcf.gz" `
  --llm-provider mock
```

## Hard-called SNP dry run

These are placeholder files for inventory only. They are not real PLINK files.

```powershell
cd "C:\dev\Insillico OS\backend"
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

## Low-depth genotype-likelihood dry run

This uses a placeholder file for inventory only. It is not real CRAM data.

```powershell
cd "C:\dev\Insillico OS\backend"
New-Item -ItemType Directory -Force -Path "C:\dev\pytest-tmp\insilicopop_demo_inventory" | Out-Null
Set-Content -Path "C:\dev\pytest-tmp\insilicopop_demo_inventory\sample.cram" -Value "inventory placeholder only"
python -m app.insilicopop.cli agent-run `
  --goal "Plan population structure analysis for low-depth sequencing data using genotype likelihoods" `
  --metadata examples/indian_metadata.csv `
  --cram "C:\dev\pytest-tmp\insilicopop_demo_inventory\sample.cram" `
  --llm-provider mock
```

## Inspect outputs

Use the printed `run_id`.

```powershell
Get-Content "C:\dev\Insillico OS\backend\app\generated\agents\{run_id}\final_report.md"
Get-Content "C:\dev\Insillico OS\backend\app\generated\agents\{run_id}\workflow_selection.json"
Get-Content "C:\dev\Insillico OS\backend\app\generated\agents\{run_id}\reproducibility\runtime_lock.json"
```
