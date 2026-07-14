import subprocess
import sys


def test_benchmark_agent_memory_cli_runs():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.insilicopop.cli",
            "benchmark-agent-memory",
            "--scenario",
            "admixture_underfit",
            "--budget-chars",
            "1500",
            "--memory-mode",
            "compact",
        ],
        cwd="backend",
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0
    assert "critical_recall" in result.stdout
    assert "final_score" in result.stdout
