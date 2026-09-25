from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from asignacion_estudiantes_service.adapters.db.session import get_session
from asignacion_estudiantes_service.application.dashboard_service import obtener_resumen_gerencial

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/resumen-gerencial")
def resumen_gerencial(session: Session = Depends(get_session)) -> dict[str, Any]:
    return obtener_resumen_gerencial(session)
