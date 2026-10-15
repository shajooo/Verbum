"""
Verbum – Transcription Service
FastAPI HTTP / SSE sidecar.

Improvements over initial version:
- lifespan startup event (replaces deprecated on_event)
- Model warm-up & download progress via SSE
- Correct multipart UploadFile detection (hasattr check)
- Engine & job state are module-level singletons (not re-imported per request)
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import json
import os
import secrets
import shutil
import socket
import sys
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import uvicorn

from engine import (
    AVAILABLE_MODELS,
    DEFAULT_MODEL_NAME,
    TranscriptionCancelledError,
    TranscriptionEngine,
    download_model,
    get_installed_models,
    is_cuda_available,
    is_model_installed,
)

# ---------------------------------------------------------------------------
# Globals (set before server start)
# ---------------------------------------------------------------------------

SELECTED_PORT: int = 0
AUTH_TOKEN: str = ""

engine = TranscriptionEngine()

# ---------------------------------------------------------------------------
# Lifespan – emit handshake once server is bound and ready
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    print(f"VERBUM_BACKEND_READY port={SELECTED_PORT} token={AUTH_TOKEN}", flush=True)
    yield


app = FastAPI(
    title="Verbum Transcription Service",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def verify_token(authorization: Optional[str] = Header(None)) -> str:
    if not AUTH_TOKEN:
        return ""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Missing Authorization header"},
        )
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or parts[1] != AUTH_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Invalid authentication token"},
        )
    return authorization

# ---------------------------------------------------------------------------
# Job Management
# ---------------------------------------------------------------------------

class Job:
    def __init__(
        self,
        job_id: str,
        audio_path: str,
        model_name: str,
        language: Optional[str],
        vad: bool,
        prompt: Optional[str],
        is_temp_file: bool = False,
    ):
        self.job_id = job_id
        self.audio_path = audio_path
        self.model_name = model_name
        self.language = language
        self.vad = vad
        self.prompt = prompt
        self.is_temp_file = is_temp_file
        self.cancelled = False
        self.done = False
        self.task: Optional[asyncio.Task] = None
        self.events: asyncio.Queue = asyncio.Queue()

    async def emit(self, event_type: str, data: Dict[str, Any]) -> None:
        await self.events.put({"event": event_type, "job_id": self.job_id, **data})


CURRENT_JOB: Optional[Job] = None
JOB_HISTORY: Dict[str, Job] = {}
JOB_LOCK = asyncio.Lock()

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ModelSelectRequest(BaseModel):
    name: str

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def get_health(_token: str = Depends(verify_token)) -> Dict[str, Any]:
    return {
        "status": "ok",
        "device": "cuda" if is_cuda_available() else "cpu",
        "current_model": engine.current_model_name,
        "models_installed": get_installed_models(),
        "models_available": list(AVAILABLE_MODELS.keys()),
        "cuda_available": is_cuda_available(),
    }


@app.post("/model/select")
def select_model(req: ModelSelectRequest, _token: str = Depends(verify_token)) -> Dict[str, Any]:
    name = req.name.lower()
    if name not in AVAILABLE_MODELS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_MODEL", "message": f"Unknown model name '{name}'"},
        )
    if not is_model_installed(name):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NO_MODEL", "message": f"Model '{name}' is not downloaded yet"},
        )
    try:
        info = engine.load_model(name)
        return {
            "status": "ready",
            "model": info["model"],
            "device": info["device"],
            "compute_type": info["compute_type"],
            "cuda_fallback": info.get("cuda_fallback", False),
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "MODEL_LOAD_FAILED", "message": str(e)},
        )


@app.post("/model/download")
async def download_model_endpoint(req: ModelSelectRequest, _token: str = Depends(verify_token)) -> StreamingResponse:
    name = req.name.lower()
    if name not in AVAILABLE_MODELS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_MODEL", "message": f"Unknown model name '{name}'"},
        )

    q: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def sync_progress(info: Dict[str, Any]) -> None:
        asyncio.run_coroutine_threadsafe(q.put(info), loop)

    async def run_download() -> None:
        try:
            await loop.run_in_executor(None, download_model, name, sync_progress)
            await q.put({"done": True, "status": "Download complete", "percent": 100.0})
        except Exception as e:
            await q.put({"error": str(e), "code": "MODEL_DOWNLOAD_FAILED"})

    asyncio.create_task(run_download())

    async def event_generator() -> AsyncGenerator[str, None]:
        while True:
            item = await q.get()
            yield f"data: {json.dumps(item)}\n\n"
            if item.get("done") or item.get("error"):
                break

    return StreamingResponse(event_generator(), media_type="text/event-stream")


async def run_transcription_worker(job: Job) -> None:
    loop = asyncio.get_running_loop()
    try:
        await job.emit("queued", {})

        if job.cancelled:
            raise TranscriptionCancelledError("Cancelled before model load")

        if engine.current_model_name != job.model_name or engine.current_model is None:
            await job.emit("loading_model", {"model": job.model_name})
            await loop.run_in_executor(None, engine.load_model, job.model_name)

        if job.cancelled:
            raise TranscriptionCancelledError("Cancelled before decode")

        await job.emit("decoding_audio", {})

        def on_prog(fraction: float) -> None:
            if job.cancelled:
                return
            pct = round(fraction * 100, 1)
            asyncio.run_coroutine_threadsafe(
                job.emit("transcribing", {"percent": pct}),
                loop,
            )

        def cancel_check() -> bool:
            return job.cancelled

        result = await loop.run_in_executor(
            None,
            engine.transcribe,
            job.audio_path,
            job.language,
            job.vad,
            job.prompt,
            on_prog,
            cancel_check,
        )

        if job.cancelled:
            await job.emit("cancelled", {})
        else:
            await job.emit("done", {"result": result})

    except (TranscriptionCancelledError, asyncio.CancelledError):
        await job.emit("cancelled", {})
    except Exception as e:
        msg = str(e)
        code = "BAD_AUDIO" if ("audio" in msg.lower() or "decode" in msg.lower()) else "INTERNAL"
        await job.emit("error", {"code": code, "message": msg})
    finally:
        job.done = True
        if job.is_temp_file and os.path.isfile(job.audio_path):
            try:
                os.remove(job.audio_path)
            except Exception:
                pass
        global CURRENT_JOB
        async with JOB_LOCK:
            if CURRENT_JOB == job:
                CURRENT_JOB = None


@app.post("/transcribe")
async def create_transcription_job(
    request: Request,
    _token: str = Depends(verify_token),
) -> Dict[str, Any]:
    global CURRENT_JOB

    async with JOB_LOCK:
        if CURRENT_JOB is not None and not CURRENT_JOB.done:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "BUSY", "message": "Still transcribing the previous audio."},
            )

        content_type = request.headers.get("content-type", "")
        job_id = str(uuid.uuid4())

        if "multipart/form-data" in content_type:
            form = await request.form()
            file_obj = form.get("file")
            if not file_obj or not hasattr(file_obj, "file"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"code": "BAD_AUDIO", "message": "Missing 'file' in multipart form data"},
                )

            model_name = str(form.get("model") or engine.current_model_name or DEFAULT_MODEL_NAME)
            language = str(form.get("language")) if form.get("language") else None
            vad_val = form.get("vad")
            vad = False if (vad_val is not None and str(vad_val).lower() in ("false", "0")) else True
            prompt = str(form.get("prompt")) if form.get("prompt") else None

            temp_dir = os.path.join(tempfile.gettempdir(), "verbum_uploads")
            os.makedirs(temp_dir, exist_ok=True)
            suffix = os.path.splitext(file_obj.filename or "audio.wav")[1] or ".wav"
            temp_path = os.path.join(temp_dir, f"{job_id}{suffix}")

            with open(temp_path, "wb") as f_out:
                shutil.copyfileobj(file_obj.file, f_out)

            job = Job(job_id, temp_path, model_name, language, vad, prompt, is_temp_file=True)

        else:
            try:
                body = await request.json()
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"code": "BAD_REQUEST", "message": "Expected JSON with 'path' or multipart form"},
                )

            path = body.get("path")
            if not path or not os.path.isfile(path):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"code": "BAD_AUDIO", "message": f"Audio file not found: {path}"},
                )

            model_name = body.get("model") or engine.current_model_name or DEFAULT_MODEL_NAME
            language = body.get("language")
            vad = body.get("vad", True)
            prompt = body.get("prompt")

            job = Job(job_id, path, model_name, language, vad, prompt, is_temp_file=False)

        CURRENT_JOB = job
        JOB_HISTORY[job_id] = job
        job.task = asyncio.create_task(run_transcription_worker(job))

        return {"job_id": job_id, "status": "queued"}


@app.get("/events/{job_id}")
async def stream_job_events(job_id: str, _token: str = Depends(verify_token)) -> StreamingResponse:
    if job_id not in JOB_HISTORY:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": f"Job {job_id} not found"},
        )

    job = JOB_HISTORY[job_id]

    async def event_generator() -> AsyncGenerator[str, None]:
        while True:
            try:
                event = await asyncio.wait_for(job.events.get(), timeout=30.0)
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("event") in ("done", "error", "cancelled"):
                    break
            except asyncio.TimeoutError:
                yield ": ping\n\n"
                if job.done:
                    break

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/cancel/{job_id}")
async def cancel_job(job_id: str, _token: str = Depends(verify_token)) -> Dict[str, Any]:
    global CURRENT_JOB
    job = JOB_HISTORY.get(job_id)
    if job is None and CURRENT_JOB is not None:
        job = CURRENT_JOB

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": f"Job {job_id} not found"},
        )

    job.cancelled = True
    job.done = True

    # Immediately release CURRENT_JOB so subsequent recordings are not blocked with 409 BUSY
    async with JOB_LOCK:
        if CURRENT_JOB == job:
            CURRENT_JOB = None

    # Emit cancelled event to SSE stream
    await job.emit("cancelled", {})

    # Cancel background worker task if active
    if job.task and not job.task.done():
        job.task.cancel()

    # Clean up temp audio file if present
    if job.is_temp_file and os.path.isfile(job.audio_path):
        try:
            os.remove(job.audio_path)
        except Exception:
            pass

    return {"status": "cancelled", "job_id": job.job_id}

# ---------------------------------------------------------------------------
# Server startup helpers
# ---------------------------------------------------------------------------

def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_service(port: int = 0, token: Optional[str] = None) -> None:
    global AUTH_TOKEN, SELECTED_PORT
    SELECTED_PORT = port if port > 0 else find_free_port()
    AUTH_TOKEN = token if token else secrets.token_hex(16)

    config = uvicorn.Config(
        app=app,
        host="127.0.0.1",
        port=SELECTED_PORT,
        log_level="warning",
        access_log=False,
    )
    uvicorn.Server(config).run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verbum Transcription Service")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--token", type=str, default="")
    args = parser.parse_args()
    start_service(port=args.port, token=args.token)
