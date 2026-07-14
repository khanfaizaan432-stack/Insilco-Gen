# InSilicoPop Demo Examples

This folder contains v0.15 local demo notes for the existing backend.

These examples are intentionally documentation-only. They do not add a script that executes genomics tools, calls external LLMs, or requires real genomic data.

Use them with:

```powershell
cd "C:\dev\Insillico OS"
$env:TEMP = "C:\dev\pytest-tmp"
$env:TMP = "C:\dev\pytest-tmp"
```

Files:

- `sample_goals.md`: researcher goals and expected workflow-family behavior.
- `sample_cli_commands.md`: safe mock-provider CLI demos.
- `sample_api_requests.md`: local workbench API and agent-run request examples.

Demo principles:

- `mock` provider by default.
- `external_llm_called=false` by default.
- `external_tools_executed=false`.
- raw VCF/BAM/CRAM/PLINK-like files are inventory-only.
- generated command previews are dry-run only.
- human review is required.

For full context, see:

- `docs/insilicopop_overview.md`
- `docs/local_demo_v015.md`
- `docs/safety_guardrails.md`
- `docs/why_not_freeform_chatgpt.md`
