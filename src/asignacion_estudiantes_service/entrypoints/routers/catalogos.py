from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from asignacion_estudiantes_service.adapters.db.session import get_session
from asignacion_estudiantes_service.domain.models import Clinica, Estudiante
from asignacion_estudiantes_service.domain.schemas import ClinicaOut, EstudianteOut

router = APIRouter(prefix="/catalogos", tags=["catalogos"])


@router.get("/clinicas", response_model=list[ClinicaOut])
def listar_clinicas(session: Session = Depends(get_session)):
    return list(session.scalars(select(Clinica).order_by(Clinica.nombre)))


@router.get("/estudiantes", response_model=list[EstudianteOut])
def listar_estudiantes(session: Session = Depends(get_session)):
    return list(session.scalars(select(Estudiante).order_by(Estudiante.id)))
