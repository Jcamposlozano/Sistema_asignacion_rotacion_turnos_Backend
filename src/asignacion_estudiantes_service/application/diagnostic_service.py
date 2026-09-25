from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from asignacion_estudiantes_service.application.analysis_service import obtener_analisis_asignacion
from asignacion_estudiantes_service.application.asignacion_service import obtener_ejecucion


def obtener_diagnostico_asignacion(session: Session, ejecucion_id: int) -> dict[str, Any] | None:
    ejecucion = obtener_ejecucion(session, ejecucion_id)
    if ejecucion is None:
        return None

    analisis = obtener_analisis_asignacion(session, ejecucion_id)
    if analisis is None:
        return None

    resumen = analisis["resumen"]
    pendientes = analisis["pendientes"]
    resumen_especialidad = analisis["resumen_especialidad"]
    restricciones = analisis["restricciones"]
    bloques = analisis["bloques"]
    ocupacion = analisis["ocupacion"]

    total_pendientes = int(resumen["asignaciones_pendientes"])
    cobertura = float(resumen["cobertura_global"])
    nivel = _nivel_diagnostico(total_pendientes, restricciones, bloques)

    riesgos = _riesgos(total_pendientes, resumen_especialidad, restricciones, bloques)
    causas = _causas_probables(total_pendientes, resumen_especialidad, restricciones, ocupacion)
    recomendaciones = _recomendaciones(total_pendientes, resumen_especialidad, restricciones, bloques)
    acciones = _acciones_rapidas(total_pendientes, restricciones, bloques)

    return {
        "ejecucion_id": ejecucion.id,
        "parametria_id": ejecucion.parametria_id,
        "nivel": nivel,
        "confianza": 1.0,
        "resumen_ejecutivo": _resumen_ejecutivo(total_pendientes, cobertura, nivel),
        "metricas": {
            "estudiantes": resumen["estudiantes"],
            "numero_periodos": resumen["numero_periodos"],
            "asignaciones_realizadas": resumen["asignaciones_realizadas"],
            "asignaciones_pendientes": total_pendientes,
            "cobertura_global": cobertura,
            "estrategia": resumen["estrategia"],
            "institucion_residual": resumen["institucion_residual"],
        },
        "riesgos": riesgos,
        "causas_probables": causas,
        "recomendaciones": recomendaciones,
        "acciones_rapidas": acciones,
    }


def _nivel_diagnostico(
    total_pendientes: int,
    restricciones: list[dict[str, Any]],
    bloques: list[dict[str, Any]],
) -> str:
    restricciones_con_pendientes = any(int(item["pendientes"]) > 0 for item in restricciones)
    bloques_con_pendientes = any(int(item["con_pendiente"]) > 0 for item in bloques)
    if total_pendientes > 0 and (restricciones_con_pendientes or bloques_con_pendientes):
        return "CRITICO"
    if total_pendientes > 0:
        return "ADVERTENCIA"
    if any(str(item["estado"]).startswith("REVISAR") for item in restricciones):
        return "ADVERTENCIA"
    return "OK"


def _resumen_ejecutivo(total_pendientes: int, cobertura: float, nivel: str) -> str:
    cobertura_pct = round(cobertura * 100, 1)
    if total_pendientes == 0:
        return f"La ejecución quedó cubierta al {cobertura_pct}% y no registra asignaciones pendientes."
    return (
        f"La ejecución tiene {total_pendientes} asignaciones pendientes, "
        f"con cobertura global de {cobertura_pct}%. Nivel de atención: {nivel}."
    )


def _riesgos(
    total_pendientes: int,
    resumen_especialidad: list[dict[str, Any]],
    restricciones: list[dict[str, Any]],
    bloques: list[dict[str, Any]],
) -> list[dict[str, str]]:
    riesgos: list[dict[str, str]] = []
    if total_pendientes > 0:
        riesgos.append(
            {
                "severidad": "alta",
                "titulo": "Asignaciones pendientes",
                "detalle": f"Existen {total_pendientes} periodos sin institución asignada.",
                "entidad": "resultados",
            }
        )

    for row in resumen_especialidad:
        pendiente = int(row["pendiente"])
        if pendiente > 0:
            riesgos.append(
                {
                    "severidad": "alta",
                    "titulo": "Especialidad con demanda no cubierta",
                    "detalle": f"{row['especialidad']} tiene {pendiente} asignaciones pendientes.",
                    "entidad": str(row["especialidad"]),
                }
            )

    restricciones_problematicas = [
        row for row in restricciones if int(row["pendientes"]) > 0 or int(row["otras_instituciones"]) > 0
    ]
    if restricciones_problematicas:
        riesgos.append(
            {
                "severidad": "media",
                "titulo": "Restricciones por revisar",
                "detalle": f"{len(restricciones_problematicas)} restricciones tienen pendientes o uso de otras instituciones.",
                "entidad": "restricciones",
            }
        )

    bloques_problematicos = [
        row for row in bloques if int(row["con_pendiente"]) > 0 or int(row["institucion_diferente"]) > 0
    ]
    if bloques_problematicos:
        riesgos.append(
            {
                "severidad": "media",
                "titulo": "Bloques con tensión operativa",
                "detalle": f"{len(bloques_problematicos)} combinaciones tienen pendientes o instituciones diferentes.",
                "entidad": "bloques",
            }
        )

    if not riesgos:
        riesgos.append(
            {
                "severidad": "baja",
                "titulo": "Sin riesgos críticos",
                "detalle": "No se detectaron pendientes ni incumplimientos relevantes en la ejecución.",
                "entidad": "ejecucion",
            }
        )
    return riesgos


