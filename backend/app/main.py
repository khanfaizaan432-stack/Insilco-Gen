from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.insilicopop.agent.loop import AgentLoop
from app.insilicopop.agent.workbench import (
    AgentArtifactContent,
    AgentArtifactSummary,
    AgentRunDetail,
    AgentRunSummary,
    ReproducibilityBundleSummary,
    WorkbenchRunStore,
)
from app.insilicopop.audit_service import InSilicoPopAuditService, capabilities
from app.insilicopop.benchmarks.agent_trace import AgentMemoryBenchmarkRunner
from app.insilicopop.benchmarks.runner import MemoryBenchmarkRunner
from app.insilicopop.memory.compressor import DomainMemoryCompressor
from app.insilicopop.llm.byok_runtime import BYOKSessionConfiguration, byok_runtime
from app.schemas.memory import MemoryCompressRequest, MemoryCompressResponse
from app.workflows.dry_biotics import DryBioticsWorkflow


app = FastAPI(
    title="InSilicoOS Backend",
    version="0.1.0",
    description="Local agentic workflow backend for dry-lab computational biology.",
)

MAX_BYOK_CONFIGURATION_BYTES = 64_000
CAPABILITY_PATH_PATTERN = re.compile(r"(/insilicopop/byok/session/)[A-Za-z0-9_.:%-]+")


def _redact_capability_path(value: str) -> str:
    return CAPABILITY_PATH_PATTERN.sub(r"\1[REDACTED_CAPABILITY]", value)


class _CapabilityAccessLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(_redact_capability_path(item) if isinstance(item, str) else item for item in record.args)
        if isinstance(record.msg, str):
            record.msg = _redact_capability_path(record.msg)
        return True


_access_logger = logging.getLogger("uvicorn.access")
if not any(isinstance(item, _CapabilityAccessLogFilter) for item in _access_logger.filters):
    _access_logger.addFilter(_CapabilityAccessLogFilter())

WORKBENCH_HTML_PATH = Path(__file__).resolve().parent / "insilicopop" / "workbench_static" / "index.html"


class MemoryBenchmarkRequest(BaseModel):
    scenario: str = Field(default="all")
    token_budget: int = Field(default=1000, ge=1)


class AgentMemoryBenchmarkRequest(BaseModel):
    scenario: str = Field(default="all")
    budget_chars: int = Field(default=1500, ge=1)
    memory_mode: str = Field(default="compact")


@app.post("/insilicopop/byok/session")
async def configure_byok_session(request: Request) -> dict[str, object]:
    """Parse BYOK configuration without framework errors echoing request values."""

    try:
        declared_length = request.headers.get("content-length")
        if declared_length is not None:
            if not re.fullmatch(r"\d+", declared_length):
                raise ValueError("BYOK configuration Content-Length is invalid.")
            if int(declared_length) > MAX_BYOK_CONFIGURATION_BYTES:
                raise ValueError("BYOK configuration body is too large.")
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > MAX_BYOK_CONFIGURATION_BYTES:
                raise ValueError("BYOK configuration body is too large.")
            raw.extend(chunk)
        payload = json.loads(bytes(raw))
        if not isinstance(payload, dict):
            raise ValueError("BYOK configuration must be an object.")
        config = BYOKSessionConfiguration.model_validate(payload)
        return byok_runtime.configure(config).model_dump()
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError, ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid BYOK configuration. Check provider, endpoint, model, key presence, and bounded budget values.",
        ) from exc


@app.get("/insilicopop/byok/session/{session_id}")
def byok_session_status(session_id: str) -> dict[str, object]:
    try:
        return byok_runtime.status(session_id).model_dump()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/insilicopop/byok/session/{session_id}/test")
