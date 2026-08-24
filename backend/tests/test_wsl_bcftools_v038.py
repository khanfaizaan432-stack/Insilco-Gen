from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.insilicopop.cli import _load_v038_fixture, main
from app.insilicopop.clinical.integrated_analysis import build_clinical_case_v038_workspace
from app.insilicopop.clinical.integrated_analysis_models import BcftoolsInvocation
from app.insilicopop.clinical import tool_execution as tool_execution_module
from app.insilicopop.clinical.tool_execution import (
    _BoundedCommandResult,
    WslBcftoolsAdapter,
    load_registered_wsl_runtime,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO_ROOT / "examples" / "insilicopop_demo" / "canonical_v038_integrated_analysis.json"
CANONICAL_VCF_PATH = REPO_ROOT / "examples" / "insilicopop_demo" / "canonical_v038_input.vcf"
AUTHORIZED_EXPECTED_OUTPUT_PATH = (
    REPO_ROOT / "examples" / "insilicopop_demo" / "expected_v038_wsl_bcftools_authorized_output.json"
)


def _payload() -> dict:
    return _load_v038_fixture(str(FIXTURE_PATH))


class _FakeWslRunner:
    """Controlled direct-argv runner for failure-path checks; never starts a process."""

    def __init__(self, runtime) -> None:
        self.runtime = runtime
        self.digest = runtime.executable_sha256
        self.mode = "success"
        self.stats_path_number = 0
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], timeout_seconds: int, cwd: Path, env: dict[str, str], max_output_bytes: int) -> _BoundedCommandResult:
        del timeout_seconds, cwd, env, max_output_bytes
        self.calls.append(argv)
        if "/usr/bin/test" in argv:
            return _BoundedCommandResult(returncode=1, stdout=b"", stderr=b"")
        if "/usr/bin/stat" in argv:
            return _BoundedCommandResult(
                returncode=0,
                stdout=f"regular file|755|{self.runtime.executable_byte_size}\n".encode("ascii"),
                stderr=b"",
            )
        if "/usr/bin/sha256sum" in argv:
            return _BoundedCommandResult(
                returncode=0,
                stdout=f"{self.digest}  {self.runtime.bcftools_wsl_path}\n".encode("ascii"),
                stderr=b"",
            )
        if "--version" in argv:
            return _BoundedCommandResult(
                returncode=0,
                stdout=b"bcftools 1.24\nUsing htslib 1.24\n",
                stderr=b"",
            )
        if "stats" in argv:
            if self.mode == "timeout":
                return _BoundedCommandResult(returncode=-1, stdout=b"", stderr=b"", timed_out=True)
            if self.mode == "output_limit":
                return _BoundedCommandResult(returncode=-1, stdout=b"", stderr=b"", output_limit_exceeded=True)
            if self.mode == "nonzero":
                return _BoundedCommandResult(returncode=2, stdout=b"", stderr=b"synthetic failure")
            self.stats_path_number += 1
            return _BoundedCommandResult(
                returncode=0,
                stdout=(
                    "# The command line was:\tbcftools stats /mnt/c/fresh-" + str(self.stats_path_number) + "/input.vcf\n"
                    "ID\t0\t/mnt/c/fresh-" + str(self.stats_path_number) + "/input.vcf\n"
                    "SN\t0\tnumber of samples:\t2\n"
                    "SN\t0\tnumber of records:\t1\n"
                ).encode("utf-8"),
                stderr=b"",
            )
        if "query" in argv:
            return _BoundedCommandResult(returncode=0, stdout=b"SAMPLE-DEMO\nCONTROL-DEMO\n", stderr=b"")
        if "view" in argv:
            return _BoundedCommandResult(returncode=0, stdout=b"##fileformat=VCFv4.3\n", stderr=b"")
        if "norm" in argv:
            return _BoundedCommandResult(returncode=0, stdout=b"", stderr=b"")
        raise AssertionError(f"unexpected fixed runner argv: {argv!r}")


@pytest.fixture
def fake_adapter(tmp_path: Path):
    runtime, authorization = load_registered_wsl_runtime()
    runner = _FakeWslRunner(runtime)
    adapter = WslBcftoolsAdapter(
        runtime_binding=runtime,
        authorization=authorization,
        bounded_root=tmp_path / "bounded",
        runner=runner,
    )
    assert adapter.availability.available
    staged = adapter.stage_canonical_input(CANONICAL_VCF_PATH)
    try:
        yield adapter, authorization, runner, staged
    finally:
        adapter.cleanup()


