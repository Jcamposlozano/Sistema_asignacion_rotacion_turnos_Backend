from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from asignacion_estudiantes_service.application.asignacion_service import ejecutar_asignacion
from asignacion_estudiantes_service.application.diagnostic_service import obtener_diagnostico_asignacion
from asignacion_estudiantes_service.application.parametria_service import (
    crear_parametria,
    obtener_parametria_completa,
)
from asignacion_estudiantes_service.domain.models import (
    Asignacion,
    AsignacionEjecucion,
    Combinacion,
    DistribucionPeriodo,
    Parametria,
    ParametriaEstudiante,
    ParametriaInstitucion,
    Restriccion,
)
from asignacion_estudiantes_service.domain.schemas import (
    AsignacionConfigIn,
    CombinacionIn,
    DistribucionPeriodoIn,
    EstudianteIn,
    InstitucionIn,
    OptimizarParametriaIn,
    ParametriaCargaIn,
    RestriccionIn,
    limpiar_texto,
)


class OptimizacionError(ValueError):
    pass


def optimizar_cupos_parametria(session: Session, parametria_id: int) -> dict[str, Any]:
    parametria = obtener_parametria_completa(session, parametria_id)
    if parametria is None:
        raise OptimizacionError(f"No existe la parametría {parametria_id}")

    sugerencias = _calcular_cupos_sugeridos(parametria)
    cupos_actuales = sum(item["cupo_actual"] for item in sugerencias)
    cupos_sugeridos = sum(item["cupo_sugerido"] for item in sugerencias)
    advertencias = _advertencias(parametria, sugerencias)

    return {
        "parametria_id": parametria.id,
        "fase": "3.1",
        "resultado": "CUPOS_SUGERIDOS",
        "estudiantes": len(parametria.estudiantes),
        "numero_periodos": parametria.numero_periodos,
        "cupos_totales_actuales": cupos_actuales,
        "cupos_totales_sugeridos": cupos_sugeridos,
        "reduccion_cupos": cupos_actuales - cupos_sugeridos,
        "resumen": (
            f"Se sugieren {cupos_sugeridos} cupos por periodo frente a "
            f"{cupos_actuales} configurados actualmente."
        ),
        "parametria_sugerida": sugerencias,
        "advertencias": advertencias,
    }


def optimizar_y_validar_parametria(
    session: Session, parametria_id: int, payload: OptimizarParametriaIn
) -> dict[str, Any]:
    parametria = obtener_parametria_completa(session, parametria_id)
    if parametria is None:
        raise OptimizacionError(f"No existe la parametría {parametria_id}")

    optimizacion = optimizar_cupos_parametria(session, parametria_id)
    simulated_payload = _payload_optimizado(parametria, optimizacion["parametria_sugerida"])
    temp_parametria = crear_parametria(session, simulated_payload)
    try:
        ejecucion = ejecutar_asignacion(
            session, temp_parametria.id, max_intentos=payload.max_intentos
        )
        diagnostico = obtener_diagnostico_asignacion(session, ejecucion.id)
        if diagnostico is None:
            raise OptimizacionError("No fue posible diagnosticar la parametría optimizada")

        resultado = "VALIDADO" if ejecucion.total_pendientes == 0 else "VALIDADO_CON_PENDIENTES"
        return {
            **optimizacion,
            "fase": "3.2",
            "resultado": resultado,
            "parametria_simulada_id": temp_parametria.id,
            "ejecucion_simulada_id": ejecucion.id,
            "pendientes_estimados": ejecucion.total_pendientes,
            "diagnostico": diagnostico,
            "resumen": (
                f"Parametría sugerida validada con {ejecucion.total_pendientes} "
                "pendientes estimados."
            ),
        }
    finally:
        _eliminar_parametria_temporal(session, temp_parametria.id)


def _calcular_cupos_sugeridos(parametria: Parametria) -> list[dict[str, Any]]:
    restricciones_minimas = _restricciones_minimas(parametria)
    sugerencias: list[dict[str, Any]] = []
    instituciones_por_especialidad: dict[str, list[ParametriaInstitucion]] = defaultdict(list)
    for institucion in parametria.instituciones:
        instituciones_por_especialidad[limpiar_texto(institucion.especialidad)].append(institucion)

    estudiantes = len(parametria.estudiantes)
    for distribucion in parametria.distribuciones:
        especialidad = limpiar_texto(distribucion.especialidad)
        instituciones = instituciones_por_especialidad[especialidad]
        demanda = estudiantes * distribucion.asignacion
        cupos_minimos_periodo = math.ceil(demanda / parametria.numero_periodos)
        proveedor_unico = len(instituciones) == 1
        total_objetivo = max(
            cupos_minimos_periodo,
            sum(
                restricciones_minimas.get((item.clinica.nombre, especialidad), 0)
                for item in instituciones
            ),
        )
        distribucion_cupos = _distribuir_cupos_balanceados(
            instituciones,
            total_objetivo,
            restricciones_minimas,
            especialidad,
        )
        for institucion in instituciones:
            sugerido = distribucion_cupos[institucion.clinica.nombre]
            uso_estimado = sugerido * parametria.numero_periodos
            sugerencias.append(
                {
                    "institucion": institucion.clinica.nombre,
                    "especialidad": institucion.especialidad,
                    "cupo_actual": institucion.cantidad,
                    "cupo_sugerido": sugerido,
                    "demanda_estimada": demanda,
                    "uso_estimado": uso_estimado,
                    "capacidad_actual": institucion.cantidad * parametria.numero_periodos,
                    "capacidad_sugerida": uso_estimado,
                    "proveedor_unico": proveedor_unico,
                    "razon": _razon_sugerencia(proveedor_unico, sugerido, institucion.cantidad),
                }
            )
    return sugerencias


