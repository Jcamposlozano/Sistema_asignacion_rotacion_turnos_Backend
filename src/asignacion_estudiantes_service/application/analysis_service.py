from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from sqlalchemy.orm import Session

from asignacion_estudiantes_service.application.asignacion_service import (
    listar_resultados,
    obtener_ejecucion,
)
from asignacion_estudiantes_service.application.parametria_service import (
    obtener_parametria_completa,
)
from asignacion_estudiantes_service.domain.models import Asignacion
from asignacion_estudiantes_service.domain.schemas import limpiar_texto


def obtener_analisis_asignacion(session: Session, ejecucion_id: int) -> dict[str, Any] | None:
    ejecucion = obtener_ejecucion(session, ejecucion_id)
    if ejecucion is None:
        return None

    parametria = obtener_parametria_completa(session, ejecucion.parametria_id)
    if parametria is None:
        return None

    resultados = listar_resultados(session, ejecucion_id)
    estudiantes_ids = [item.estudiante_id for item in parametria.estudiantes]
    total_teorico = len(estudiantes_ids) * parametria.numero_periodos
    total_pendientes = sum(1 for item in resultados if item.pendiente)
    total_real = total_teorico - total_pendientes

    return {
        "resumen": {
            "numero_periodos": parametria.numero_periodos,
            "estrategia": parametria.estrategia,
            "institucion_residual": parametria.institucion_residual,
            "estudiantes": len(estudiantes_ids),
            "bloques_configurados": len(parametria.combinaciones),
            "asignaciones_teoricas": total_teorico,
            "asignaciones_realizadas": total_real,
            "asignaciones_pendientes": total_pendientes,
            "cobertura_global": _ratio(total_real, total_teorico),
        },
        "resumen_especialidad": _resumen_especialidad(parametria, resultados, len(estudiantes_ids)),
        "bloques": _analisis_bloques(parametria, resultados, estudiantes_ids),
        "restricciones": _analisis_restricciones(parametria, resultados),
        "ocupacion": _detalle_ocupacion(parametria, resultados),
        "pendientes": [
            {
                "id": item.estudiante_id,
                "periodo": item.periodo,
                "especialidad": item.especialidad,
                "estado": "REQUIERE ASIGNACION MANUAL",
            }
            for item in resultados
            if item.pendiente
        ],
    }


def _resumen_especialidad(parametria, resultados: list[Asignacion], total_estudiantes: int):
    rows = []
    for distribucion in parametria.distribuciones:
        demanda = total_estudiantes * distribucion.asignacion
        capacidad = (
            sum(
                item.cantidad
                for item in parametria.instituciones
                if _eq(item.especialidad, distribucion.especialidad)
            )
            * parametria.numero_periodos
        )
        asignado = sum(
            1
            for item in resultados
            if not item.pendiente and _eq(item.especialidad, distribucion.especialidad)
        )
        pendiente = demanda - asignado
        rows.append(
            {
                "especialidad": distribucion.especialidad,
                "asignacion_estudiante": distribucion.asignacion,
                "demanda_teorica": demanda,
                "capacidad_total": capacidad,
                "asignado": asignado,
                "pendiente": pendiente,
                "cupos_sin_usar": max(0, capacidad - asignado),
                "cobertura": _ratio(asignado, demanda),
                "estado": "CUBIERTO" if pendiente == 0 else "REQUIERE REVISION",
            }
        )
    return rows


def _analisis_bloques(parametria, resultados: list[Asignacion], estudiantes_ids: list[str]):
    by_student = _rows_by_student(resultados)
    rows = []
    for combinacion in parametria.combinaciones:
        cumplen = misma = distinta = con_pendiente = 0
        for estudiante_id in estudiantes_ids:
            inicio = _buscar_inicio_bloque(by_student[estudiante_id], combinacion)
            if inicio == 0:
                continue
            cumplen += 1
            bloque_rows = [
                row
                for row in by_student[estudiante_id]
                if inicio <= row.periodo <= inicio + combinacion.longitud_bloque - 1
            ]
            if any(row.pendiente for row in bloque_rows):
                con_pendiente += 1
            elif len({limpiar_texto(row.institucion) for row in bloque_rows}) == 1:
                misma += 1
            else:
                distinta += 1

        rows.append(
            {
                "especialidad_1": combinacion.especialidad_1,
                "especialidad_2": combinacion.especialidad_2,
                "tipo_bloque": f"X{combinacion.longitud_bloque}",
                "estudiantes": len(estudiantes_ids),
                "cumplen_consecutividad": cumplen,
                "misma_institucion": misma,
                "institucion_diferente": distinta,
                "con_pendiente": con_pendiente,
                "cumplimiento": _ratio(cumplen, len(estudiantes_ids)),
            }
        )
    return rows


