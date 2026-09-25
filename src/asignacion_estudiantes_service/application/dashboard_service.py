from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from asignacion_estudiantes_service.application.asignacion_service import listar_resultados
from asignacion_estudiantes_service.application.optimization_service import optimizar_cupos_parametria
from asignacion_estudiantes_service.application.parametria_service import obtener_parametria_completa
from asignacion_estudiantes_service.domain.models import Asignacion, AsignacionEjecucion, Parametria
from asignacion_estudiantes_service.domain.schemas import limpiar_texto


@dataclass
class RotacionGerencial:
    estudiante_id: str
    semestre: str
    institucion: str
    servicio: str
    periodo_inicio: int
    periodo_fin: int
    periodos: int
    pendiente: bool
    causa_pendiente: str | None = None


def obtener_resumen_gerencial(session: Session) -> dict[str, Any]:
    ejecuciones = _ultimas_ejecuciones_por_parametria(session)
    rotaciones: list[RotacionGerencial] = []
    parametria_ids = [ejecucion.parametria_id for ejecucion in ejecuciones]
    for ejecucion in ejecuciones:
        parametria = obtener_parametria_completa(session, ejecucion.parametria_id)
        if parametria is None:
            continue
        rotaciones.extend(_consolidar_rotaciones(parametria, listar_resultados(session, ejecucion.id)))

    total_rotaciones = len(rotaciones)
    estudiantes = {rotacion.estudiante_id for rotacion in rotaciones}
    instituciones = {rotacion.institucion for rotacion in rotaciones if not rotacion.pendiente}
    servicios = {rotacion.servicio for rotacion in rotaciones}
    pendientes = [rotacion for rotacion in rotaciones if rotacion.pendiente]

    return {
        "alcance": {
            "criterio": "ULTIMA_EJECUCION_POR_PARAMETRIA",
            "parametrias": len(parametria_ids),
            "ejecuciones": len(ejecuciones),
        },
        "kpis": {
            "estudiantes_unicos": len(estudiantes),
            "rotaciones": total_rotaciones,
            "escenarios": len(instituciones),
            "areas_rotacion": len(servicios),
            "rotaciones_pendientes": len(pendientes),
            "rotaciones_promedio_por_estudiante": _ratio(total_rotaciones, len(estudiantes)),
            "indice_diversificacion_institucional": _indice_diversificacion(rotaciones),
        },
        "top_escenarios_por_carga": _top_escenarios_por_carga(rotaciones),
        "escenarios_subutilizados": _escenarios_subutilizados(session, parametria_ids, rotaciones),
        "servicios_mayor_demanda": _servicios_mayor_demanda(rotaciones),
        "semestres_presion_rotacion": _semestres_presion_rotacion(rotaciones),
        "instituciones_dependencia_critica": _instituciones_dependencia_critica(rotaciones),
        "rotaciones_pendientes_por_causa": _rotaciones_pendientes_por_causa(pendientes),
        "balance_publico_privado": _balance_publico_privado(rotaciones),
        "rotaciones_simulado_vs_real": _rotaciones_simulado_vs_real(),
        "capacidad_sugerida_vs_usada": _capacidad_sugerida_vs_usada(session, parametria_ids, rotaciones),
    }


def _ultimas_ejecuciones_por_parametria(session: Session) -> list[AsignacionEjecucion]:
    latest_ids = (
        select(func.max(AsignacionEjecucion.id).label("id"))
        .group_by(AsignacionEjecucion.parametria_id)
        .subquery()
    )
    return list(
        session.scalars(
            select(AsignacionEjecucion)
            .where(AsignacionEjecucion.id.in_(select(latest_ids.c.id)))
            .order_by(AsignacionEjecucion.id.desc())
        )
    )


