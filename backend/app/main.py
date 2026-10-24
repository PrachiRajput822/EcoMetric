"""EcoMetric HTTP API and static frontend."""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import FRONTEND_DIR, get_settings
from .data.store import DatasetError, list_samples, store
from .pipeline import Pipeline
from .verify import audit

VERSION = "1.0.0"
log = logging.getLogger("ecometric")

app = FastAPI(title="EcoMetric API", version=VERSION, docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
pipeline = Pipeline()

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob:; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("Content-Security-Policy", CSP)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(DatasetError)
async def dataset_error(_: Request, exc: DatasetError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    log.exception("Unhandled error")
    return JSONResponse(status_code=500, content={"detail": "Something went wrong on the server. Please try again."})


class SampleRequest(BaseModel):
    sample_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")


class AskRequest(BaseModel):
    dataset_id: str = Field(pattern=r"^[a-f0-9]{12}$")
    question: str = Field(min_length=2, max_length=500)
    lang: Literal["en", "hi"] = "en"
    mode: Literal["auto", "gemini", "ollama", "rules"] = "auto"


@app.get("/api/status")
def status() -> dict[str, Any]:
    s = get_settings()
    return {"version": VERSION, **pipeline.status(), "limits": {"max_upload_mb": s.max_upload_mb, "max_rows": s.max_rows,
                                                                  "max_columns": s.max_columns}}


@app.get("/api/samples")
def samples() -> list[dict[str, Any]]:
    return list_samples()


@app.post("/api/datasets/sample")
def load_sample(req: SampleRequest) -> dict[str, Any]:
    return store.load_sample(req.sample_id).summary()


@app.post("/api/datasets/upload")
async def upload(file: UploadFile = File(...)) -> dict[str, Any]:
    limit = int(get_settings().max_upload_mb * 1024 * 1024)
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise DatasetError(f"File is larger than {get_settings().max_upload_mb:g} MB.")
    ds = await run_in_threadpool(store.load_upload, file.filename or "upload.csv", content)
    return ds.summary()


@app.get("/api/datasets/{dataset_id}")
def get_dataset(dataset_id: str) -> dict[str, Any]:
    if len(dataset_id) != 12:
        raise HTTPException(404, "Dataset not found.")
    return store.get(dataset_id).summary()


@app.post("/api/ask")
def ask(req: AskRequest) -> dict[str, Any]:
    ds = store.get(req.dataset_id)
    return pipeline.ask(ds, req.question, req.lang, req.mode)


@app.get("/api/audit")
def audit_log(limit: int = 20) -> list[dict[str, Any]]:
    return audit.recent(max(1, min(limit, 100)))


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
