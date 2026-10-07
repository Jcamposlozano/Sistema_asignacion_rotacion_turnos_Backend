from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from asignacion_estudiantes_service.adapters.db.session import get_session
from asignacion_estudiantes_service.application.analysis_service import obtener_analisis_asignacion
from asignacion_estudiantes_service.application.asignacion_service import (
    AsignacionNotFoundError,
    crear_ejecucion_desde_matriz,
    ejecutar_asignacion,
    limpiar_resultados_huerfanos,
    listar_ejecuciones_parametria,
    listar_resultados,
    obtener_ejecucion,
    obtener_ultima_ejecucion_parametria,
)
from asignacion_estudiantes_service.application.diagnostic_service import obtener_diagnostico_asignacion
from asignacion_estudiantes_service.application.file_import_service import (
    ArchivoImportError,
    leer_matriz_archivo,
)
from asignacion_estudiantes_service.application.optimization_service import (
    OptimizacionError,
    optimizar_cupos_parametria,
    optimizar_y_validar_parametria,
)
from asignacion_estudiantes_service.application.parametria_service import ParametriaError
from asignacion_estudiantes_service.domain.schemas import (
    AsignacionEjecucionOut,
    AsignacionOut,
    DiagnosticoAsignacionOut,
    EjecutarAsignacionOut,
    LimpiezaResultadosOut,
    MatrizAsignacionIn,
    OptimizacionCuposOut,
    OptimizacionParametriaOut,
    OptimizarParametriaIn,
)

router = APIRouter(prefix="/asignaciones", tags=["asignaciones"])


@router.post("/parametrias/{parametria_id}/ejecutar", response_model=EjecutarAsignacionOut)
def ejecutar(
    parametria_id: int,
    max_intentos: int = Query(default=20, ge=1, le=20),
    session: Session = Depends(get_session),
):
    try:
        ejecucion = ejecutar_asignacion(session, parametria_id, max_intentos=max_intentos)
    except AsignacionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return EjecutarAsignacionOut(
        ejecucion_id=ejecucion.id,
        parametria_id=ejecucion.parametria_id,
        estado=ejecucion.estado,
        total_estudiantes=ejecucion.total_estudiantes,
        total_asignaciones=ejecucion.total_asignaciones,
        total_pendientes=ejecucion.total_pendientes,
        mensaje=ejecucion.mensaje,
    )


@router.get("/parametrias/{parametria_id}/ultima", response_model=AsignacionEjecucionOut)
def ultima_ejecucion(parametria_id: int, session: Session = Depends(get_session)):
    ejecucion = obtener_ultima_ejecucion_parametria(session, parametria_id)
    if ejecucion is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La parametría no tiene ejecuciones guardadas",
        )
    return ejecucion


@router.get("/parametrias/{parametria_id}/ejecuciones", response_model=list[AsignacionEjecucionOut])
def ejecuciones_parametria(parametria_id: int, session: Session = Depends(get_session)):
    return listar_ejecuciones_parametria(session, parametria_id)


@router.post("/parametrias/{parametria_id}/matriz", response_model=AsignacionEjecucionOut)
def cargar_matriz_ajustada(
    parametria_id: int,
    payload: MatrizAsignacionIn,
    session: Session = Depends(get_session),
):
    try:
        return crear_ejecucion_desde_matriz(session, parametria_id, payload)
    except AsignacionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.post("/parametrias/{parametria_id}/matriz-archivo", response_model=AsignacionEjecucionOut)
async def cargar_matriz_ajustada_archivo(
    parametria_id: int,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    content = await file.read()
    try:
        payload = leer_matriz_archivo(file.filename or "", content)
        return crear_ejecucion_desde_matriz(session, parametria_id, payload)
    except AsignacionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (ArchivoImportError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.get("/ejecuciones/{ejecucion_id}", response_model=AsignacionEjecucionOut)
def estado(ejecucion_id: int, session: Session = Depends(get_session)):
    ejecucion = obtener_ejecucion(session, ejecucion_id)
    if ejecucion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ejecución no encontrada")
    return ejecucion


@router.get("/ejecuciones/{ejecucion_id}/resultados", response_model=list[AsignacionOut])
def resultados(ejecucion_id: int, session: Session = Depends(get_session)):
    if obtener_ejecucion(session, ejecucion_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ejecución no encontrada")
    return listar_resultados(session, ejecucion_id)


@router.get("/ejecuciones/{ejecucion_id}/analisis")
def analisis(ejecucion_id: int, session: Session = Depends(get_session)):
    data = obtener_analisis_asignacion(session, ejecucion_id)
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ejecución no encontrada")
    return data


@router.get("/ejecuciones/{ejecucion_id}/diagnostico", response_model=DiagnosticoAsignacionOut)
def diagnostico(ejecucion_id: int, session: Session = Depends(get_session)):
    data = obtener_diagnostico_asignacion(session, ejecucion_id)
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ejecución no encontrada")
    return data


@router.delete("/huerfanas", response_model=LimpiezaResultadosOut)
def limpiar_huerfanas(session: Session = Depends(get_session)):
    return limpiar_resultados_huerfanos(session)


@router.post("/parametrias/{parametria_id}/optimizar-cupos", response_model=OptimizacionCuposOut)
def optimizar_cupos(parametria_id: int, session: Session = Depends(get_session)):
    try:
        return optimizar_cupos_parametria(session, parametria_id)
    except OptimizacionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/parametrias/{parametria_id}/optimizar-parametria",
    response_model=OptimizacionParametriaOut,
)
def optimizar_parametria(
    parametria_id: int,
    payload: OptimizarParametriaIn,
    session: Session = Depends(get_session),
):
    try:
        return optimizar_y_validar_parametria(session, parametria_id, payload)
    except OptimizacionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ParametriaError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