def _restricciones_minimas(parametria: Parametria) -> dict[tuple[str, str], int]:
    distribucion = {
        limpiar_texto(item.especialidad): item.asignacion for item in parametria.distribuciones
    }
    instituciones_disponibles = {
        (item.clinica.nombre, limpiar_texto(item.especialidad))
        for item in parametria.instituciones
    }
    demanda_restringida: dict[tuple[str, str], int] = defaultdict(int)
    for restriccion in parametria.restricciones:
        institucion = restriccion.clinica.nombre
        if restriccion.especialidad:
            especialidades = [limpiar_texto(restriccion.especialidad)]
        else:
            especialidades = [
                especialidad
                for nombre, especialidad in instituciones_disponibles
                if nombre == institucion
            ]
        for especialidad in especialidades:
            demanda_restringida[(institucion, especialidad)] += distribucion.get(especialidad, 0)

    return {
        key: math.ceil(periodos / parametria.numero_periodos)
        for key, periodos in demanda_restringida.items()
    }


def _distribuir_cupos_balanceados(
    instituciones: list[ParametriaInstitucion],
    total_objetivo: int,
    restricciones_minimas: dict[tuple[str, str], int],
    especialidad: str,
) -> dict[str, int]:
    result = {
        item.clinica.nombre: restricciones_minimas.get((item.clinica.nombre, especialidad), 0)
        for item in instituciones
    }
    restantes = max(0, total_objetivo - sum(result.values()))
    ordenadas = sorted(instituciones, key=lambda item: item.clinica.nombre)
    while restantes > 0:
        objetivo = min(result.values()) if result else 0
        candidatas = [item for item in ordenadas if result[item.clinica.nombre] == objetivo]
        for item in candidatas:
            if restantes == 0:
                break
            result[item.clinica.nombre] += 1
            restantes -= 1
    return result


def _payload_optimizado(
    parametria: Parametria, sugerencias: list[dict[str, Any]]
) -> ParametriaCargaIn:
    cupos = {
        (limpiar_texto(item["institucion"]), limpiar_texto(item["especialidad"])): int(
            item["cupo_sugerido"]
        )
        for item in sugerencias
    }
    return ParametriaCargaIn(
        nombre=f"OPTIMIZACION - {parametria.nombre}",
        instituciones=[
            InstitucionIn(
                institucion=item.clinica.nombre,
                especialidad=item.especialidad,
                cantidad=cupos[(limpiar_texto(item.clinica.nombre), limpiar_texto(item.especialidad))],
            )
            for item in parametria.instituciones
        ],
        restricciones=[
            RestriccionIn(
                estudiante=item.estudiante_id,
                institucion=item.clinica.nombre,
                especialidad=item.especialidad,
            )
            for item in parametria.restricciones
        ],
        asignacion=AsignacionConfigIn(
            numero_periodos=parametria.numero_periodos,
            estudiantes_aleatorio=parametria.estudiantes_aleatorio,
            instituciones_aleatorio=parametria.instituciones_aleatorio,
            asignacion=parametria.estrategia,
            institucion_residual=parametria.institucion_residual,
        ),
        distribucion_periodos=[
            DistribucionPeriodoIn(especialidad=item.especialidad, asignacion=item.asignacion)
            for item in parametria.distribuciones
        ],
        combinaciones=[
            CombinacionIn(
                especialidad_1=item.especialidad_1,
                especialidad_2=item.especialidad_2,
                bloque=item.bloque,
            )
            for item in parametria.combinaciones
        ],
        estudiantes=[
            EstudianteIn(
                id=item.estudiante.id,
                nombre=item.estudiante.nombre,
                semestre=item.estudiante.semestre,
            )
            for item in parametria.estudiantes
        ],
    )


def _advertencias(parametria: Parametria, sugerencias: list[dict[str, Any]]) -> list[str]:
    advertencias = []
    for item in sugerencias:
        if item["proveedor_unico"]:
            advertencias.append(
                f"{item['especialidad']} solo tiene una institución disponible: {item['institucion']}."
            )
        if int(item["cupo_sugerido"]) == 0:
            advertencias.append(
                f"{item['institucion']} / {item['especialidad']} queda con cupo sugerido 0."
            )
    if parametria.combinaciones:
        advertencias.append(
            "La validación completa ejecuta los bloques X2/X4; la sugerencia inicial minimiza cupos por demanda."
        )
    return sorted(set(advertencias))


def _razon_sugerencia(proveedor_unico: bool, sugerido: int, actual: int) -> str:
    if proveedor_unico:
        return "Proveedor único para la especialidad."
    if sugerido < actual:
        return "Reducción por balance de demanda y minimización de cupos."
    if sugerido > actual:
        return "Incremento requerido por demanda mínima o restricciones."
    return "Se conserva por balance de demanda."


def _eliminar_parametria_temporal(session: Session, parametria_id: int) -> None:
    ejecuciones_ids = list(
        session.scalars(
            select(AsignacionEjecucion.id).where(AsignacionEjecucion.parametria_id == parametria_id)
        )
    )
    for ejecucion_id in ejecuciones_ids:
        session.execute(delete(Asignacion).where(Asignacion.ejecucion_id == ejecucion_id))
    session.execute(delete(AsignacionEjecucion).where(AsignacionEjecucion.parametria_id == parametria_id))
    for model in (
        Restriccion,
        Combinacion,
        DistribucionPeriodo,
        ParametriaInstitucion,
        ParametriaEstudiante,
    ):
        session.execute(delete(model).where(model.parametria_id == parametria_id))
    session.execute(delete(Parametria).where(Parametria.id == parametria_id))
    session.commit()