def _stats_invocation(authorization, *, timeout_seconds: int = 30) -> BcftoolsInvocation:
    return BcftoolsInvocation(
        operation="stats",
        input_relative_path=authorization.authorized_input_relative_path,
        timeout_seconds=timeout_seconds,
    )


def test_registered_wsl_adapter_uses_fixed_direct_argv(fake_adapter) -> None:
    adapter, authorization, runner, staged = fake_adapter
    argv = adapter._argv(BcftoolsInvocation(operation="version"), None, None)
    assert argv[:5] == [
        str(Path(adapter.runtime_binding.wsl_executable_path)),
        "--distribution",
        "Ubuntu-24.04",
        "--exec",
        "/usr/bin/env",
    ]
    assert argv[-2:] == [adapter.runtime_binding.bcftools_wsl_path, "--version"]
    assert "bash" not in argv
    assert "powershell" not in " ".join(argv).casefold()
    assert all(";" not in value and "|" not in value for value in argv)

    version = adapter.execute(BcftoolsInvocation(operation="version")).record
    stats = adapter.execute(_stats_invocation(authorization), input_path=staged).record
    samples = adapter.execute(
        BcftoolsInvocation(operation="sample_names", input_relative_path=authorization.authorized_input_relative_path),
        input_path=staged,
    ).record

    assert version.execution_status.value == "completed"
    assert stats.typed_invocation["result_summary"]["stats"]["number_of_records"] == 1
    assert samples.typed_invocation["result_summary"]["sample_names"] == ("SAMPLE-DEMO", "CONTROL-DEMO")
    assert all("--distribution" in call and "--exec" in call for call in runner.calls)


def test_generic_boolean_cannot_authorize_the_workspace() -> None:
    workspace = build_clinical_case_v038_workspace(_payload(), tool_execution_authorized=True)
    record = workspace.external_tool_executions[0]
    assert workspace.status.value == "partial"
    assert record.execution_status.value == "blocked"
    assert record.availability.value == "auth_required"
    assert record.error_code == "TOOL_AUTHORIZATION_REQUIRED"


def test_wrong_distribution_executable_and_digest_fail_closed(tmp_path: Path) -> None:
    runtime, authorization = load_registered_wsl_runtime()

    wrong_distribution = runtime.model_copy(update={"distribution": "Ubuntu-22.04"})
    wrong_distribution_auth = authorization.model_copy(
        update={"runtime_binding_identity_sha256": wrong_distribution.identity_sha256()}
    )
    distribution_adapter = WslBcftoolsAdapter(
        runtime_binding=wrong_distribution,
        authorization=wrong_distribution_auth,
        bounded_root=tmp_path / "wrong-distribution",
        runner=_FakeWslRunner(runtime),
    )
    assert distribution_adapter.execute(BcftoolsInvocation(operation="version")).record.error_code == "WRONG_DISTRIBUTION"
    distribution_adapter.cleanup()

    wrong_executable = runtime.model_copy(update={"wsl_executable_path": r"C:\missing\wsl.exe"})
    wrong_executable_auth = authorization.model_copy(
        update={"runtime_binding_identity_sha256": wrong_executable.identity_sha256()}
    )
    executable_adapter = WslBcftoolsAdapter(
        runtime_binding=wrong_executable,
        authorization=wrong_executable_auth,
        bounded_root=tmp_path / "wrong-executable",
        runner=_FakeWslRunner(runtime),
    )
    assert executable_adapter.execute(BcftoolsInvocation(operation="version")).record.error_code == "WSL_EXECUTABLE_INVALID"
    executable_adapter.cleanup()

    wrong_digest = runtime.model_copy(update={"executable_sha256": "0" * 64})
    wrong_digest_auth = authorization.model_copy(
        update={"runtime_binding_identity_sha256": wrong_digest.identity_sha256()}
    )
    digest_adapter = WslBcftoolsAdapter(
        runtime_binding=wrong_digest,
        authorization=wrong_digest_auth,
        bounded_root=tmp_path / "wrong-digest",
        runner=_FakeWslRunner(runtime),
    )
    assert digest_adapter.execute(BcftoolsInvocation(operation="version")).record.error_code == "EXECUTABLE_DIGEST_MISMATCH"
    digest_adapter.cleanup()


