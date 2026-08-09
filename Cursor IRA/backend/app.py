"""FastAPI entrypoint — Roth IRA / TVM retirement model."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .engine import calculate
from .models import CalculateRequest, CalculateResponse, HealthResponse

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(
    title="Roth IRA / TVM Retirement Model",
    version="1.0.0",
    description="Full stack: engines, tax, actuary mode, vintages, milestones, what-ifs, frontend.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/api/calculate", response_model=CalculateResponse)
def api_calculate(payload: CalculateRequest) -> CalculateResponse:
    return calculate(payload)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/style.css")
def style_css() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "style.css", media_type="text/css")


@app.get("/app.js")
def app_js() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "app.js", media_type="application/javascript")