def _consolidar_rotaciones(parametria: Parametria, rows: list[Asignacion]) -> list[RotacionGerencial]:
    estudiantes = {
        item.estudiante_id: item.estudiante.semestre or "SIN SEMESTRE"
        for item in parametria.estudiantes
    }
    combinaciones = sorted(parametria.combinaciones, key=lambda item: item.longitud_bloque, reverse=True)
    rows_by_student: dict[str, list[Asignacion]] = defaultdict(list)
    for row in rows:
        rows_by_student[row.estudiante_id].append(row)

    rotaciones: list[RotacionGerencial] = []
    for estudiante_id, student_rows in rows_by_student.items():
        ordered = sorted(student_rows, key=lambda item: item.periodo)
        by_period = {row.periodo: row for row in ordered}
        periodo = 1
        while periodo <= parametria.numero_periodos:
            row = by_period.get(periodo)
            if row is None:
                periodo += 1
                continue
            bloque = _matching_block(by_period, periodo, combinaciones)
            if bloque:
                length, servicio = bloque
                block_rows = [
                    by_period[p]
                    for p in range(periodo, periodo + length)
                    if by_period.get(p) is not None
                ]
                rotaciones.append(
                    _build_rotacion(
                        estudiante_id,
                        estudiantes.get(estudiante_id, "SIN SEMESTRE"),
                        block_rows,
                        servicio,
                        parametria,
                    )
                )
                periodo += length
                continue

            consecutive = [row]
            next_period = periodo + 1
            while next_period <= parametria.numero_periodos:
                next_row = by_period.get(next_period)
                if (
                    next_row is None
                    or next_row.pendiente != row.pendiente
                    or not _eq(next_row.institucion, row.institucion)
                    or not _eq(next_row.especialidad, row.especialidad)
                ):
                    break
                consecutive.append(next_row)
                next_period += 1
            rotaciones.append(
                _build_rotacion(
                    estudiante_id,
                    estudiantes.get(estudiante_id, "SIN SEMESTRE"),
                    consecutive,
                    row.especialidad,
                    parametria,
                )
            )
            periodo = next_period
    return rotaciones


def _matching_block(by_period: dict[int, Asignacion], periodo: int, combinaciones) -> tuple[int, str] | None:
    for combinacion in combinaciones:
        length = combinacion.longitud_bloque
        block_rows = [by_period.get(p) for p in range(periodo, periodo + length)]
        if any(row is None for row in block_rows):
            continue
        especialidades = [limpiar_texto(row.especialidad) for row in block_rows if row is not None]
        esp1 = limpiar_texto(combinacion.especialidad_1)
        esp2 = limpiar_texto(combinacion.especialidad_2)
        if length == 4 and all(especialidad == esp1 for especialidad in especialidades):
            return length, combinacion.especialidad_1
        if length == 2 and set(especialidades) == {esp1, esp2}:
            return length, f"{combinacion.especialidad_1} + {combinacion.especialidad_2}"
    return None


def _build_rotacion(
    estudiante_id: str,
    semestre: str,
    rows: list[Asignacion],
    servicio: str,
    parametria: Parametria,
) -> RotacionGerencial:
    pendiente = any(row.pendiente for row in rows)
    institucion = "PENDIENTE" if pendiente else rows[0].institucion
    return RotacionGerencial(
        estudiante_id=estudiante_id,
        semestre=semestre,
        institucion=institucion,
        servicio=servicio,
        periodo_inicio=min(row.periodo for row in rows),
        periodo_fin=max(row.periodo for row in rows),
        periodos=len(rows),
        pendiente=pendiente,
        causa_pendiente=_causa_pendiente(rows, parametria) if pendiente else None,
    )


def _top_escenarios_por_carga(rotaciones: list[RotacionGerencial]) -> list[dict[str, Any]]:
    total = len([rotacion for rotacion in rotaciones if not rotacion.pendiente])
    counter = Counter(rotacion.institucion for rotacion in rotaciones if not rotacion.pendiente)
    students: dict[str, set[str]] = defaultdict(set)
    for rotacion in rotaciones:
        if not rotacion.pendiente:
            students[rotacion.institucion].add(rotacion.estudiante_id)
    return [
        {
            "institucion": institucion,
            "rotaciones": rotaciones_count,
            "estudiantes_unicos": len(students[institucion]),
            "participacion": _ratio(rotaciones_count, total),
        }
        for institucion, rotaciones_count in counter.most_common(10)
    ]


