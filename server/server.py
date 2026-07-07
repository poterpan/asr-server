"""FastAPI front-end for the FunASR transcription pipeline.

Endpoints:
    GET  /                                             -> web UI (static/index.html)
    GET  /health                                       -> liveness probe (open)
    POST /transcribe          (multipart audio upload) -> {job_id}
    GET  /jobs/{job_id}                                -> job status
    GET  /jobs/{job_id}/result?format=json|md|llm      -> result payload

Auth: Bearer token from FUNASR_API_KEY env var. If unset, auth is disabled
(local dev only). The UI page itself is served unauthenticated; the browser
JS reads the user-pasted key from localStorage and sends it as a Bearer
header on each API call.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Header,
    UploadFile,
)
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from pipeline import Pipeline, format_as_markdown, format_for_llm

STATIC_DIR = Path(__file__).parent / "static"

logging.basicConfig(
    level=os.environ.get("FUNASR_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("funasr-server")

API_KEY = os.environ.get("FUNASR_API_KEY")
OUTPUT_DIR = Path(os.environ.get("FUNASR_OUTPUT_DIR", "outputs")).resolve()
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

if not API_KEY:
    logger.warning(
        "FUNASR_API_KEY is not set — request authentication is DISABLED. "
        "This is fine for local development on 127.0.0.1, but NEVER expose "
        "this server to a network without setting a key. Generate one with "
        "`openssl rand -hex 32`."
    )

app = FastAPI(title="funasr-server", version="0.1.0")

# Pipeline is heavy (multi-GB GPU load); build lazily on first request and reuse.
_pipeline: Pipeline | None = None
_pipeline_lock = threading.Lock()


def get_pipeline() -> Pipeline:
    global _pipeline
    if _pipeline is None:
        with _pipeline_lock:
            if _pipeline is None:
                _pipeline = Pipeline(device="cuda")
    return _pipeline


# In-memory job store. Single-process; survives only while uvicorn runs.
_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()


def _new_job(filename: str) -> str:
    job_id = uuid.uuid4().hex
    with _jobs_lock:
        _jobs[job_id] = {
            "id": job_id,
            "filename": filename,
            "status": "queued",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "started_at": None,
            "finished_at": None,
            "error": None,
            "segments": None,
        }
    return job_id


def _set_job(job_id: str, **fields: Any) -> None:
    with _jobs_lock:
        _jobs[job_id].update(fields)


def _get_job(job_id: str) -> dict[str, Any]:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return dict(job)


def require_auth(authorization: str | None = Header(default=None)) -> None:
    if not API_KEY:
        return
    expected = f"Bearer {API_KEY}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="invalid or missing bearer token")


def _run_job(
    job_id: str, audio_path: str, hotword: str | None, traditional: bool
) -> None:
    _set_job(
        job_id,
        status="running",
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    try:
        pipeline = get_pipeline()
        segments = pipeline.transcribe(
            audio_path, hotword=hotword, traditional=traditional
        )
        _set_job(
            job_id,
            status="done",
            finished_at=datetime.now(timezone.utc).isoformat(),
            segments=segments,
        )
        logger.info("job %s done (%d segments)", job_id, len(segments))
    except Exception as exc:
        logger.exception("job %s failed", job_id)
        _set_job(
            job_id,
            status="failed",
            finished_at=datetime.now(timezone.utc).isoformat(),
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        try:
            os.unlink(audio_path)
        except OSError:
            pass


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/transcribe", dependencies=[Depends(require_auth)])
async def transcribe(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    hotword: str | None = Form(default=None),
    traditional: bool = Form(default=True),
) -> dict[str, str]:
    suffix = Path(file.filename or "audio.wav").suffix or ".wav"
    tmp = tempfile.NamedTemporaryFile(prefix="funasr_", suffix=suffix, delete=False)
    try:
        with tmp:
            shutil.copyfileobj(file.file, tmp)
    finally:
        await file.close()

    job_id = _new_job(file.filename or "uploaded.wav")
    background_tasks.add_task(_run_job, job_id, tmp.name, hotword, traditional)
    return {"job_id": job_id, "status": "queued"}


@app.get("/jobs/{job_id}", dependencies=[Depends(require_auth)])
def job_status(job_id: str) -> dict[str, Any]:
    job = _get_job(job_id)
    # Don't echo segments in status; result endpoint owns that.
    job.pop("segments", None)
    return job


@app.get("/jobs/{job_id}/result", dependencies=[Depends(require_auth)])
def job_result(
    job_id: str,
    format: Literal["json", "md", "llm"] = "json",
):
    job = _get_job(job_id)
    if job["status"] != "done":
        raise HTTPException(
            status_code=409,
            detail=f"job not finished (status={job['status']})",
        )
    segments = job["segments"] or []
    if format == "md":
        title = f"Transcript — {job['filename']}"
        return PlainTextResponse(
            format_as_markdown(segments, title=title),
            media_type="text/markdown; charset=utf-8",
        )
    if format == "llm":
        return PlainTextResponse(
            format_for_llm(segments),
            media_type="text/plain; charset=utf-8",
        )
    return JSONResponse({"job_id": job_id, "segments": segments})


# --- Web UI -----------------------------------------------------------------

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def root() -> FileResponse:
        # no-cache: force revalidation so every page load passes through
        # Cloudflare Access and silently renews an expired session cookie;
        # a heuristically-cached page skips CF and its XHRs die on the stale
        # cookie with an opaque CORS "network error"
        return FileResponse(
            STATIC_DIR / "index.html",
            headers={"Cache-Control": "no-cache"},
        )