def test_replacement_stale_authorization_and_input_mismatch_fail_closed(fake_adapter, tmp_path: Path) -> None:
    adapter, authorization, runner, staged = fake_adapter
    runner.digest = "0" * 64
    replaced = adapter.execute(BcftoolsInvocation(operation="version")).record
    assert replaced.execution_status.value == "blocked"
    assert replaced.error_code == "EXECUTABLE_DIGEST_MISMATCH"

    runtime, authorization = load_registered_wsl_runtime()
    stale_authorization = authorization.model_copy(update={"expires_at_utc": "2020-01-01T00:00:00Z"})
    stale_adapter = WslBcftoolsAdapter(
        runtime_binding=runtime,
        authorization=stale_authorization,
        bounded_root=tmp_path / "stale",
        now=datetime(2026, 8, 23, tzinfo=timezone.utc),
        runner=_FakeWslRunner(runtime),
    )
    assert stale_adapter.execute(BcftoolsInvocation(operation="version")).record.error_code == "STALE_AUTHORIZATION"
    stale_adapter.cleanup()

    mismatch = tmp_path / "mismatched.vcf"
    mismatch.write_text(CANONICAL_VCF_PATH.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="digest"):
        WslBcftoolsAdapter(
            runtime_binding=runtime,
            authorization=authorization,
            bounded_root=tmp_path / "mismatch",
            runner=_FakeWslRunner(runtime),
        ).stage_canonical_input(mismatch)
    assert staged.is_file()


def test_unsupported_reference_url_shell_and_traversal_inputs_are_rejected(fake_adapter) -> None:
    adapter, authorization, _runner, staged = fake_adapter
    reference_invocation = BcftoolsInvocation(
        operation="stats",
        input_relative_path=authorization.authorized_input_relative_path,
        reference_name="GRCh38",
        reference_source="local-approved-reference.fa",
        reference_assembly="GRCh38",
        reference_byte_size=1,
        reference_sha256="a" * 64,
    )
    assert adapter.execute(reference_invocation, input_path=staged).record.error_code == "REFERENCE_NORMALIZATION_NOT_AUTHORIZED"
    assert adapter.execute(_stats_invocation(authorization, timeout_seconds=31), input_path=staged).record.error_code == "TIMEOUT_NOT_AUTHORIZED"

    for invalid in (
        {"operation": "query"},
        {"operation": "stats", "input_relative_path": "https://example.invalid/input.vcf"},
        {"operation": "stats", "input_relative_path": "input;rm.vcf"},
        {"operation": "stats", "input_relative_path": "../escape.vcf"},
    ):
        with pytest.raises(ValueError):
            BcftoolsInvocation(**invalid)