def _escenarios_subutilizados(
    session: Session, parametria_ids: list[int], rotaciones: list[RotacionGerencial]
) -> list[dict[str, Any]]:
    if not parametria_ids:
        return []
    capacidad = _capacidad_por_institucion(session, parametria_ids)
    periodos_usados = Counter()
    rotaciones_count = Counter()
    for rotacion in rotaciones:
        if not rotacion.pendiente:
            periodos_usados[rotacion.institucion] += rotacion.periodos
            rotaciones_count[rotacion.institucion] += 1
    rows = []
    for institucion, capacidad_total in capacidad.items():
        usados = periodos_usados[institucion]
        ocupacion = _ratio(usados, capacidad_total)
        if ocupacion < 0.35:
            rows.append(
                {
                    "institucion": institucion,
                    "capacidad_periodos": capacidad_total,
                    "periodos_usados": usados,
                    "rotaciones": rotaciones_count[institucion],
                    "ocupacion": ocupacion,
                }
            )
    return sorted(rows, key=lambda item: (item["ocupacion"], item["rotaciones"]))[:10]


def _servicios_mayor_demanda(rotaciones: list[RotacionGerencial]) -> list[dict[str, Any]]:
    counter = Counter(rotacion.servicio for rotacion in rotaciones)
    students: dict[str, set[str]] = defaultdict(set)
    periods = Counter()
    for rotacion in rotaciones:
        students[rotacion.servicio].add(rotacion.estudiante_id)
        periods[rotacion.servicio] += rotacion.periodos
    return [
        {
            "servicio": servicio,
            "rotaciones": count,
            "estudiantes_unicos": len(students[servicio]),
            "periodos_programados": periods[servicio],
        }
        for servicio, count in counter.most_common(10)
    ]


def _semestres_presion_rotacion(rotaciones: list[RotacionGerencial]) -> list[dict[str, Any]]:
    counter = Counter(rotacion.semestre for rotacion in rotaciones)
    students: dict[str, set[str]] = defaultdict(set)
    pending = Counter()
    for rotacion in rotaciones:
        students[rotacion.semestre].add(rotacion.estudiante_id)
        if rotacion.pendiente:
            pending[rotacion.semestre] += 1
    return [
        {
            "semestre": semestre,
            "rotaciones": count,
            "estudiantes_unicos": len(students[semestre]),
            "rotaciones_promedio_estudiante": _ratio(count, len(students[semestre])),
            "pendientes": pending[semestre],
        }
        for semestre, count in sorted(counter.items(), key=lambda item: str(item[0]))
    ]


def _instituciones_dependencia_critica(rotaciones: list[RotacionGerencial]) -> list[dict[str, Any]]:
    total = len([rotacion for rotacion in rotaciones if not rotacion.pendiente])
    counter = Counter(rotacion.institucion for rotacion in rotaciones if not rotacion.pendiente)
    rows = []
    for institucion, count in counter.most_common():
        participacion = _ratio(count, total)
        if participacion >= 0.25:
            rows.append(
                {
                    "institucion": institucion,
                    "rotaciones": count,
                    "participacion": participacion,
                    "riesgo": "ALTA CONCENTRACION",
                }
            )
    return rows


def _rotaciones_pendientes_por_causa(rotaciones: list[RotacionGerencial]) -> list[dict[str, Any]]:
    counter = Counter(rotacion.causa_pendiente or "SIN CLASIFICAR" for rotacion in rotaciones)
    return [{"causa": causa, "rotaciones": count} for causa, count in counter.most_common()]


def _balance_publico_privado(rotaciones: list[RotacionGerencial]) -> list[dict[str, Any]]:
    counter = Counter(_clasificar_institucion(rotacion.institucion) for rotacion in rotaciones if not rotacion.pendiente)
    total = sum(counter.values())
    return [
        {"tipo": tipo, "rotaciones": count, "participacion": _ratio(count, total)}
        for tipo, count in counter.most_common()
    ]


