"""FastAPI application — KYB Fund EI platform."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import data_loader
from api.routers import admin, bles, copilot, dashboard, documents, evals, funds, reports, suggestions

MOCK: bool = os.getenv("MOCK", "true").lower() == "true"


@asynccontextmanager
async def lifespan(app: FastAPI):
    data_loader.load_all()
    yield


app = FastAPI(
    title="Fund EI — KYB Compliance Platform",
    version="1.0.0",
    lifespan=lifespan,
)

_default_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
_extra_origins = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_default_origins + _extra_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard.router, prefix="/api")
app.include_router(funds.router, prefix="/api")
app.include_router(bles.router, prefix="/api")
app.include_router(suggestions.router, prefix="/api")
app.include_router(copilot.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(evals.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(documents.router, prefix="/api")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "mock": MOCK, "funds_loaded": len(data_loader.ALL_FUNDS_LIST)}
