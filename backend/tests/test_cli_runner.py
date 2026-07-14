import subprocess
import sys


def test_benchmark_memory_cli_runs():
    result = subprocess.run(
        [sys.executable, "-m", "app.insilicopop.cli", "benchmark-memory", "--scenario", "admixture_underfit", "--token-budget", "1000"],
        cwd="backend",
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0
    assert "winner=" in result.stdout


def test_audit_cli_runs_with_example_files():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.insilicopop.cli",
            "audit",
            "--metadata",
            "examples/indian_metadata.csv",
            "--pca",
            "examples/pca_results.csv",
            "--admixture",
            "examples/admixture_cv_errors.csv",
            "--fst",
            "examples/fst_matrix.csv",
            "--roh",
            "examples/roh_summary.csv",
            "--selection",
            "examples/selection_scan_results.csv",
            "--query",
            "selection is proven",
        ],
        cwd="backend",
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0
    assert "reliability_score=" in result.stdout