def test_byok_session(session_id: str) -> dict[str, object]:
    try:
        return byok_runtime.test_connection(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/insilicopop/byok/session/{session_id}")
def forget_byok_session(session_id: str) -> dict[str, object]:
    byok_runtime.forget(session_id)
    return {"status": "forgotten"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "insilicoos-backend"}


@app.post("/analyze")
async def analyze(
    sequences: UploadFile = File(...),
    labels: UploadFile = File(...),
) -> dict[str, object]:
    try:
        fasta_bytes = await sequences.read()
        label_bytes = await labels.read()
        return DryBioticsWorkflow().run(fasta_bytes, label_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/insilicopop/capabilities")
def insilicopop_capabilities() -> dict[str, object]:
    return capabilities()


@app.get("/insilicopop/workbench", response_class=HTMLResponse)
def insilicopop_workbench() -> HTMLResponse:
    if not WORKBENCH_HTML_PATH.is_file():
        raise HTTPException(status_code=500, detail="workbench UI asset is missing")
    return HTMLResponse(WORKBENCH_HTML_PATH.read_text(encoding="utf-8"))


@app.post("/insilicopop/audit")
async def insilicopop_audit(
    query: str | None = Form(None),
    metadata_file: UploadFile | None = File(None),
    pca_file: UploadFile | None = File(None),
    admixture_file: UploadFile | None = File(None),
    fst_file: UploadFile | None = File(None),
    roh_file: UploadFile | None = File(None),
    plink_qc_file: UploadFile | None = File(None),
    selection_file: UploadFile | None = File(None),
    plink_imiss_file: UploadFile | None = File(None),
    plink_lmiss_file: UploadFile | None = File(None),
    plink_het_file: UploadFile | None = File(None),
    plink_hwe_file: UploadFile | None = File(None),
    plink_prune_in_file: UploadFile | None = File(None),
    plink_prune_out_file: UploadFile | None = File(None),
    plink_genome_file: UploadFile | None = File(None),
    admixture_cv_file: UploadFile | None = File(None),
    admixture_q_file: UploadFile | None = File(None),
    admixture_p_file: UploadFile | None = File(None),
    smartpca_evec_file: UploadFile | None = File(None),
    smartpca_eval_file: UploadFile | None = File(None),
    smartpca_log_file: UploadFile | None = File(None),
    windowed_fst_file: UploadFile | None = File(None),
    plink_hom_file: UploadFile | None = File(None),
    vcf_file: UploadFile | None = File(None),
    plink_bed_file: UploadFile | None = File(None),
    plink_bim_file: UploadFile | None = File(None),
    plink_fam_file: UploadFile | None = File(None),
    ped_file: UploadFile | None = File(None),
    map_file: UploadFile | None = File(None),
    pgen_file: UploadFile | None = File(None),
    pvar_file: UploadFile | None = File(None),
    psam_file: UploadFile | None = File(None),
    bam_file: UploadFile | None = File(None),
    cram_file: UploadFile | None = File(None),
) -> dict[str, object]:
    try:
        uploads = {
            "metadata": await _read_optional_upload_with_name(metadata_file),
            "pca": await _read_optional_upload_with_name(pca_file),
            "admixture": await _read_optional_upload_with_name(admixture_file),
            "fst": await _read_optional_upload_with_name(fst_file),
            "roh": await _read_optional_upload_with_name(roh_file),
            "plink_qc": await _read_optional_upload_with_name(plink_qc_file),
            "selection_scan": await _read_optional_upload_with_name(selection_file),
            "plink_imiss": await _read_optional_upload_with_name(plink_imiss_file),
            "plink_lmiss": await _read_optional_upload_with_name(plink_lmiss_file),
            "plink_het": await _read_optional_upload_with_name(plink_het_file),
            "plink_hwe": await _read_optional_upload_with_name(plink_hwe_file),
            "plink_prune_in": await _read_optional_upload_with_name(plink_prune_in_file),
            "plink_prune_out": await _read_optional_upload_with_name(plink_prune_out_file),
            "plink_genome": await _read_optional_upload_with_name(plink_genome_file),
            "admixture_cv": await _read_optional_upload_with_name(admixture_cv_file),
            "admixture_q": await _read_optional_upload_with_name(admixture_q_file),
            "admixture_p": await _read_optional_upload_with_name(admixture_p_file),
            "smartpca_evec": await _read_optional_upload_with_name(smartpca_evec_file),
            "smartpca_eval": await _read_optional_upload_with_name(smartpca_eval_file),
            "smartpca_log": await _read_optional_upload_with_name(smartpca_log_file),
            "windowed_fst": await _read_optional_upload_with_name(windowed_fst_file),
            "plink_hom": await _read_optional_upload_with_name(plink_hom_file),
            "vcf": await _read_optional_upload_with_name(vcf_file),
            "plink_bed": await _read_optional_upload_with_name(plink_bed_file),
            "plink_bim": await _read_optional_upload_with_name(plink_bim_file),
            "plink_fam": await _read_optional_upload_with_name(plink_fam_file),
            "ped": await _read_optional_upload_with_name(ped_file),
            "map": await _read_optional_upload_with_name(map_file),
            "pgen": await _read_optional_upload_with_name(pgen_file),
            "pvar": await _read_optional_upload_with_name(pvar_file),
            "psam": await _read_optional_upload_with_name(psam_file),
            "bam": await _read_optional_upload_with_name(bam_file),
            "cram": await _read_optional_upload_with_name(cram_file),
        }
        return InSilicoPopAuditService().run(query, uploads).model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/insilicopop/agent/run")
async def insilicopop_agent_run(
    query: str | None = Form(None),
    max_steps: int = Form(8),
    memory_budget_chars: int = Form(1500),
    memory_mode: str = Form("compact"),
    llm_provider: str = Form("mock"),
    data_use_agreement_scope: str | None = Form(None),
    metadata_registry: str | None = Form(None),
    clinical_case_intake: str | None = Form(None),
    byok_session_id: str | None = Form(None),
    metadata_file: UploadFile | None = File(None),
    pca_file: UploadFile | None = File(None),
    admixture_file: UploadFile | None = File(None),
    fst_file: UploadFile | None = File(None),
    roh_file: UploadFile | None = File(None),
    plink_qc_file: UploadFile | None = File(None),
    selection_file: UploadFile | None = File(None),
    plink_imiss_file: UploadFile | None = File(None),
    plink_lmiss_file: UploadFile | None = File(None),
    plink_het_file: UploadFile | None = File(None),
    plink_hwe_file: UploadFile | None = File(None),
    plink_prune_in_file: UploadFile | None = File(None),
    plink_prune_out_file: UploadFile | None = File(None),
    plink_genome_file: UploadFile | None = File(None),
    admixture_cv_file: UploadFile | None = File(None),
    admixture_q_file: UploadFile | None = File(None),
    admixture_p_file: UploadFile | None = File(None),
    smartpca_evec_file: UploadFile | None = File(None),
    smartpca_eval_file: UploadFile | None = File(None),
    smartpca_log_file: UploadFile | None = File(None),
    windowed_fst_file: UploadFile | None = File(None),
    plink_hom_file: UploadFile | None = File(None),
    vcf_file: UploadFile | None = File(None),
    plink_bed_file: UploadFile | None = File(None),
    plink_bim_file: UploadFile | None = File(None),
    plink_fam_file: UploadFile | None = File(None),
    ped_file: UploadFile | None = File(None),
    map_file: UploadFile | None = File(None),
    pgen_file: UploadFile | None = File(None),
    pvar_file: UploadFile | None = File(None),
    psam_file: UploadFile | None = File(None),
    bam_file: UploadFile | None = File(None),
    cram_file: UploadFile | None = File(None),
) -> dict[str, object]:
    if memory_mode not in {"compact", "ultra_compact"}:
        raise HTTPException(status_code=400, detail="memory_mode must be compact or ultra_compact")
    try:
        uploads = {
            "metadata": await _read_optional_upload_with_name(metadata_file),
            "pca": await _read_optional_upload_with_name(pca_file),
            "admixture": await _read_optional_upload_with_name(admixture_file),
            "fst": await _read_optional_upload_with_name(fst_file),
            "roh": await _read_optional_upload_with_name(roh_file),
            "plink_qc": await _read_optional_upload_with_name(plink_qc_file),
            "selection_scan": await _read_optional_upload_with_name(selection_file),
            "plink_imiss": await _read_optional_upload_with_name(plink_imiss_file),
            "plink_lmiss": await _read_optional_upload_with_name(plink_lmiss_file),
            "plink_het": await _read_optional_upload_with_name(plink_het_file),
            "plink_hwe": await _read_optional_upload_with_name(plink_hwe_file),
            "plink_prune_in": await _read_optional_upload_with_name(plink_prune_in_file),
            "plink_prune_out": await _read_optional_upload_with_name(plink_prune_out_file),
            "plink_genome": await _read_optional_upload_with_name(plink_genome_file),
            "admixture_cv": await _read_optional_upload_with_name(admixture_cv_file),
            "admixture_q": await _read_optional_upload_with_name(admixture_q_file),
            "admixture_p": await _read_optional_upload_with_name(admixture_p_file),
            "smartpca_evec": await _read_optional_upload_with_name(smartpca_evec_file),
            "smartpca_eval": await _read_optional_upload_with_name(smartpca_eval_file),
            "smartpca_log": await _read_optional_upload_with_name(smartpca_log_file),
            "windowed_fst": await _read_optional_upload_with_name(windowed_fst_file),
            "plink_hom": await _read_optional_upload_with_name(plink_hom_file),
            "vcf": await _read_optional_upload_with_name(vcf_file),
            "plink_bed": await _read_optional_upload_with_name(plink_bed_file),
            "plink_bim": await _read_optional_upload_with_name(plink_bim_file),
            "plink_fam": await _read_optional_upload_with_name(plink_fam_file),
            "ped": await _read_optional_upload_with_name(ped_file),
            "map": await _read_optional_upload_with_name(map_file),
            "pgen": await _read_optional_upload_with_name(pgen_file),
            "pvar": await _read_optional_upload_with_name(pvar_file),
            "psam": await _read_optional_upload_with_name(psam_file),
            "bam": await _read_optional_upload_with_name(bam_file),
            "cram": await _read_optional_upload_with_name(cram_file),
        }
        return AgentLoop().run(
            query=query,
            uploads=uploads,
            max_steps=max_steps,
            memory_budget_chars=memory_budget_chars,
            memory_mode=memory_mode,  # type: ignore[arg-type]
            llm_provider=llm_provider,
            data_use_agreement_scope=_parse_data_use_agreement_scope(data_use_agreement_scope),
            metadata_registry=_parse_json_object_form(metadata_registry, "metadata_registry"),
            clinical_case_intake=_parse_json_object_form(clinical_case_intake, "clinical_case_intake"),
            byok_runtime=byok_runtime.public_provenance(byok_session_id) if byok_session_id else None,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/insilicopop/agent/runs", response_model=list[AgentRunSummary])
def insilicopop_agent_runs() -> list[AgentRunSummary]:
    return WorkbenchRunStore().list_runs()


@app.get("/insilicopop/agent/runs/{run_id}", response_model=AgentRunDetail)
def insilicopop_agent_run_detail(run_id: str) -> AgentRunDetail:
    try:
        return WorkbenchRunStore().run_detail(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="agent run not found") from exc


@app.get("/insilicopop/agent/runs/{run_id}/artifacts", response_model=list[AgentArtifactSummary])
def insilicopop_agent_run_artifacts(run_id: str) -> list[AgentArtifactSummary]:
    try:
        return WorkbenchRunStore().list_artifacts(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="agent run not found") from exc


@app.get("/insilicopop/agent/runs/{run_id}/artifacts/{artifact_name:path}", response_model=AgentArtifactContent)
def insilicopop_agent_run_artifact(run_id: str, artifact_name: str) -> AgentArtifactContent:
    try:
        return WorkbenchRunStore().read_artifact(run_id, artifact_name)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="artifact is not allowed for workbench access") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="agent artifact not found") from exc


@app.get("/insilicopop/agent/runs/{run_id}/report", response_model=AgentArtifactContent)
def insilicopop_agent_run_report(run_id: str) -> AgentArtifactContent:
    try:
        return WorkbenchRunStore().final_report(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="agent run report not found") from exc


@app.get("/insilicopop/agent/runs/{run_id}/workflow-selection")
def insilicopop_agent_run_workflow_selection(run_id: str) -> dict[str, object]:
    try:
        return WorkbenchRunStore().workflow_selection(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="agent run workflow selection not found") from exc


@app.get("/insilicopop/agent/runs/{run_id}/reproducibility", response_model=ReproducibilityBundleSummary)
def insilicopop_agent_run_reproducibility(run_id: str) -> ReproducibilityBundleSummary:
    try:
        return WorkbenchRunStore().reproducibility(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="agent run not found") from exc


@app.post("/insilicopop/memory/compress", response_model=MemoryCompressResponse)
def insilicopop_memory_compress(request: MemoryCompressRequest) -> MemoryCompressResponse:
    return DomainMemoryCompressor().compress(request)


@app.post("/insilicopop/benchmark/memory")
def insilicopop_memory_benchmark(request: MemoryBenchmarkRequest) -> dict[str, object]:
    try:
        return MemoryBenchmarkRunner().run(request.scenario, request.token_budget)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/insilicopop/benchmark/agent-memory")
def insilicopop_agent_memory_benchmark(request: AgentMemoryBenchmarkRequest) -> dict[str, object]:
    try:
        return AgentMemoryBenchmarkRunner().run(request.scenario, request.budget_chars, request.memory_mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _read_optional_upload(upload: UploadFile | None) -> bytes | None:
    if upload is None:
        return None
    content = await upload.read()
    return content or None


async def _read_optional_upload_with_name(upload: UploadFile | None) -> dict[str, bytes | str] | None:
    if upload is None:
        return None
    content = await upload.read()
    if not content:
        return None
    return {"content": content, "filename": upload.filename or "upload"}


def _parse_data_use_agreement_scope(raw: str | None) -> dict[str, object] | None:
    return _parse_json_object_form(raw, "data_use_agreement_scope")


def _parse_json_object_form(raw: str | None, field_name: str) -> dict[str, object] | None:
    if raw is None or not raw.strip():
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} must be valid JSON object text") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{field_name} must be a JSON object")
    return parsed
