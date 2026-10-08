from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from asignacion_estudiantes_service.application.assignment_engine import (
    AssignmentError,
    EngineResult,
    run_assignment,
)
from asignacion_estudiantes_service.application.parametria_service import (
    obtener_parametria_completa,
)
from asignacion_estudiantes_service.domain.models import (
    Asignacion,
    AsignacionEjecucion,
    Clinica,
    Combinacion,
    DistribucionPeriodo,
    Parametria,
    ParametriaEstudiante,
    ParametriaInstitucion,
    Restriccion,
)
from asignacion_estudiantes_service.domain.schemas import MatrizAsignacionIn, limpiar_texto


class AsignacionNotFoundError(ValueError):
    pass


MAX_INTENTOS_ASIGNACION = 20


def ejecutar_asignacion(
    session: Session, parametria_id: int, max_intentos: int = MAX_INTENTOS_ASIGNACION
) -> AsignacionEjecucion:
    parametria = obtener_parametria_completa(session, parametria_id)
    if parametria is None:
        raise AsignacionNotFoundError(f"No existe la parametría {parametria_id}")

    max_intentos = max(1, min(max_intentos, MAX_INTENTOS_ASIGNACION))
    best_result: EngineResult | None = None
    intentos_ejecutados = 0
    last_error = ""

    try:
        for intento in range(1, max_intentos + 1):
            intentos_ejecutados = intento
            try:
                result = run_assignment(parametria)
            except AssignmentError as exc:
                last_error = str(exc)
                continue

            if best_result is None or result.total_pendientes < best_result.total_pendientes:
                best_result = result

            if result.total_pendientes == 0:
                break

        if best_result is None:
            raise AssignmentError(last_error or "No fue posible generar una asignación.")

        ejecucion = AsignacionEjecucion(
            parametria_id=parametria.id,
            estado="COMPLETADA",
            total_estudiantes=best_result.total_estudiantes,
            total_asignaciones=best_result.total_asignaciones,
            total_pendientes=best_result.total_pendientes,
            mensaje=(
                f"Mejor resultado seleccionado entre {intentos_ejecutados} "
                f"intento(s), máximo configurado {max_intentos}."
            ),
        )
        session.add(ejecucion)
        session.flush()

        for row in best_result.rows:
            session.add(
                Asignacion(
                    ejecucion_id=ejecucion.id,
                    parametria_id=parametria.id,
                    estudiante_id=row.estudiante_id,
                    periodo=row.periodo,
                    especialidad=row.especialidad,
                    clinica_id=row.clinica_id,
                    institucion=row.institucion,
                    pendiente=row.pendiente,
                )
            )
    except AssignmentError as exc:
        ejecucion = AsignacionEjecucion(
            parametria_id=parametria.id,
            estado="ERROR",
            mensaje=str(exc),
        )
        session.add(ejecucion)

    session.commit()
    session.refresh(ejecucion)
    return ejecucion


def obtener_ejecucion(session: Session, ejecucion_id: int) -> AsignacionEjecucion | None:
    return session.scalar(select(AsignacionEjecucion).where(AsignacionEjecucion.id == ejecucion_id))


def obtener_ultima_ejecucion_parametria(
    session: Session, parametria_id: int
) -> AsignacionEjecucion | None:
    return session.scalar(
        select(AsignacionEjecucion)
        .where(
            AsignacionEjecucion.parametria_id == parametria_id,
            AsignacionEjecucion.total_asignaciones > 0,
        )
        .order_by(AsignacionEjecucion.id.desc())
        .limit(1)
    )


def listar_ejecuciones_parametria(session: Session, parametria_id: int) -> list[AsignacionEjecucion]:
    return list(
        session.scalars(
            select(AsignacionEjecucion)
            .where(
                AsignacionEjecucion.parametria_id == parametria_id,
                AsignacionEjecucion.total_asignaciones > 0,
            )
            .order_by(AsignacionEjecucion.id.desc())
        )
    )


def listar_resultados(session: Session, ejecucion_id: int) -> list[Asignacion]:
    return list(
        session.scalars(
            select(Asignacion)
            .where(Asignacion.ejecucion_id == ejecucion_id)
            .options(selectinload(Asignacion.estudiante))
            .order_by(Asignacion.estudiante_id, Asignacion.periodo)
        )
    )