def _analisis_restricciones(parametria, resultados: list[Asignacion]):
    by_student = _rows_by_student(resultados)
    rows = []
    for restriccion in parametria.restricciones:
        applicable = [
            row
            for row in by_student[restriccion.estudiante_id]
            if not restriccion.especialidad or _eq(row.especialidad, restriccion.especialidad)
        ]
        en_preferida = en_proveedor_unico = en_residual = otras = pendientes = 0
        for row in applicable:
            if row.pendiente:
                pendientes += 1
            elif _eq(row.institucion, restriccion.clinica.nombre):
                en_preferida += 1
            elif _es_proveedor_unico(parametria, row.especialidad, row.institucion):
                en_proveedor_unico += 1
            elif _is_residual(row.institucion, parametria.institucion_residual):
                en_residual += 1
            else:
                otras += 1

        rows.append(
            {
                "id": restriccion.estudiante_id,
                "institucion_preferida": restriccion.clinica.nombre,
                "especialidad": restriccion.especialidad or "TODAS",
                "practicas_aplicables": len(applicable),
                "en_preferida": en_preferida,
                "proveedor_unico": en_proveedor_unico,
                "en_residual": en_residual,
                "otras_instituciones": otras,
                "pendientes": pendientes,
                "cumplimiento_preferida": _ratio(en_preferida, len(applicable)),
                "estado": _estado_restriccion(otras, pendientes, en_proveedor_unico, en_residual),
            }
        )
    return rows


def _detalle_ocupacion(parametria, resultados: list[Asignacion]):
    assigned_counter = Counter(
        (row.clinica_id, limpiar_texto(row.especialidad), row.periodo)
        for row in resultados
        if not row.pendiente and row.clinica_id is not None
    )
    rows = []
    for institucion in parametria.instituciones:
        for periodo in range(1, parametria.numero_periodos + 1):
            asignados = assigned_counter[
                (institucion.clinica_id, limpiar_texto(institucion.especialidad), periodo)
            ]
            disponibles = institucion.cantidad - asignados
            rows.append(
                {
                    "institucion": institucion.clinica.nombre,
                    "especialidad": institucion.especialidad,
                    "periodo": periodo,
                    "capacidad": institucion.cantidad,
                    "asignados": asignados,
                    "disponibles": disponibles,
                    "ocupacion": _ratio(asignados, institucion.cantidad),
                    "tipo": "RESIDUAL"
                    if _is_residual(institucion.clinica.nombre, parametria.institucion_residual)
                    else "NORMAL",
                    "estado": _estado_ocupacion(institucion.cantidad, asignados),
                }
            )
    return rows


def _rows_by_student(resultados: list[Asignacion]) -> dict[str, list[Asignacion]]:
    grouped: dict[str, list[Asignacion]] = defaultdict(list)
    for row in resultados:
        grouped[row.estudiante_id].append(row)
    for rows in grouped.values():
        rows.sort(key=lambda item: item.periodo)
    return grouped


def _buscar_inicio_bloque(rows: list[Asignacion], combinacion) -> int:
    by_period = {row.periodo: row.especialidad for row in rows}
    if combinacion.longitud_bloque == 4:
        for periodo in range(1, max(by_period.keys(), default=0) - 2):
            if all(
                _eq(by_period.get(p), combinacion.especialidad_1)
                for p in range(periodo, periodo + 4)
            ):
                return periodo
        return 0

    for periodo in range(1, max(by_period.keys(), default=0)):
        a = by_period.get(periodo)
        b = by_period.get(periodo + 1)
        if (_eq(a, combinacion.especialidad_1) and _eq(b, combinacion.especialidad_2)) or (
            _eq(a, combinacion.especialidad_2) and _eq(b, combinacion.especialidad_1)
        ):
            return periodo
    return 0


def _es_proveedor_unico(parametria, especialidad: str, institucion: str) -> bool:
    instituciones = {
        limpiar_texto(item.clinica.nombre)
        for item in parametria.instituciones
        if _eq(item.especialidad, especialidad)
    }
    return len(instituciones) == 1 and limpiar_texto(institucion) in instituciones


def _estado_restriccion(otras: int, pendientes: int, proveedor_unico: int, residual: int) -> str:
    if otras > 0:
        return "REVISAR: USO TERCEROS"
    if pendientes > 0:
        return "REQUIERE REVISION"
    if proveedor_unico > 0 and residual > 0:
        return "PREFERIDA + PROVEEDOR UNICO + SABANA"
    if proveedor_unico > 0:
        return "PREFERIDA + PROVEEDOR UNICO"
    if residual > 0:
        return "PREFERIDA + SABANA"
    return "100% PREFERIDA"


def _estado_ocupacion(capacidad: int, asignados: int) -> str:
    if capacidad == 0:
        return "SIN CUPO"
    if asignados == capacidad:
        return "COMPLETA"
    if asignados == 0:
        return "VACIA"
    return "PARCIAL"


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0


def _eq(left: str | None, right: str | None) -> bool:
    return limpiar_texto(left) == limpiar_texto(right)


def _is_residual(institucion: str, residual: str) -> bool:
    return limpiar_texto(residual) in limpiar_texto(institucion)