def test_reparse_path_rejection(fake_adapter, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, authorization, _runner, staged = fake_adapter
    reparse = adapter.bounded_root / "input" / "simulated-reparse.vcf"
    reparse.write_bytes(staged.read_bytes())
    original_classifier = tool_execution_module._is_symlink_or_reparse
    monkeypatch.setattr(
        tool_execution_module,
        "_is_symlink_or_reparse",
        lambda path: Path(path).absolute() == reparse.absolute() or original_classifier(path),
    )
    with pytest.raises(ValueError, match="symlink|reparse"):
        adapter.execute(_stats_invocation(authorization), input_path=reparse)


@pytest.mark.parametrize(
    ("mode", "status", "error_code"),
    [
        ("timeout", "timed_out", "TIMEOUT"),
        ("output_limit", "blocked", "OUTPUT_TOO_LARGE"),
        ("nonzero", "failed", "NONZERO_EXIT"),
    ],
)
def test_timeout_output_limit_and_nonzero_exit_are_bounded(fake_adapter, mode: str, status: str, error_code: str) -> None:
    adapter, authorization, runner, staged = fake_adapter
    runner.mode = mode
    result = adapter.execute(_stats_invocation(authorization), input_path=staged).record
    assert result.execution_status.value == status
    assert result.error_code == error_code
    serialized = json.dumps(result.model_dump(mode="json"), sort_keys=True)
    assert "synthetic failure" not in serialized
    assert "stderr" not in serialized


def test_malformed_output_and_deterministic_stats_parsing(fake_adapter) -> None:
    adapter, authorization, runner, staged = fake_adapter
    first = adapter.execute(_stats_invocation(authorization), input_path=staged).record
    second = adapter.execute(_stats_invocation(authorization), input_path=staged).record
    assert first.typed_invocation["result_summary"]["normalized_stdout_sha256"] == second.typed_invocation["result_summary"]["normalized_stdout_sha256"]

    malformed_output = adapter.bounded_root / "output" / "malformed.vcf"
    malformed_output.parent.mkdir(parents=True, exist_ok=True)
    malformed_output.write_text("not-a-vcf\n", encoding="utf-8")
    malformed = adapter.execute(
        BcftoolsInvocation(
            operation="decompose_multiallelic",
            input_relative_path=authorization.authorized_input_relative_path,
        ),
        input_path=staged,
        output_path=malformed_output,
    ).record
    assert malformed.execution_status.value == "failed"
    assert malformed.error_code == "MALFORMED_OUTPUT"
    assert runner.calls


def test_genuine_pinned_wsl_suite_and_authorized_workspace_reload(tmp_path: Path) -> None:
    try:
        runtime, authorization = load_registered_wsl_runtime()
    except (OSError, ValueError) as exc:
        pytest.skip(f"registered local WSL runtime is unavailable: {exc}")
    adapter = WslBcftoolsAdapter(
        runtime_binding=runtime,
        authorization=authorization,
        bounded_root=tmp_path / "genuine",
    )
    if not adapter.availability.available:
        adapter.cleanup()
        pytest.skip(f"registered local WSL runtime is unavailable: {adapter.availability.reason}")

    workspace = build_clinical_case_v038_workspace(
        _payload(),
        tool_adapter=adapter,
        tool_execution_authorization=authorization,
    )
    assert workspace.status.value == "complete"
    assert [record.operation for record in workspace.external_tool_executions] == [
        "version",
        "validate",
        "stats",
        "sample_names",
        "decompose_multiallelic",
    ]
    assert all(record.execution_status.value == "completed" for record in workspace.external_tool_executions)
    decomposition = workspace.external_tool_executions[-1].typed_invocation["result_summary"]
    assert decomposition["reference_left_normalization_performed"] is False
    assert decomposition["source_representation_matches_deterministic_record"] is True
    assert decomposition["matched_deterministic_source_record_ids"] == (
        "vcf-source-2c8fd5ddad44a81b30cc",
        "vcf-source-6404fd5ac340275e2e78",
    )
    assert [item["source_alt_index"] for item in decomposition["decomposed_records"]] == [1, 1, 2]
    assert len(decomposition["decomposed_records"]) == 3
    stats = workspace.external_tool_executions[2].typed_invocation["result_summary"]["stats"]
    assert stats["number_of_records"] == 2
    assert stats["number_of_multiallelic_sites"] == 1
    assert not adapter.bounded_root.exists()

    serialized = json.dumps(workspace.model_dump(mode="json"), sort_keys=True)
    assert "approval_record" not in serialized
    assert "password" not in serialized.casefold()
    assert "stderr" not in serialized
    assert "stdout\"" not in serialized
    reloaded = type(workspace).verified_load(workspace.model_dump(mode="json"))
    assert reloaded.final_integrity_sha256 == workspace.final_integrity_sha256


def test_authorized_cli_replays_the_separate_expected_artifact(capsys: pytest.CaptureFixture[str]) -> None:
    try:
        runtime, authorization = load_registered_wsl_runtime()
    except (OSError, ValueError) as exc:
        pytest.skip(f"registered local WSL runtime is unavailable: {exc}")
    probe = WslBcftoolsAdapter(runtime_binding=runtime, authorization=authorization)
    if not probe.availability.available:
        probe.cleanup()
        pytest.skip(f"registered local WSL runtime is unavailable: {probe.availability.reason}")
    probe.cleanup()

    assert main(["v038-demo", "--fixture", str(FIXTURE_PATH), "--authorize-tool"]) == 0
    first = capsys.readouterr().out
    assert main(["v038-demo", "--fixture", str(FIXTURE_PATH), "--authorize-tool"]) == 0
    second = capsys.readouterr().out
    assert first == second
    assert json.loads(first) == json.loads(AUTHORIZED_EXPECTED_OUTPUT_PATH.read_text(encoding="utf-8"))
    assert json.loads(first)["workspace_status"] == "complete"
