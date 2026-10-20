"""FastAPI REST interface. Run with:  uvicorn logintel.api:app --reload"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from . import __version__
from .config import MAX_UPLOAD_BYTES
from .detectors import DETECTORS
from .exceptions import LogIntelError
from .logging_setup import get_logger
from .service import AnalysisService

log = get_logger("api")


class AnalyzeRequest(BaseModel):
    detector: str = Field("isolation_forest", description=f"One of {sorted(DETECTORS)}")
    contamination: float = Field(0.05, gt=0.0, lt=0.5)
    train_batch_id: int | None = Field(None, description="Fit on this earlier batch instead of a chronological split")
    train_fraction: float = Field(0.6, ge=0.1, le=0.9)
    normal_only: bool = False
    gap_seconds: int = Field(120, ge=1, le=86400)
    min_incident_events: int = Field(3, ge=1, le=1000, description="Smaller anomaly clusters are not reported as incidents")


class CompareRequest(AnalyzeRequest):
    detectors: list[str] | None = None


def create_app(db_path: str | None = None) -> FastAPI:
    app = FastAPI(title="Log Intelligence Platform", version=__version__,
                  description="Anomaly detection, explanation and root-cause hints for application logs.")
    service = AnalysisService(db_path)

    @app.exception_handler(LogIntelError)
    async def _domain_error(_: Request, exc: LogIntelError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content={"detail": str(exc)})

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return JSONResponse(status_code=500, content={"detail": "Internal server error."})

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__, "detectors": sorted(DETECTORS)}

    @app.post("/batches", status_code=201)
    async def upload_batch(file: UploadFile = File(...), name: str | None = Form(None)) -> dict[str, Any]:
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="File too large.")
        return await run_in_threadpool(service.ingest_bytes, data, file.filename or "upload", name)

    @app.get("/batches")
    def list_batches() -> list[dict[str, Any]]:
        return service.storage.list_batches()

    @app.get("/batches/{batch_id}")
    def get_batch(batch_id: int) -> dict[str, Any]:
        return service.storage.get_batch(batch_id)

    @app.post("/batches/{batch_id}/analyze", status_code=201)
    def analyze(batch_id: int, req: AnalyzeRequest) -> dict[str, Any]:
        return service.analyze(batch_id, **req.model_dump())

    @app.post("/batches/{batch_id}/compare", status_code=201)
    def compare(batch_id: int, req: CompareRequest) -> list[dict[str, Any]]:
        kwargs = req.model_dump()
        detectors = kwargs.pop("detectors")
        kwargs.pop("detector")
        return service.compare_detectors(batch_id, detectors, **kwargs)

    @app.get("/runs")
    def list_runs(batch_id: int | None = None) -> list[dict[str, Any]]:
        return service.storage.list_runs(batch_id)

    @app.get("/runs/{run_id}")
    def get_run(run_id: int) -> dict[str, Any]:
        return service.storage.get_run(run_id)

    @app.get("/runs/{run_id}/findings")
    def findings(run_id: int, service_name: str | None = Query(None, alias="service"), level: str | None = None,
                 min_score: float | None = Query(None, ge=0.0, le=1.0), limit: int = Query(100, ge=1, le=1000),
                 offset: int = Query(0, ge=0)) -> dict[str, Any]:
        service.storage.get_run(run_id)
        return {"total": service.storage.count_findings(run_id),
                "items": service.storage.get_findings(run_id, service_name, level, min_score, limit, offset)}

    @app.get("/runs/{run_id}/incidents")
    def incidents(run_id: int) -> list[dict[str, Any]]:
        service.storage.get_run(run_id)
        return service.storage.get_incidents(run_id)

    @app.get("/runs/{run_id}/history")
    def history(run_id: int) -> dict[str, Any]:
        return service.history_comparison(run_id)

    @app.get("/runs/{run_id}/report")
    def report(run_id: int, format: str = Query("json")) -> Response:
        content, media = service.report(run_id, format)
        ext = {"text/markdown": "md", "text/csv": "csv", "application/json": "json"}[media]
        return Response(content, media_type=media,
                        headers={"Content-Disposition": f'attachment; filename="run_{run_id}.{ext}"'})

    return app


app = create_app()
