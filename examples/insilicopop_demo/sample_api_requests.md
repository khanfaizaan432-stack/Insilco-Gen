# Sample API Requests

These examples assume the local backend is running:

```powershell
cd "C:\dev\Insillico OS\backend"
$env:TEMP = "C:\dev\pytest-tmp"
$env:TMP = "C:\dev\pytest-tmp"
python -m uvicorn app.main:app --reload
```

The examples use local files and the `mock` provider. They do not call an external LLM and do not execute genomics tools.

## Health check

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/health"
```

## Start a results-only audit run

PowerShell 7 supports `-Form` for multipart form requests:

```powershell
$form = @{
  query = "Audit existing PCA and ADMIXTURE output claims for safety and reproducibility"
  llm_provider = "mock"
  metadata_file = Get-Item "C:\dev\Insillico OS\backend\examples\indian_metadata.csv"
  pca_file = Get-Item "C:\dev\Insillico OS\backend\examples\pca_results.csv"
  admixture_file = Get-Item "C:\dev\Insillico OS\backend\examples\admixture_cv_errors.csv"
}
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/insilicopop/agent/run" -Form $form
```

Expected response fields include:

```text
run_id
workflow_selection
final_state
generated_files
reproducibility_bundle
llm_provider
external_llm_called
external_tools_executed
```

Default safety metadata should remain:

```json
{
  "llm_provider": "mock",
  "external_llm_called": false,
  "external_tools_executed": false
}
```

## Inspect generated runs

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/insilicopop/agent/runs"
```

## Inspect a run

Replace `{run_id}` with the returned run id:

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/insilicopop/agent/runs/{run_id}"
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/insilicopop/agent/runs/{run_id}/artifacts"
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/insilicopop/agent/runs/{run_id}/report"
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/insilicopop/agent/runs/{run_id}/workflow-selection"
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/insilicopop/agent/runs/{run_id}/reproducibility"
```

## Read an allowlisted artifact

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/insilicopop/agent/runs/{run_id}/artifacts/final_report.md"
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/insilicopop/agent/runs/{run_id}/artifacts/reproducibility/runtime_lock.json"
```

The artifact endpoint is allowlisted and path traversal protected. It is not an arbitrary filesystem reader.