def _causas_probables(
    total_pendientes: int,
    resumen_especialidad: list[dict[str, Any]],
    restricciones: list[dict[str, Any]],
    ocupacion: list[dict[str, Any]],
) -> list[dict[str, str]]:
    causas: list[dict[str, str]] = []
    if total_pendientes == 0:
        return [
            {
                "severidad": "baja",
                "titulo": "Capacidad suficiente",
                "detalle": "La parametría actual permitió cubrir todas las asignaciones teóricas.",
                "entidad": "parametria",
            }
        ]

    agotadas = _especialidades_agotadas(ocupacion)
    for row in resumen_especialidad:
        pendiente = int(row["pendiente"])
        cupos_sin_usar = int(row["cupos_sin_usar"])
        especialidad = str(row["especialidad"])
        if pendiente > 0 and especialidad in agotadas:
            causas.append(
                {
                    "severidad": "alta",
                    "titulo": "Cupos agotados",
                    "detalle": f"{especialidad} tiene periodos con instituciones completas y demanda pendiente.",
                    "entidad": especialidad,
                }
            )
        elif pendiente > 0 and cupos_sin_usar > 0:
            causas.append(
                {
                    "severidad": "media",
                    "titulo": "Cupos disponibles no aprovechados",
                    "detalle": f"{especialidad} conserva {cupos_sin_usar} cupos agregados sin usar; revisar restricciones, bloques o aleatoriedad.",
                    "entidad": especialidad,
                }
            )

    restricciones_pendientes = [row for row in restricciones if int(row["pendientes"]) > 0]
    if restricciones_pendientes:
        causas.append(
            {
                "severidad": "alta",
                "titulo": "Restricciones obligatorias sin cupo",
                "detalle": f"{len(restricciones_pendientes)} restricciones quedaron con prácticas pendientes.",
                "entidad": "restricciones",
            }
        )

    return causas


def _recomendaciones(
    total_pendientes: int,
    resumen_especialidad: list[dict[str, Any]],
    restricciones: list[dict[str, Any]],
    bloques: list[dict[str, Any]],
) -> list[dict[str, str]]:
    recomendaciones: list[dict[str, str]] = []
    for row in resumen_especialidad:
        pendiente = int(row["pendiente"])
        if pendiente > 0:
            recomendaciones.append(
                {
                    "severidad": "alta",
                    "titulo": "Ajustar capacidad por especialidad",
                    "detalle": f"Aumentar cupos o instituciones disponibles para {row['especialidad']} antes de volver a ejecutar.",
                    "entidad": str(row["especialidad"]),
                }
            )

    if any(int(row["pendientes"]) > 0 for row in restricciones):
        recomendaciones.append(
            {
                "severidad": "alta",
                "titulo": "Revisar restricciones prioritarias",
                "detalle": "Validar que cada institución preferente tenga cupo para la especialidad obligatoria del estudiante.",
                "entidad": "restricciones",
            }
        )

    if any(int(row["con_pendiente"]) > 0 for row in bloques):
        recomendaciones.append(
            {
                "severidad": "media",
                "titulo": "Revisar bloques X2/X4",
                "detalle": "Las combinaciones con pendientes pueden requerir más cupo consecutivo o menor rigidez en la parametría.",
                "entidad": "bloques",
            }
        )

    if total_pendientes == 0:
        recomendaciones.append(
            {
                "severidad": "baja",
                "titulo": "Conservar parametría",
                "detalle": "La ejecución actual es apta para revisión final y descarga de resultados.",
                "entidad": "ejecucion",
            }
        )

    return recomendaciones[:6]


def _acciones_rapidas(
    total_pendientes: int,
    restricciones: list[dict[str, Any]],
    bloques: list[dict[str, Any]],
) -> list[dict[str, str]]:
    acciones = [
        {
            "id": "ver-resultados",
            "label": "Ver resultados",
            "target": "resultados",
        },
        {
            "id": "descargar-analisis",
            "label": "Descargar análisis",
            "target": "analisis",
        },
    ]
    if total_pendientes > 0:
        acciones.insert(
            0,
            {
                "id": "filtrar-pendientes",
                "label": "Filtrar pendientes",
                "target": "resultados",
            },
        )
    if any(int(row["pendientes"]) > 0 or int(row["otras_instituciones"]) > 0 for row in restricciones):
        acciones.append(
            {
                "id": "revisar-restricciones",
                "label": "Revisar restricciones",
                "target": "analisis",
            }
        )
    if any(int(row["con_pendiente"]) > 0 or int(row["institucion_diferente"]) > 0 for row in bloques):
        acciones.append(
            {
                "id": "revisar-bloques",
                "label": "Revisar bloques",
                "target": "analisis",
            }
        )
    return acciones


def _especialidades_agotadas(ocupacion: list[dict[str, Any]]) -> set[str]:
    agotadas = set()
    for row in ocupacion:
        if str(row["estado"]) == "COMPLETA":
            agotadas.add(str(row["especialidad"]))
    return agotadas