def _rotaciones_simulado_vs_real() -> dict[str, Any]:
    return {
        "estado": "NO_DISPONIBLE",
        "mensaje": "Las validaciones simuladas se ejecutan temporalmente y no se persisten para auditoría histórica.",
        "real": [],
        "simulado": [],
    }


def _capacidad_sugerida_vs_usada(
    session: Session, parametria_ids: list[int], rotaciones: list[RotacionGerencial]
) -> list[dict[str, Any]]:
    usados = Counter()
    for rotacion in rotaciones:
        if not rotacion.pendiente:
            usados[(rotacion.institucion, rotacion.servicio)] += rotacion.periodos
    rows = []
    for parametria_id in parametria_ids:
        try:
            optimizacion = optimizar_cupos_parametria(session, parametria_id)
        except ValueError:
            continue
        for item in optimizacion["parametria_sugerida"]:
            key = (item["institucion"], item["especialidad"])
            rows.append(
                {
                    "parametria_id": parametria_id,
                    "institucion": item["institucion"],
                    "servicio": item["especialidad"],
                    "capacidad_actual": item["capacidad_actual"],
                    "capacidad_sugerida": item["capacidad_sugerida"],
                    "periodos_usados": usados[key],
                    "brecha_actual": item["capacidad_actual"] - usados[key],
                    "brecha_sugerida": item["capacidad_sugerida"] - usados[key],
                }
            )
    return sorted(rows, key=lambda item: abs(item["brecha_sugerida"]), reverse=True)[:20]


def _capacidad_por_institucion(session: Session, parametria_ids: list[int]) -> dict[str, int]:
    capacidad: dict[str, int] = defaultdict(int)
    for parametria_id in parametria_ids:
        parametria = obtener_parametria_completa(session, parametria_id)
        if parametria is None:
            continue
        for institucion in parametria.instituciones:
            capacidad[institucion.clinica.nombre] += institucion.cantidad * parametria.numero_periodos
    return capacidad


def _causa_pendiente(rows: list[Asignacion], parametria: Parametria) -> str:
    especialidades = {limpiar_texto(row.especialidad) for row in rows}
    if any(_restriccion_aplica(row, parametria) for row in rows):
        return "RESTRICCION SIN CUPO"
    for combinacion in parametria.combinaciones:
        combo = {limpiar_texto(combinacion.especialidad_1), limpiar_texto(combinacion.especialidad_2)}
        if especialidades.issubset(combo):
            return "BLOQUE SIN CUPO"
    return "CUPO INSUFICIENTE"


def _restriccion_aplica(row: Asignacion, parametria: Parametria) -> bool:
    for restriccion in parametria.restricciones:
        if restriccion.estudiante_id != row.estudiante_id:
            continue
        if restriccion.especialidad and not _eq(restriccion.especialidad, row.especialidad):
            continue
        return True
    return False


def _clasificar_institucion(institucion: str) -> str:
    normalized = limpiar_texto(institucion)
    public_keywords = ("HOSPITAL UNIVERSITARIO", "HOSPITAL DE", "SUBRED", "E.S.E", "ESE")
    private_keywords = ("CLINICA", "FUNDACION", "UNIVERSIDAD")
    if any(keyword in normalized for keyword in public_keywords):
        return "PUBLICO"
    if any(keyword in normalized for keyword in private_keywords):
        return "PRIVADO"
    return "SIN CLASIFICAR"


def _indice_diversificacion(rotaciones: list[RotacionGerencial]) -> float:
    counts = Counter(rotacion.institucion for rotacion in rotaciones if not rotacion.pendiente)
    total = sum(counts.values())
    if total == 0:
        return 0
    concentration = sum((count / total) ** 2 for count in counts.values())
    return 1 - concentration


def _ratio(numerator: int | float, denominator: int | float) -> float:
    return numerator / denominator if denominator else 0


def _eq(left: str | None, right: str | None) -> bool:
    return limpiar_texto(left) == limpiar_texto(right)
