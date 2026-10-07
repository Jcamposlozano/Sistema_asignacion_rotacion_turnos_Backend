from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from asignacion_estudiantes_service.adapters.db.session import get_session
from asignacion_estudiantes_service.application.asignacion_service import listar_parametrias
from asignacion_estudiantes_service.application.file_import_service import (
    ArchivoImportError,
    leer_estudiantes_archivo,
    leer_instituciones_archivo,
    leer_parametria_plantilla,
)
from asignacion_estudiantes_service.application.parametria_service import (
    ParametriaError,
    actualizar_parametria,
    crear_parametria,
    eliminar_parametria,
    obtener_parametria_completa,
)
from asignacion_estudiantes_service.domain.schemas import (
    EstudianteIn,
    InstitucionIn,
    ParametriaCargaIn,
    ParametriaCreadaOut,
    ParametriaResumenOut,
)

router = APIRouter(prefix="/parametrias", tags=["parametrias"])


@router.post("/importar-estudiantes", response_model=list[EstudianteIn])
async def importar_estudiantes(file: UploadFile = File(...)):
    content = await file.read()
    try:
        return leer_estudiantes_archivo(file.filename or "", content)
    except ArchivoImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.post("/importar-instituciones", response_model=list[InstitucionIn])
async def importar_instituciones(file: UploadFile = File(...)):
    content = await file.read()
    try:
        return leer_instituciones_archivo(file.filename or "", content)
    except ArchivoImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.post("/importar-plantilla", response_model=ParametriaCargaIn)
async def importar_plantilla(file: UploadFile = File(...)):
    content = await file.read()
    try:
        return leer_parametria_plantilla(file.filename or "", content)
    except ArchivoImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.post("", response_model=ParametriaCreadaOut, status_code=status.HTTP_201_CREATED)
def cargar_parametria(payload: ParametriaCargaIn, session: Session = Depends(get_session)):
    try:
        parametria = crear_parametria(session, payload)
    except ParametriaError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    return ParametriaCreadaOut(id=parametria.id, mensaje="Parametría cargada correctamente")


@router.put("/{parametria_id}", response_model=ParametriaCreadaOut)
def reemplazar_parametria(
    parametria_id: int, payload: ParametriaCargaIn, session: Session = Depends(get_session)
):
    try:
        parametria = actualizar_parametria(session, parametria_id, payload)
    except ParametriaError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    if parametria is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Parametría no encontrada"
        )
    return ParametriaCreadaOut(id=parametria.id, mensaje="Parametría actualizada correctamente")


@router.delete("/{parametria_id}", status_code=status.HTTP_204_NO_CONTENT)
def borrar_parametria(parametria_id: int, session: Session = Depends(get_session)):
    eliminada = eliminar_parametria(session, parametria_id)
    if not eliminada:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Parametría no encontrada"
        )


@router.get("", response_model=list[ParametriaResumenOut])
def listar(session: Session = Depends(get_session)):
    return listar_parametrias(session)


@router.get("/{parametria_id}")
def obtener(parametria_id: int, session: Session = Depends(get_session)):
    parametria = obtener_parametria_completa(session, parametria_id)
    if parametria is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Parametría no encontrada"
        )
    return {
        "id": parametria.id,
        "nombre": parametria.nombre,
        "asignacion": {
            "numero_periodos": parametria.numero_periodos,
            "estudiantes_aleatorio": parametria.estudiantes_aleatorio,
            "instituciones_aleatorio": parametria.instituciones_aleatorio,
            "asignacion": parametria.estrategia,
            "institucion_residual": parametria.institucion_residual,
        },
        "instituciones": [
            {
                "institucion": item.clinica.nombre,
                "especialidad": item.especialidad,
                "cantidad": item.cantidad,
            }
            for item in parametria.instituciones
        ],
        "restricciones": [
            {
                "estudiante": item.estudiante_id,
                "institucion": item.clinica.nombre,
                "especialidad": item.especialidad,
            }
            for item in parametria.restricciones
        ],
        "distribucion_periodos": [
            {"especialidad": item.especialidad, "asignacion": item.asignacion}
            for item in parametria.distribuciones
        ],
        "combinaciones": [
            {
                "especialidad_1": item.especialidad_1,
                "especialidad_2": item.especialidad_2,
                "bloque": item.bloque,
            }
            for item in parametria.combinaciones
        ],
        "estudiantes": [
            {
                "id": item.estudiante.id,
                "nombre": item.estudiante.nombre,
                "semestre": item.estudiante.semestre,
            }
            for item in parametria.estudiantes
        ],
    }
