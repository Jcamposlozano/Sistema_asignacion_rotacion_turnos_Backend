from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from asignacion_estudiantes_service.adapters.db.session import init_db
from asignacion_estudiantes_service.entrypoints.routers import (
    asignaciones,
    catalogos,
    dashboard,
    parametrias,
)
from asignacion_estudiantes_service.shared.config import load_config

cfg = load_config()
SERVICE_NAME = cfg.get("project", {}).get("name", "asignacion-estudiantes-service")
app = FastAPI(title=SERVICE_NAME, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg.get("service", {}).get("cors_origins", []),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(parametrias.router)
app.include_router(asignaciones.router)
app.include_router(catalogos.router)
app.include_router(dashboard.router)


@app.on_event("startup")
def startup():
    init_db()


@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME}