def crear_ejecucion_desde_matriz(
    session: Session, parametria_id: int, payload: MatrizAsignacionIn
) -> AsignacionEjecucion:
    parametria = obtener_parametria_completa(session, parametria_id)
    if parametria is None:
        raise AsignacionNotFoundError(f"No existe la parametría {parametria_id}")

    estudiantes_parametria = {item.estudiante_id for item in parametria.estudiantes}
    clinicas = {
        limpiar_texto(clinica.nombre): clinica
        for clinica in session.scalars(select(Clinica))
    }
    periodos_esperados = set(range(1, parametria.numero_periodos + 1))
    filas_por_estudiante: dict[str, set[int]] = {}
    asignaciones: list[Asignacion] = []
    total_pendientes = 0

    for fila in payload.filas:
        estudiante_id = str(fila.estudiante_id).strip()
        if estudiante_id not in estudiantes_parametria:
            raise ValueError(
                f"El estudiante {estudiante_id} no pertenece a la parametría {parametria_id}"
            )
        if fila.periodo not in periodos_esperados:
            raise ValueError(
                f"El periodo {fila.periodo} no es válido para una parametría de "
                f"{parametria.numero_periodos} periodos"
            )
        periodos = filas_por_estudiante.setdefault(estudiante_id, set())
        if fila.periodo in periodos:
            raise ValueError(
                f"El estudiante {estudiante_id} tiene el periodo {fila.periodo} repetido"
            )
        periodos.add(fila.periodo)

        institucion = limpiar_texto(fila.institucion)
        especialidad = limpiar_texto(fila.especialidad)
        pendiente = not institucion or not especialidad or institucion == "PENDIENTE"
        if pendiente:
            institucion = "PENDIENTE"
        clinica = clinicas.get(institucion)
        if not pendiente and clinica is None:
            raise ValueError(f"La institución {fila.institucion} no existe en la parametría/catalogo")
        if pendiente:
            total_pendientes += 1

        asignaciones.append(
            Asignacion(
                parametria_id=parametria.id,
                estudiante_id=estudiante_id,
                periodo=fila.periodo,
                especialidad=especialidad or "PENDIENTE",
                clinica_id=None if pendiente else clinica.id,
                institucion=institucion,
                pendiente=pendiente,
            )
        )

    for estudiante_id in estudiantes_parametria:
        faltantes = periodos_esperados - filas_por_estudiante.get(estudiante_id, set())
        if faltantes:
            raise ValueError(
                f"El estudiante {estudiante_id} no tiene todos los periodos. "
                f"Faltan: {', '.join(str(item) for item in sorted(faltantes))}"
            )

    ejecucion = AsignacionEjecucion(
        parametria_id=parametria.id,
        estado="AJUSTADA_MANUALMENTE",
        total_estudiantes=len(estudiantes_parametria),
        total_asignaciones=len(asignaciones),
        total_pendientes=total_pendientes,
        mensaje=payload.mensaje or "Malla cargada desde archivo ajustado por usuario.",
    )
    session.add(ejecucion)
    session.flush()
    for asignacion in asignaciones:
        asignacion.ejecucion_id = ejecucion.id
        session.add(asignacion)

    session.commit()
    session.refresh(ejecucion)
    return ejecucion


def limpiar_ejecuciones_parametria(session: Session, parametria_id: int) -> None:
    ejecuciones = list(
        session.scalars(
            select(AsignacionEjecucion)
            .where(AsignacionEjecucion.parametria_id == parametria_id)
            .options(selectinload(AsignacionEjecucion.asignaciones))
        )
    )
    for ejecucion in ejecuciones:
        session.execute(delete(Asignacion).where(Asignacion.ejecucion_id == ejecucion.id))
        session.delete(ejecucion)
    session.commit()


def limpiar_resultados_huerfanos(session: Session) -> dict[str, int]:
    parametria_ids = select(Parametria.id)
    detalles_eliminados = 0
    for model in (
        Restriccion,
        Combinacion,
        DistribucionPeriodo,
        ParametriaInstitucion,
        ParametriaEstudiante,
    ):
        result = session.execute(delete(model).where(model.parametria_id.not_in(parametria_ids)))
        detalles_eliminados += result.rowcount or 0

    ejecuciones_huerfanas = list(
        session.scalars(
            select(AsignacionEjecucion.id).where(
                AsignacionEjecucion.parametria_id.not_in(parametria_ids)
            )
        )
    )
    asignaciones_huerfanas_por_parametria = session.execute(
        delete(Asignacion).where(Asignacion.parametria_id.not_in(parametria_ids))
    ).rowcount
    asignaciones_huerfanas_por_ejecucion = 0
    for ejecucion_id in ejecuciones_huerfanas:
        result = session.execute(delete(Asignacion).where(Asignacion.ejecucion_id == ejecucion_id))
        asignaciones_huerfanas_por_ejecucion += result.rowcount or 0

    ejecuciones_result = session.execute(
        delete(AsignacionEjecucion).where(AsignacionEjecucion.id.in_(ejecuciones_huerfanas))
    )
    session.commit()
    return {
        "ejecuciones_eliminadas": ejecuciones_result.rowcount or 0,
        "asignaciones_eliminadas": (asignaciones_huerfanas_por_parametria or 0)
        + asignaciones_huerfanas_por_ejecucion,
        "detalles_parametria_eliminados": detalles_eliminados,
    }


def listar_parametrias(session: Session) -> list[Parametria]:
    return list(session.scalars(select(Parametria).order_by(Parametria.id.desc())))
