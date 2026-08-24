from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from app.insilicopop.clinical.integrated_analysis_models import (
    BcftoolsExecutionAuthorization,
    BcftoolsInvocation,
    ExternalToolExecutionRecord,
    ExternalToolExecutionStatus,
    SourceAvailability,
    SourceClassification,
    WslBcftoolsRuntimeBinding,
    canonical_json,
    sha256_hex,
)


BCFTOOLS_ADAPTER_VERSION = "insilicopop-bcftools-adapter-0.38.0"
BCFTOOLS_PARSER_VERSION = "bcftools-parser-0.38.0"
BCFTOOLS_SCHEMA_VERSION = "0.38"
MAX_INPUT_BYTES = 50_000_000
MAX_OUTPUT_BYTES = 50_000_000
SAFE_EXECUTABLE_NAME = "bcftools.exe" if os.name == "nt" else "bcftools"


class BcftoolsAvailability(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    available: bool
    executable_path: str | None = None
    version: str | None = None
    binary_sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    binary_byte_size: int | None = Field(default=None, ge=0)
    license: str = "unknown until pinned release verification"
    execution_environment: str = "native"
    reason: str | None = None


class BcftoolsExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record: ExternalToolExecutionRecord
    parsed_output: dict[str, Any] = Field(default_factory=dict)
    output_path: str | None = None


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_path(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    root_resolved = root.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError("bcftools input/output path must stay inside the bounded workspace") from exc
    if any(token in str(resolved) for token in (";", "|", "&", "$", "`", "\x00")):
        raise ValueError("bcftools path contains a shell metacharacter")
    return resolved


def _invocation_identity(invocation: BcftoolsInvocation) -> str:
    return sha256_hex({"tool": "bcftools", "adapter_version": BCFTOOLS_ADAPTER_VERSION, "invocation": invocation.model_dump(mode="json")})


def discover_bcftools(executable_path: str | None = None) -> BcftoolsAvailability:
    candidate = executable_path or shutil.which("bcftools")
    if not candidate:
        return BcftoolsAvailability(
            available=False,
            execution_environment="native unavailable; WSL/container probes are performed by the validation harness",
            reason="no allowlisted native bcftools executable was found",
        )
    resolved = Path(candidate).resolve()
    if resolved.name.casefold() not in {"bcftools", "bcftools.exe"}:
        return BcftoolsAvailability(available=False, reason="discovered executable is not named bcftools")
    if not resolved.is_file():
        return BcftoolsAvailability(available=False, reason="discovered bcftools path is not a regular file")
    try:
        version = _inspect_version(resolved)
        digest = _file_sha256(resolved)
        size = resolved.stat().st_size
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return BcftoolsAvailability(available=False, executable_path=str(resolved), reason=f"bcftools inspection failed: {exc}")
    return BcftoolsAvailability(
        available=True,
        executable_path=str(resolved),
        version=version,
        binary_sha256=digest,
        binary_byte_size=size,
        license="bcftools/htslib license must be pinned with the approved release",
    )


def _inspect_version(executable: Path) -> str:
    completed = subprocess.run(
        [str(executable), "--version"],
        shell=False,
        cwd=str(executable.parent),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=15,
        check=False,
        env={"PATH": str(executable.parent), "LC_ALL": "C", "HTS_FILE_LOCKING": "0"},
    )
    if completed.returncode != 0:
        raise ValueError("bcftools --version returned a non-zero exit code")
    first_line = completed.stdout.decode("utf-8", errors="replace").splitlines()[0] if completed.stdout else ""
    match = re.search(r"bcftools\s+([0-9][A-Za-z0-9._-]*)", first_line, flags=re.IGNORECASE)
    if not match:
        raise ValueError("bcftools version output did not contain a parseable version")
    return match.group(1)


class BcftoolsAdapter:
    def __init__(
        self,
        *,
        executable_path: str | None = None,
        bounded_root: Path | None = None,
        max_input_bytes: int = MAX_INPUT_BYTES,
        max_output_bytes: int = MAX_OUTPUT_BYTES,
        authorization_granted: bool = True,
    ) -> None:
        self.bounded_root = (bounded_root or Path(tempfile.gettempdir()) / "insilicopop-v038-tools").resolve()
        self.max_input_bytes = max_input_bytes
        self.max_output_bytes = max_output_bytes
        self.authorization_granted = authorization_granted
        if not authorization_granted:
            self.availability = BcftoolsAvailability(
                available=False,
                execution_environment="not checked; explicit controlled approval required",
                reason="explicit controlled approval is required before bcftools discovery or execution",
            )
            self._executable = None
            return
        self.bounded_root.mkdir(parents=True, exist_ok=True)
        self.availability = discover_bcftools(executable_path)
        if self.availability.available and self.availability.executable_path:
            executable = Path(self.availability.executable_path).resolve()
            if executable.name.casefold() not in {"bcftools", "bcftools.exe"}:
                raise ValueError("bcftools adapter only accepts the exact allowlisted bcftools executable")
            self._executable = executable
        else:
            self._executable = None

    def execute(
        self,
        invocation: BcftoolsInvocation,
        *,
        input_path: Path | None = None,
        output_path: Path | None = None,
    ) -> BcftoolsExecutionResult:
        identity = _invocation_identity(invocation)
        if not self.authorization_granted:
            return BcftoolsExecutionResult(
                record=self._record(
                    invocation,
                    identity=identity,
                    status=ExternalToolExecutionStatus.BLOCKED,
                    error_code="TOOL_AUTHORIZATION_REQUIRED",
                    error_detail="explicit controlled approval is required before bcftools discovery or execution",
                )
            )
        if not self.availability.available or self._executable is None:
            return BcftoolsExecutionResult(
                record=self._record(
                    invocation,
                    identity=identity,
                    status=ExternalToolExecutionStatus.UNAVAILABLE,
                    error_code="BCFTOOLS_UNAVAILABLE",
                    error_detail=self.availability.reason or "bcftools is not available",
                )
            )
        if invocation.operation == "version":
            input_file = None
        else:
            if input_path is None:
                raise ValueError("bcftools operation requires a typed input path")
            input_file = _safe_path(Path(input_path), self.bounded_root)
            if not input_file.is_file():
                raise ValueError("bcftools input path is not a regular file")
            if input_file.stat().st_size > self.max_input_bytes:
                return BcftoolsExecutionResult(record=self._record(invocation, identity=identity, status=ExternalToolExecutionStatus.BLOCKED, error_code="INPUT_TOO_LARGE", error_detail="input exceeds the bounded adapter limit"))
        output_file: Path | None = None
        if output_path is not None:
            output_file = _safe_path(Path(output_path), self.bounded_root)
            output_file.parent.mkdir(parents=True, exist_ok=True)
        argv = self._argv(invocation, input_file, output_file)
        try:
            completed = subprocess.run(
                argv,
                shell=False,
                cwd=str(self.bounded_root),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=invocation.timeout_seconds,
                check=False,
                env={"PATH": str(self._executable.parent), "LC_ALL": "C", "HTS_FILE_LOCKING": "0", "NO_PROXY": "*"},
            )
        except subprocess.TimeoutExpired:
            return BcftoolsExecutionResult(record=self._record(invocation, identity=identity, status=ExternalToolExecutionStatus.TIMED_OUT, input_file=input_file, error_code="TIMEOUT", error_detail="bcftools exceeded the typed timeout"))
        stdout = completed.stdout or b""
        stderr = completed.stderr or b""
        if len(stdout) > self.max_output_bytes or len(stderr) > self.max_output_bytes:
            return BcftoolsExecutionResult(record=self._record(invocation, identity=identity, status=ExternalToolExecutionStatus.BLOCKED, input_file=input_file, error_code="OUTPUT_TOO_LARGE", error_detail="bcftools output exceeded the bounded adapter limit"))
        if completed.returncode != 0:
            return BcftoolsExecutionResult(record=self._record(invocation, identity=identity, status=ExternalToolExecutionStatus.FAILED, input_file=input_file, error_code="NONZERO_EXIT", error_detail=stderr.decode("utf-8", errors="replace")[:500]))
        parsed = self._parse(invocation, stdout, input_file, output_file)
        output_digest = _file_sha256(output_file) if output_file and output_file.is_file() else None
        if output_file and output_file.is_file() and output_file.stat().st_size > self.max_output_bytes:
            return BcftoolsExecutionResult(record=self._record(invocation, identity=identity, status=ExternalToolExecutionStatus.BLOCKED, input_file=input_file, output_file=output_file, error_code="OUTPUT_TOO_LARGE", error_detail="bcftools output file exceeded the bounded adapter limit"))
        return BcftoolsExecutionResult(
            record=self._record(invocation, identity=identity, status=ExternalToolExecutionStatus.COMPLETED, input_file=input_file, output_file=output_file, output_digest=output_digest, parsed=parsed),
            parsed_output=parsed,
            output_path=str(output_file) if output_file else None,
        )

    def _argv(self, invocation: BcftoolsInvocation, input_file: Path | None, output_file: Path | None) -> list[str]:
        assert self._executable is not None
        input_text = str(input_file) if input_file else None
        if invocation.operation == "version":
            return [str(self._executable), "--version"]
        if input_text is None:
            raise ValueError("typed bcftools operation missing input")
        if invocation.operation == "validate":
            return [str(self._executable), "view", "-h", input_text]
        if invocation.operation == "stats":
            return [str(self._executable), "stats", input_text]
        if invocation.operation == "sample_names":
            return [str(self._executable), "query", "-l", input_text]
        if invocation.operation == "decompose_multiallelic":
            if output_file is None:
                raise ValueError("multiallelic decomposition requires a typed output path")
            return [str(self._executable), "norm", "-m", "-any", "-Ov", "-o", str(output_file), input_text]
        raise ValueError(f"unsupported typed bcftools operation: {invocation.operation}")

    def _parse(self, invocation: BcftoolsInvocation, stdout: bytes, input_file: Path | None, output_file: Path | None) -> dict[str, Any]:
        text = stdout.decode("utf-8", errors="replace")
        if invocation.operation == "version":
            return {"version": self.availability.version, "stdout_sha256": sha256_hex(stdout)}
        if invocation.operation == "sample_names":
            return {"sample_names": tuple(item for item in (line.strip() for line in text.splitlines()) if item), "sample_count": len([line for line in text.splitlines() if line.strip()])}
        if invocation.operation == "stats":
            values: dict[str, Any] = {}
            for line in text.splitlines():
                if not line.startswith("SN\t"):
                    continue
                fields = line.split("\t")
                if len(fields) >= 4:
                    key = fields[2].rstrip(":").strip().lower().replace(" ", "_")
                    values[key] = _typed_number(fields[3])
            return {"stats": values, "stdout_sha256": sha256_hex(stdout), "input_sha256": _file_sha256(input_file) if input_file else None}
        if invocation.operation == "validate":
            return {"header_validated": True, "header_sha256": sha256_hex(stdout)}
        if invocation.operation == "decompose_multiallelic":
            return {"decomposed_output_sha256": _file_sha256(output_file) if output_file and output_file.is_file() else None, "decomposed_output_bytes": output_file.stat().st_size if output_file and output_file.is_file() else 0}
        return {}

    def _record(
        self,
        invocation: BcftoolsInvocation,
        *,
        identity: str,
        status: ExternalToolExecutionStatus,
        input_file: Path | None = None,
        output_file: Path | None = None,
        output_digest: str | None = None,
        parsed: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_detail: str | None = None,
    ) -> ExternalToolExecutionRecord:
        return ExternalToolExecutionRecord(
            execution_id=f"bcftools-execution-{identity[:24]}",
            tool_id="bcftools",
            tool_name="bcftools",
            adapter_version=BCFTOOLS_ADAPTER_VERSION,
            execution_status=status,
            availability=(
                SourceAvailability.AUTH_REQUIRED
                if not self.authorization_granted
                else (SourceAvailability.AVAILABLE if self.availability.available else SourceAvailability.UNAVAILABLE)
            ),
            operation=invocation.operation,
            typed_invocation=invocation.model_dump(mode="json"),
            executable_path=self.availability.executable_path,
            tool_version=self.availability.version,
            binary_or_image_digest=self.availability.binary_sha256,
            license=self.availability.license,
            execution_environment=self.availability.execution_environment,
            input_sha256=_file_sha256(input_file) if input_file and input_file.is_file() else None,
            output_sha256=output_digest,
            invocation_identity_sha256=identity,
            parser_version=BCFTOOLS_PARSER_VERSION,
            schema_version=BCFTOOLS_SCHEMA_VERSION,
            network_disabled=True,
            shell_used=False,
            timeout_seconds=invocation.timeout_seconds,
            output_size_bytes=output_file.stat().st_size if output_file and output_file.is_file() else None,
            error_code=error_code,
            error_detail=error_detail,
            source_classification=SourceClassification.DETERMINISTIC,
        )


def _typed_number(value: str) -> int | float | str:
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


WSL_BCFTOOLS_ADAPTER_VERSION = "insilicopop-wsl-bcftools-adapter-0.38.0"
WSL_BCFTOOLS_PARSER_VERSION = "bcftools-wsl-parser-0.38.0"
WSL_RUNTIME_ENVIRONMENT = "wsl2:Ubuntu-24.04:direct-argv"
_PROXY_ENVIRONMENT_KEYS = {
    "ALL_PROXY",
    "FTP_PROXY",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "all_proxy",
    "ftp_proxy",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "WSLENV",
}


@dataclass(frozen=True)
class _BoundedCommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    timed_out: bool = False
    output_limit_exceeded: bool = False


CommandRunner = Callable[[list[str], int, Path, dict[str, str], int], _BoundedCommandResult]


def _run_bounded_command(
    argv: list[str],
    timeout_seconds: int,
    cwd: Path,
    env: dict[str, str],
    max_output_bytes: int,
) -> _BoundedCommandResult:
    """Drain both streams concurrently and kill the child before output grows unbounded."""

    process = subprocess.Popen(
        argv,
        shell=False,
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    captured = {"stdout": bytearray(), "stderr": bytearray()}
    lock = threading.Lock()
    output_limit_exceeded = threading.Event()

    def drain(stream_name: str, stream: Any) -> None:
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                break
            with lock:
                bucket = captured[stream_name]
                remaining = max_output_bytes + 1 - len(bucket)
                if remaining > 0:
                    bucket.extend(chunk[:remaining])
                if len(bucket) > max_output_bytes:
                    output_limit_exceeded.set()
                    try:
                        process.kill()
                    except OSError:
                        pass

    assert process.stdout is not None and process.stderr is not None
    readers = (
        threading.Thread(target=drain, args=("stdout", process.stdout), daemon=True),
        threading.Thread(target=drain, args=("stderr", process.stderr), daemon=True),
    )
    for reader in readers:
        reader.start()
    timed_out = False
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        process.wait()
    for reader in readers:
        reader.join(timeout=5)
    return _BoundedCommandResult(
        returncode=process.returncode if process.returncode is not None else -1,
        stdout=bytes(captured["stdout"]),
        stderr=bytes(captured["stderr"]),
        timed_out=timed_out,
        output_limit_exceeded=output_limit_exceeded.is_set(),
    )


def _contains_shell_metacharacter(value: str) -> bool:
    return any(token in value for token in (";", "|", "&", "$", "`", "\x00", "\n", "\r"))


def _is_symlink_or_reparse(path: Path) -> bool:
    try:
        metadata = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(metadata.st_mode):
        return True
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(metadata, "st_file_attributes", 0) & reparse_flag)


def _safe_bounded_windows_path(path: Path, root: Path, *, must_exist: bool) -> Path:
    if _contains_shell_metacharacter(str(path)):
        raise ValueError("bcftools path contains a shell metacharacter")
    if not path.is_absolute() or str(path).startswith("\\\\"):
        raise ValueError("bcftools accepts only canonical absolute local Windows paths")
    raw_root = root.absolute()
    raw_path = path.absolute()
    try:
        relative = raw_path.relative_to(raw_root)
    except ValueError as exc:
        raise ValueError("bcftools input/output path must stay inside the bounded workspace") from exc
    if any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("bcftools path traversal is not allowed")
    candidate = raw_root
    if _is_symlink_or_reparse(candidate):
        raise ValueError("bounded workspace root cannot be a symlink or reparse point")
    for part in relative.parts:
        candidate = candidate / part
        if candidate.exists() or candidate.is_symlink():
            if _is_symlink_or_reparse(candidate):
                raise ValueError("bcftools rejects symlink or reparse-point path components")
    resolved_root = raw_root.resolve()
    resolved_path = raw_path.resolve(strict=False)
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("bcftools path escaped the bounded workspace") from exc
    if must_exist and (not raw_path.is_file() or _is_symlink_or_reparse(raw_path)):
        raise ValueError("bcftools input path is not a regular non-reparse file")
    return raw_path


def _windows_path_to_wsl_path(path: Path) -> str:
    resolved = path.resolve()
    if str(resolved).startswith("\\\\") or not re.fullmatch(r"[A-Za-z]:", resolved.drive):
        raise ValueError("only local drive-letter paths can be mapped into WSL")
    relative = resolved.relative_to(Path(resolved.anchor))
    return f"/mnt/{resolved.drive[0].lower()}/" + "/".join(relative.parts)


def _safe_vcf_records(path: Path) -> tuple[dict[str, str], ...]:
    records: list[dict[str, str]] = []
    with path.open("rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            if not line or line.startswith("#"):
                continue
            columns = line.rstrip("\r\n").split("\t")
            if len(columns) < 8:
                raise ValueError("bcftools decomposition output is not a valid VCF record stream")
            records.append({
                "chromosome": columns[0],
                "position": columns[1],
                "identifier": columns[2],
                "ref": columns[3],
                "alt": columns[4],
            })
            if len(records) > 10_000:
                raise ValueError("bcftools decomposition output exceeded the bounded record parser limit")
    return tuple(records)


def _normalized_stats_output(stdout: bytes) -> bytes:
    text = stdout.decode("utf-8", errors="replace")
    retained = [
        line
        for line in text.splitlines()
        if not line.startswith("# The command") and not line.startswith("ID\t")
    ]
    return ("\n".join(retained) + ("\n" if retained else "")).encode("utf-8")


def _wsl_invocation_identity(
    runtime: WslBcftoolsRuntimeBinding,
    authorization: BcftoolsExecutionAuthorization | None,
    invocation: BcftoolsInvocation,
) -> str:
    return sha256_hex({
        "tool": "bcftools",
        "adapter_version": WSL_BCFTOOLS_ADAPTER_VERSION,
        "runtime_binding_identity_sha256": runtime.identity_sha256(),
        "authorization_identity_sha256": authorization.identity_sha256() if authorization is not None else None,
        "invocation": invocation.model_dump(mode="json"),
    })


class WslBcftoolsAdapter:
    """Digest-pinned Ubuntu WSL adapter. It never falls back to native discovery."""

    def __init__(
        self,
        *,
        runtime_binding: WslBcftoolsRuntimeBinding,
        authorization: BcftoolsExecutionAuthorization | None,
        bounded_root: Path | None = None,
        now: datetime | None = None,
        runner: CommandRunner | None = None,
    ) -> None:
        self.runtime_binding = runtime_binding
        self.authorization = authorization
        self._now = now or datetime.now(timezone.utc)
        self._runner = runner or _run_bounded_command
        self._wsl_executable = Path(runtime_binding.wsl_executable_path)
        self.max_input_bytes = runtime_binding.max_input_bytes
        self.max_output_bytes = runtime_binding.max_output_bytes
        self._base_root = (bounded_root or Path(tempfile.gettempdir()) / "insilicopop-v038-wsl").resolve()
        self._cleanup_outcome = "not_started"
        self._availability_error_code: str | None = None
        if authorization is None:
            self.bounded_root = self._base_root
            self.availability = BcftoolsAvailability(
                available=False,
                execution_environment="not checked; typed WSL authorization required",
                reason="a typed registered WSL authorization record is required before runtime inspection",
            )
            self._availability_error_code = "TOOL_AUTHORIZATION_RECORD_REQUIRED"
            return
        self._base_root.mkdir(parents=True, exist_ok=True)
        self.bounded_root = Path(tempfile.mkdtemp(prefix="bcftools-", dir=str(self._base_root))).resolve()
        self.availability = self._inspect_runtime()

    def _host_environment(self) -> dict[str, str]:
        system_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\\Windows"
        system32 = str(Path(system_root) / "System32")
        environment = {
            key: os.environ[key]
            for key in ("SystemRoot", "WINDIR", "SystemDrive", "ComSpec", "TEMP", "TMP")
            if key in os.environ
        }
        environment["PATH"] = os.pathsep.join((str(self._wsl_executable.parent), system32, system_root))
        environment["LC_ALL"] = "C"
        for key in _PROXY_ENVIRONMENT_KEYS:
            environment.pop(key, None)
        return environment

    def _wsl_argv(self, linux_argv: list[str]) -> list[str]:
        return [
            str(self._wsl_executable),
            "--distribution",
            self.runtime_binding.distribution,
            "--exec",
            "/usr/bin/env",
            "-i",
            "LC_ALL=C",
            "HTS_FILE_LOCKING=0",
            "NO_PROXY=*",
            "no_proxy=*",
            "PATH=/usr/bin:/bin",
            *linux_argv,
        ]

    def _run_wsl(self, linux_argv: list[str], timeout_seconds: int) -> _BoundedCommandResult:
        return self._runner(
            self._wsl_argv(linux_argv),
            timeout_seconds,
            self.bounded_root,
            self._host_environment(),
            self.max_output_bytes,
        )

    def _probe(self, linux_argv: list[str], *, timeout_seconds: int = 15) -> _BoundedCommandResult:
        result = self._run_wsl(linux_argv, timeout_seconds)
        if result.timed_out:
            raise ValueError("WSL runtime inspection exceeded its timeout")
        if result.output_limit_exceeded:
            raise ValueError("WSL runtime inspection exceeded its output limit")
        return result

    def _unavailable(self, reason: str, code: str) -> BcftoolsAvailability:
        self._availability_error_code = code
        return BcftoolsAvailability(
            available=False,
            executable_path=self.runtime_binding.bcftools_wsl_path,
            execution_environment=WSL_RUNTIME_ENVIRONMENT,
            reason=reason,
        )

    def _inspect_runtime(self) -> BcftoolsAvailability:
        self._availability_error_code = None
        authorization = self.authorization
        assert authorization is not None
        if not authorization.is_current(self._now):
            return self._unavailable("the typed local authorization record is stale or not yet valid", "STALE_AUTHORIZATION")
        if authorization.runtime_binding_identity_sha256 != self.runtime_binding.identity_sha256():
            return self._unavailable("authorization does not bind the registered WSL runtime identity", "RUNTIME_BINDING_MISMATCH")
        if self.runtime_binding.distribution != "Ubuntu-24.04":
            return self._unavailable("registered WSL distribution is not the approved Ubuntu-24.04 runtime", "WRONG_DISTRIBUTION")
        if self._wsl_executable.name.casefold() != "wsl.exe" or not self._wsl_executable.is_file():
            return self._unavailable("registered absolute wsl.exe path is not an available regular file", "WSL_EXECUTABLE_INVALID")
        try:
            link = self._probe(["/usr/bin/test", "-L", self.runtime_binding.bcftools_wsl_path])
            if link.returncode == 0:
                return self._unavailable("registered bcftools executable is a symlink", "EXECUTABLE_SYMLINK")
            if link.returncode != 1:
                return self._unavailable("registered bcftools symlink inspection failed", "EXECUTABLE_INSPECTION_FAILED")
            metadata = self._probe(["/usr/bin/stat", "-c", "%F|%a|%s", self.runtime_binding.bcftools_wsl_path])
            if metadata.returncode != 0:
                return self._unavailable("registered bcftools metadata inspection failed", "EXECUTABLE_INSPECTION_FAILED")
            fields = metadata.stdout.decode("utf-8", errors="replace").strip().split("|")
            if len(fields) != 3 or fields[0] != "regular file":
                return self._unavailable("registered bcftools path is not a regular file", "EXECUTABLE_NOT_REGULAR")
            mode = int(fields[1], 8)
            size = int(fields[2])
            if mode & 0o022:
                return self._unavailable("registered bcftools executable is group- or world-writable", "EXECUTABLE_WRITABLE")
            if size != self.runtime_binding.executable_byte_size:
                return self._unavailable("registered bcftools executable size does not match the pinned runtime", "EXECUTABLE_SIZE_MISMATCH")
            digest = self._probe(["/usr/bin/sha256sum", self.runtime_binding.bcftools_wsl_path])
            digest_text = digest.stdout.decode("utf-8", errors="replace").strip().split(maxsplit=1)[0] if digest.returncode == 0 else ""
            if digest.returncode != 0 or not re.fullmatch(r"[a-f0-9]{64}", digest_text):
                return self._unavailable("registered bcftools digest inspection failed", "EXECUTABLE_INSPECTION_FAILED")
            if digest_text != self.runtime_binding.executable_sha256:
                return self._unavailable("registered bcftools digest does not match the typed binding", "EXECUTABLE_DIGEST_MISMATCH")
            version_result = self._probe([self.runtime_binding.bcftools_wsl_path, "--version"])
            version_text = version_result.stdout.decode("utf-8", errors="replace")
            bcftools_match = re.search(r"^bcftools\s+([^\s]+)", version_text, flags=re.MULTILINE | re.IGNORECASE)
            htslib_match = re.search(r"^Using htslib\s+([^\s]+)", version_text, flags=re.MULTILINE | re.IGNORECASE)
            if version_result.returncode != 0 or bcftools_match is None or htslib_match is None:
                return self._unavailable("registered bcftools version output was not parseable", "VERSION_INSPECTION_FAILED")
            if bcftools_match.group(1) != self.runtime_binding.bcftools_version:
                return self._unavailable("registered bcftools version does not match the typed binding", "WRONG_BCFTOOLS_VERSION")
            if htslib_match.group(1) != self.runtime_binding.htslib_version:
                return self._unavailable("registered htslib version does not match the typed binding", "WRONG_HTSLIB_VERSION")
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            return self._unavailable(f"registered WSL bcftools inspection failed: {exc}", "EXECUTABLE_INSPECTION_FAILED")
        return BcftoolsAvailability(
            available=True,
            executable_path=self.runtime_binding.bcftools_wsl_path,
            version=self.runtime_binding.bcftools_version,
            binary_sha256=self.runtime_binding.executable_sha256,
            binary_byte_size=self.runtime_binding.executable_byte_size,
            license=self.runtime_binding.license,
            execution_environment=WSL_RUNTIME_ENVIRONMENT,
        )

    def stage_canonical_input(self, source_path: Path) -> Path:
        """Copy only the authorization-bound local VCF into the fresh work directory."""

        if self.authorization is None:
            raise ValueError("typed authorization is required before input staging")
        source = source_path.absolute()
        if _contains_shell_metacharacter(str(source)) or _is_symlink_or_reparse(source) or not source.is_file():
            raise ValueError("authorized bcftools input must be a local regular non-reparse file")
        if _file_sha256(source) != self.authorization.authorized_input_sha256:
            raise ValueError("authorized bcftools input digest does not match the typed authorization")
        staged = self.bounded_root / "input" / "canonical_v038_input.vcf"
        staged.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, staged)
        if _file_sha256(staged) != self.authorization.authorized_input_sha256:
            raise ValueError("staged bcftools input digest verification failed")
        return _safe_bounded_windows_path(staged, self.bounded_root, must_exist=True)

    def _authorized_invocation(self, invocation: BcftoolsInvocation, input_file: Path | None) -> str | None:
        authorization = self.authorization
        if authorization is None:
            return "TOOL_AUTHORIZATION_RECORD_REQUIRED"
        if invocation.operation not in authorization.authorized_operations:
            return "UNSUPPORTED_OPERATION"
        if invocation.timeout_seconds > self.runtime_binding.max_timeout_seconds:
            return "TIMEOUT_NOT_AUTHORIZED"
        reference_values = (
            invocation.reference_name,
            invocation.reference_source,
            invocation.reference_assembly,
            invocation.reference_byte_size,
            invocation.reference_sha256,
        )
        if any(value is not None for value in reference_values):
            return "REFERENCE_NORMALIZATION_NOT_AUTHORIZED"
        if invocation.operation == "version":
            return "VERSION_ARGUMENTS_NOT_AUTHORIZED" if any((invocation.input_relative_path, invocation.output_relative_path)) else None
        if invocation.input_relative_path != authorization.authorized_input_relative_path:
            return "INPUT_PATH_NOT_AUTHORIZED"
        if input_file is None or _file_sha256(input_file) != authorization.authorized_input_sha256:
            return "INPUT_DIGEST_MISMATCH"
        return None

    def execute(
        self,
        invocation: BcftoolsInvocation,
        *,
        input_path: Path | None = None,
        output_path: Path | None = None,
    ) -> BcftoolsExecutionResult:
        identity = _wsl_invocation_identity(self.runtime_binding, self.authorization, invocation)
        if self.authorization is None:
            return BcftoolsExecutionResult(record=self._record(invocation, identity=identity, status=ExternalToolExecutionStatus.BLOCKED, error_code="TOOL_AUTHORIZATION_RECORD_REQUIRED", error_detail="a typed registered authorization record is required before WSL execution"))
        # Re-inspect immediately before every process launch. This detects a
        # replacement or permission change after the authorization was loaded.
        self.availability = self._inspect_runtime()
        if not self.availability.available:
            status = ExternalToolExecutionStatus.BLOCKED if self._availability_error_code in {
                "STALE_AUTHORIZATION",
                "RUNTIME_BINDING_MISMATCH",
                "WRONG_DISTRIBUTION",
                "WSL_EXECUTABLE_INVALID",
                "EXECUTABLE_SYMLINK",
                "EXECUTABLE_WRITABLE",
                "EXECUTABLE_SIZE_MISMATCH",
                "EXECUTABLE_DIGEST_MISMATCH",
                "WRONG_BCFTOOLS_VERSION",
                "WRONG_HTSLIB_VERSION",
            } else ExternalToolExecutionStatus.UNAVAILABLE
            return BcftoolsExecutionResult(record=self._record(invocation, identity=identity, status=status, error_code=self._availability_error_code or "BCFTOOLS_UNAVAILABLE", error_detail=self.availability.reason or "registered WSL bcftools runtime is unavailable"))
        if invocation.operation == "version":
            input_file = None
        else:
            if input_path is None:
                raise ValueError("bcftools operation requires a staged typed input path")
            input_file = _safe_bounded_windows_path(Path(input_path), self.bounded_root, must_exist=True)
            if input_file.stat().st_size > self.max_input_bytes:
                return BcftoolsExecutionResult(record=self._record(invocation, identity=identity, status=ExternalToolExecutionStatus.BLOCKED, input_file=input_file, error_code="INPUT_TOO_LARGE", error_detail="input exceeds the registered adapter limit"))
        authorization_error = self._authorized_invocation(invocation, input_file)
        if authorization_error is not None:
            return BcftoolsExecutionResult(record=self._record(invocation, identity=identity, status=ExternalToolExecutionStatus.BLOCKED, input_file=input_file, error_code=authorization_error, error_detail="typed WSL authorization did not permit this invocation"))
        output_file: Path | None = None
        if invocation.operation == "decompose_multiallelic":
            if output_path is None:
                raise ValueError("multiallelic decomposition requires a typed output path")
            output_file = _safe_bounded_windows_path(Path(output_path), self.bounded_root, must_exist=False)
            output_file.parent.mkdir(parents=True, exist_ok=True)
        argv = self._argv(invocation, input_file, output_file)
        result = self._runner(argv, invocation.timeout_seconds, self.bounded_root, self._host_environment(), self.max_output_bytes)
        if result.timed_out:
            return BcftoolsExecutionResult(record=self._record(invocation, identity=identity, status=ExternalToolExecutionStatus.TIMED_OUT, input_file=input_file, error_code="TIMEOUT", error_detail="bcftools exceeded the typed timeout"))
        if result.output_limit_exceeded:
            return BcftoolsExecutionResult(record=self._record(invocation, identity=identity, status=ExternalToolExecutionStatus.BLOCKED, input_file=input_file, output_file=output_file, error_code="OUTPUT_TOO_LARGE", error_detail="bcftools output exceeded the registered stream limit"))
        if result.returncode != 0:
            return BcftoolsExecutionResult(record=self._record(invocation, identity=identity, status=ExternalToolExecutionStatus.FAILED, input_file=input_file, output_file=output_file, error_code="NONZERO_EXIT", error_detail="bcftools returned a non-zero exit code"))
        if output_file is not None:
            if not output_file.is_file() or _is_symlink_or_reparse(output_file):
                return BcftoolsExecutionResult(record=self._record(invocation, identity=identity, status=ExternalToolExecutionStatus.FAILED, input_file=input_file, output_file=output_file, error_code="OUTPUT_NOT_REGULAR", error_detail="bcftools did not create a regular local output file"))
            if output_file.stat().st_size > self.max_output_bytes:
                return BcftoolsExecutionResult(record=self._record(invocation, identity=identity, status=ExternalToolExecutionStatus.BLOCKED, input_file=input_file, output_file=output_file, error_code="OUTPUT_TOO_LARGE", error_detail="bcftools output file exceeded the registered limit"))
        try:
            parsed = self._parse(invocation, result.stdout, input_file, output_file)
        except ValueError as exc:
            return BcftoolsExecutionResult(record=self._record(invocation, identity=identity, status=ExternalToolExecutionStatus.FAILED, input_file=input_file, output_file=output_file, error_code="MALFORMED_OUTPUT", error_detail=str(exc)))
        output_digest = _file_sha256(output_file) if output_file is not None else None
        return BcftoolsExecutionResult(
            record=self._record(invocation, identity=identity, status=ExternalToolExecutionStatus.COMPLETED, input_file=input_file, output_file=output_file, output_digest=output_digest, parsed=parsed),
            parsed_output=parsed,
            output_path=str(output_file) if output_file is not None else None,
        )

    def _argv(self, invocation: BcftoolsInvocation, input_file: Path | None, output_file: Path | None) -> list[str]:
        input_wsl = _windows_path_to_wsl_path(input_file) if input_file is not None else None
        if invocation.operation == "version":
            command = [self.runtime_binding.bcftools_wsl_path, "--version"]
        elif invocation.operation == "validate" and input_wsl is not None:
            command = [self.runtime_binding.bcftools_wsl_path, "view", "--no-version", "-Ov", input_wsl]
        elif invocation.operation == "stats" and input_wsl is not None:
            command = [self.runtime_binding.bcftools_wsl_path, "stats", input_wsl]
        elif invocation.operation == "sample_names" and input_wsl is not None:
            command = [self.runtime_binding.bcftools_wsl_path, "query", "-l", input_wsl]
        elif invocation.operation == "decompose_multiallelic" and input_wsl is not None and output_file is not None:
            command = [
                self.runtime_binding.bcftools_wsl_path,
                "norm",
                "--no-version",
                "-m",
                "-any",
                "-Ov",
                "-o",
                _windows_path_to_wsl_path(output_file),
                input_wsl,
            ]
        else:
            raise ValueError("unsupported typed WSL bcftools invocation")
        return self._wsl_argv(command)

    def _parse(
        self,
        invocation: BcftoolsInvocation,
        stdout: bytes,
        input_file: Path | None,
        output_file: Path | None,
    ) -> dict[str, Any]:
        text = stdout.decode("utf-8", errors="replace")
        if invocation.operation == "version":
            return {
                "bcftools_version": self.runtime_binding.bcftools_version,
                "htslib_version": self.runtime_binding.htslib_version,
                "stdout_sha256": sha256_hex(stdout),
            }
        if invocation.operation == "validate":
            return {"header_validated": True, "header_sha256": sha256_hex(stdout)}
        if invocation.operation == "sample_names":
            names = tuple(item for item in (line.strip() for line in text.splitlines()) if item)
            return {"sample_names": names, "sample_count": len(names)}
        if invocation.operation == "stats":
            values: dict[str, Any] = {}
            for line in text.splitlines():
                if not line.startswith("SN\t"):
                    continue
                fields = line.split("\t")
                if len(fields) >= 4:
                    key = fields[2].rstrip(":").strip().lower().replace(" ", "_")
                    values[key] = _typed_number(fields[3])
            return {
                "stats": values,
                "normalized_stdout_sha256": sha256_hex(_normalized_stats_output(stdout)),
                "input_sha256": _file_sha256(input_file) if input_file is not None else None,
            }
        if invocation.operation == "decompose_multiallelic":
            if input_file is None or output_file is None or not output_file.is_file():
                raise ValueError("decomposition output was not available for parsing")
            source_records = _safe_vcf_records(input_file)
            source_by_allele: dict[tuple[str, str, str, str], tuple[dict[str, str], int]] = {}
            for source in source_records:
                for alt_index, alt in enumerate(source["alt"].split(","), start=1):
                    source_by_allele[(source["chromosome"], source["position"], source["ref"], alt)] = (source, alt_index)
            decomposed: list[dict[str, Any]] = []
            for output in _safe_vcf_records(output_file):
                key = (output["chromosome"], output["position"], output["ref"], output["alt"])
                source, alt_index = source_by_allele.get(key, (output, 1))
                source_representation = f"{source['chromosome']}:{source['position']}:{source['ref']}>{source['alt']}"
                decomposed_representation = f"{output['chromosome']}:{output['position']}:{output['ref']}>{output['alt']}"
                decomposed.append({
                    "source_representation": source_representation,
                    "source_record_sha256": sha256_hex(source),
                    "source_alt_index": alt_index,
                    "decomposed_representation": decomposed_representation,
                    "normalized_representation": decomposed_representation,
                    "reference_left_normalization_performed": False,
                })
            return {
                "decomposed_output_sha256": _file_sha256(output_file),
                "decomposed_output_bytes": output_file.stat().st_size,
                "decomposed_records": tuple(decomposed),
                "reference_left_normalization_performed": False,
            }
        raise ValueError("unsupported typed WSL bcftools parser operation")

    def _record(
        self,
        invocation: BcftoolsInvocation,
        *,
        identity: str,
        status: ExternalToolExecutionStatus,
        input_file: Path | None = None,
        output_file: Path | None = None,
        output_digest: str | None = None,
        parsed: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_detail: str | None = None,
    ) -> ExternalToolExecutionRecord:
        contract: dict[str, Any] = {
            "runtime_binding_identity_sha256": self.runtime_binding.identity_sha256(),
            "authorization_identity_sha256": self.authorization.identity_sha256() if self.authorization is not None else None,
            "authorization_scope": self.authorization.scope if self.authorization is not None else None,
            "local_file_only": True,
            "network_isolation_level": self.runtime_binding.network_isolation_level,
            "proxy_environment_removed": True,
            "shell_interpolation_used": False,
            "work_directory_policy": "fresh_bounded_windows_directory",
            "max_input_bytes": self.max_input_bytes,
            "max_output_bytes_per_stream_or_file": self.max_output_bytes,
            "expected_exit_codes": (0,),
            "cleanup_outcome": self._cleanup_outcome,
            "reference_left_normalization_performed": False,
        }
        typed_invocation: dict[str, Any] = {
            "invocation": invocation.model_dump(mode="json"),
            "execution_contract": contract,
        }
        if parsed:
            typed_invocation["result_summary"] = parsed
        return ExternalToolExecutionRecord(
            execution_id=f"bcftools-wsl-execution-{identity[:20]}",
            tool_id="bcftools",
            tool_name="bcftools",
            adapter_version=WSL_BCFTOOLS_ADAPTER_VERSION,
            execution_status=status,
            availability=(SourceAvailability.AUTH_REQUIRED if self.authorization is None else (SourceAvailability.AVAILABLE if self.availability.available else SourceAvailability.UNAVAILABLE)),
            operation=invocation.operation,
            typed_invocation=typed_invocation,
            executable_path=self.runtime_binding.bcftools_wsl_path,
            tool_version=self.runtime_binding.bcftools_version,
            binary_or_image_digest=self.runtime_binding.executable_sha256,
            license=self.runtime_binding.license,
            execution_environment=WSL_RUNTIME_ENVIRONMENT,
            input_sha256=_file_sha256(input_file) if input_file is not None and input_file.is_file() else None,
            output_sha256=output_digest,
            invocation_identity_sha256=identity,
            parser_version=WSL_BCFTOOLS_PARSER_VERSION,
            schema_version=BCFTOOLS_SCHEMA_VERSION,
            network_disabled=True,
            shell_used=False,
            timeout_seconds=invocation.timeout_seconds,
            output_size_bytes=output_file.stat().st_size if output_file is not None and output_file.is_file() else None,
            error_code=error_code,
            error_detail=error_detail,
            source_classification=SourceClassification.DETERMINISTIC,
        )

    def with_cleanup_outcome(self, record: ExternalToolExecutionRecord, outcome: str) -> ExternalToolExecutionRecord:
        payload = dict(record.typed_invocation)
        contract = dict(payload.get("execution_contract") or {})
        contract["cleanup_outcome"] = outcome
        payload["execution_contract"] = contract
        return record.model_copy(update={"typed_invocation": payload})

    def cleanup(self) -> str:
        if self._cleanup_outcome in {"removed", "not_created", "cleanup_failed"}:
            return self._cleanup_outcome
        if not self.bounded_root.exists():
            self._cleanup_outcome = "not_created"
            return self._cleanup_outcome
        try:
            root = self.bounded_root.resolve()
            base = self._base_root.resolve()
            relative = root.relative_to(base)
            if len(relative.parts) != 1 or not root.name.startswith("bcftools-"):
                raise ValueError("refusing to clean an unbounded WSL work directory")
            shutil.rmtree(root)
            self._cleanup_outcome = "removed"
        except (OSError, ValueError):
            self._cleanup_outcome = "cleanup_failed"
        return self._cleanup_outcome


def default_wsl_runtime_paths() -> tuple[Path, Path, Path]:
    examples = Path(__file__).resolve().parents[4] / "examples" / "insilicopop_demo"
    return (
        examples / "canonical_v038_wsl_bcftools_runtime.json",
        examples / "canonical_v038_wsl_bcftools_authorization.json",
        examples / "canonical_v038_wsl_bcftools_environment_lock.json",
    )


def load_registered_wsl_runtime() -> tuple[WslBcftoolsRuntimeBinding, BcftoolsExecutionAuthorization]:
    runtime_path, authorization_path, lock_path = default_wsl_runtime_paths()
    runtime = WslBcftoolsRuntimeBinding.model_validate(json.loads(runtime_path.read_text(encoding="utf-8")))
    authorization = BcftoolsExecutionAuthorization.model_validate(json.loads(authorization_path.read_text(encoding="utf-8")))
    if _file_sha256(lock_path) != runtime.environment_lock_sha256:
        raise ValueError("registered WSL environment lock digest does not match the runtime binding")
    if authorization.runtime_binding_identity_sha256 != runtime.identity_sha256():
        raise ValueError("registered WSL authorization does not bind the runtime manifest")
    return runtime, authorization


__all__ = [
    "BCFTOOLS_ADAPTER_VERSION",
    "BCFTOOLS_PARSER_VERSION",
    "WSL_BCFTOOLS_ADAPTER_VERSION",
    "WSL_BCFTOOLS_PARSER_VERSION",
    "BcftoolsAvailability",
    "BcftoolsExecutionResult",
    "discover_bcftools",
    "BcftoolsAdapter",
    "WslBcftoolsAdapter",
    "default_wsl_runtime_paths",
    "load_registered_wsl_runtime",
]
