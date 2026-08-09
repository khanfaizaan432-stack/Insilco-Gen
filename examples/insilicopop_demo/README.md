# InSilicoPop Demo Examples

This folder contains local demo notes for the existing backend, including the v0.35 structured human-review handoff.

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
- `canonical_v035_case.json`: deterministic synthetic Indian rare-disease case fixture.
- `expected_v035_demo_output.json`: expected output for the v0.35 CLI demonstration.

Demo principles:

- `mock` provider by default.
- `external_llm_called=false` by default.
- `external_tools_executed=false`.
- raw VCF/BAM/CRAM/PLINK-like files are inventory-only.
- generated command previews are dry-run only.
- human review is required.
- v0.35 handoff packets remain research-use-only and never imply clinical approval.
- the canonical v0.35 demo records a complete bounded journey through review,
  uncertainty acknowledgement, decision and blocker resolution, readiness,
  and an external handoff event; `draft_not_clinically_approved` remains true.
- artifact manifests distinguish exact persisted-file-byte SHA-256 digests from
  canonical in-memory payload digests.

For full context, see:

- `docs/insilicopop_overview.md`
- `docs/local_demo_v015.md`
- `docs/safety_guardrails.md`
- `docs/why_not_freeform_chatgpt.md`
