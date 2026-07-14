from pathlib import Path

from app.insilicopop.agent.loop import AgentLoop


def _report(tmp_path: Path, query: str = "selection is proven") -> str:
    result = AgentLoop(generated_root=tmp_path).run(
        query=query,
        uploads={
            "selection_scan": {
                "filename": "selection.tsv",
                "content": b"chr\tposition\tgene\tihs\tp_value\n1\t123\tLCT\t2.8\t0.001\n",
            }
        },
        memory_mode="compact",
    )
    return Path(result["generated_files"]["final_report"]["absolute_path"]).read_text(encoding="utf-8")


def test_researcher_report_has_required_v013_headings_in_order(tmp_path):
    report = _report(tmp_path)
    headings = [
        "# InSilicoPop Agent Run Report",
        "## 1. Research Goal",
        "## 2. Input Inventory",
        "## 3. Workflow Selection",
        "## Recipe Preview",
        "## 4. Planned Actions",
        "## 5. Dry-Run Command Previews",
        "## 6. Missing Inputs and Dependencies",
        "## 7. Blocked Actions and Unsupported Claims",
        "## 8. Scientific Validity Notes",
        "## 9. Memory Capsule Summary",
        "## 10. Reproducibility Bundle",
        "## 11. Human Review Required",
        "## 12. Run Metadata",
    ]

    positions = [report.index(heading) for heading in headings]
    assert positions == sorted(positions)


def test_researcher_report_summarizes_goal_workflow_commands_and_guardrails(tmp_path):
    report = _report(tmp_path)

    assert "selection is proven" in report
    assert "Selected workflow family: `results_only_audit`" in report
    assert "## Recipe Preview" in report
    assert "selected recipe ID: `results_only_audit_basic`" in report
    assert "selected deterministic dry-run recipe preview" in report
    assert "Population-genetics result files are present" in report
    assert "## 5. Dry-Run Command Previews" in report
    assert "These commands were not executed by InSilicoPop." in report
    assert "Execution enabled: false" in report
    assert "## 7. Blocked Actions and Unsupported Claims" in report
    assert "FST/selection scans must not be claimed to prove selection without adequate controls." in report
    assert "No purity/superiority claims." in report
    assert "No clinical diagnosis." in report


def test_researcher_report_includes_validity_memory_reproducibility_and_human_review(tmp_path):
    report = _report(tmp_path)

    assert "## 8. Scientific Validity Notes" in report
    assert "Claims should be tied to parsed evidence." in report
    assert "## 9. Memory Capsule Summary" in report
    assert "Critical facts:" in report
    assert "Blocked interpretations:" in report
    assert "Provenance refs:" in report
    assert "## 10. Reproducibility Bundle" in report
    assert "reproducibility/selected_recipe.json" in report
    assert "reproducibility/runtime_lock.json" in report
    assert "raw user genomic files are not checksummed by default" in report
    assert "## 11. Human Review Required" in report
    assert "It does not replace expert human review." in report


def test_researcher_report_metadata_preserves_default_mock_invariants(tmp_path):
    report = _report(tmp_path)

    assert "- llm_provider: `mock`" in report
    assert "- external_llm_called: `false`" in report
    assert "- external_tools_executed: `false`" in report


def test_researcher_report_redacts_secret_like_goal_text(tmp_path):
    report = _report(tmp_path, query="audit selection token=super-secret sk-abcdefghijklmnop")

    assert "super-secret" not in report
    assert "sk-abcdefghijklmnop" not in report
    assert "[REDACTED]" in report
