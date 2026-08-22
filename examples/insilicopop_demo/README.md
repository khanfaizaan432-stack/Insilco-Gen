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
- `canonical_v037_candidate_analysis.json`: deterministic v0.37 overlay over the frozen v0.36 result package, including source-derived ranked candidates, a valid same-gene compound-heterozygous pair, source-bound exclusions, family/sample limitations, coverage, and unresolved branches.
- `expected_v037_candidate_analysis_output.json`: expected deterministic summary for `python -m app.insilicopop.cli v037-demo`.

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

For the v0.37 candidate-analysis demo, run:

```powershell
$env:PYTHONPATH = "backend"
python -m app.insilicopop.cli v037-demo
```

The demo uses the frozen v0.36 VCF header (`SAMPLE-DEMO` and
`CONTROL-DEMO`). The declared father has no corresponding VCF sample, so the
family branch remains `insufficient_information`; no deterministic de novo
claim is made. The two multi-allelic candidates exercise a source-bound
same-gene compound pair while retaining `phase_unknown` because trans evidence
is not supplied. Candidate IDs are derived from the v0.36 source binding, and
the persisted result includes strict finite frequency values plus independently
recomputed raw and weighted ranking contributions.

For full context, see:

- `docs/insilicopop_overview.md`
- `docs/local_demo_v015.md`
- `docs/safety_guardrails.md`
- `docs/why_not_freeform_chatgpt.md`
