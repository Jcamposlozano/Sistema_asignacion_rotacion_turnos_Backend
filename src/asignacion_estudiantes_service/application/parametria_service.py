from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from asignacion_estudiantes_service.domain.models import (
    Asignacion,
    AsignacionEjecucion,
    Clinica,
    Combinacion,
    DistribucionPeriodo,
    Estudiante,
    Parametria,
    ParametriaEstudiante,
    ParametriaInstitucion,
    Restriccion,
)
from asignacion_estudiantes_service.domain.schemas import ParametriaCargaIn, limpiar_texto


class ParametriaError(ValueError):
    pass


def _get_or_create_clinica(session: Session, nombre: str) -> Clinica:
    nombre_limpio = limpiar_texto(nombre)
    clinica = session.scalar(select(Clinica).where(Clinica.nombre == nombre_limpio))
    if clinica is None:
        clinica = Clinica(nombre=nombre_limpio)
        session.add(clinica)
        session.flush()
    return clinica


def _get_or_create_estudiante(
    session: Session, estudiante_id: str, nombre: str | None, semestre: str | None
) -> Estudiante:
    estudiante_id = str(estudiante_id).strip()
    semestre = str(semestre).strip() if semestre is not None else None
    estudiante = session.get(Estudiante, estudiante_id)
    if estudiante is None:
        estudiante = Estudiante(id=estudiante_id, nombre=nombre, semestre=semestre)
        session.add(estudiante)
        session.flush()
    else:
        if nombre and estudiante.nombre != nombre:
            estudiante.nombre = nombre
        if semestre and estudiante.semestre != semestre:
            estudiante.semestre = semestre
    return estudiante


def validar_carga(payload: ParametriaCargaIn) -> None:
    total_periodos = sum(item.asignacion for item in payload.distribucion_periodos)
    if total_periodos != payload.asignacion.numero_periodos:
        raise ParametriaError(
            "La suma de distribucion_periodos debe coincidir con asignacion.numero_periodos"
        )

    especialidades_distribucion = {
        limpiar_texto(item.especialidad) for item in payload.distribucion_periodos
    }
    especialidades_instituciones = {
        limpiar_texto(item.especialidad) for item in payload.instituciones
    }
    faltantes = especialidades_distribucion - especialidades_instituciones
    if faltantes:
        raise ParametriaError(
            "Hay especialidades en distribucion_periodos sin institución: "
            + ", ".join(sorted(faltantes))
        )

    estudiantes = [str(item.id).strip() for item in payload.estudiantes]
    repetidos = sorted({item for item in estudiantes if estudiantes.count(item) > 1})
    if repetidos:
        raise ParametriaError("Estudiantes repetidos: " + ", ".join(repetidos))

    estudiantes_set = set(estudiantes)
    for restriccion in payload.restricciones:
        if str(restriccion.estudiante).strip() not in estudiantes_set:
            raise ParametriaError(
                f"El estudiante {restriccion.estudiante} de restricciones no existe en estudiantes"
            )

    consumo_por_especialidad = dict.fromkeys(especialidades_distribucion, 0)
    periodos_bloques = 0
    for combinacion in payload.combinaciones:
        esp1 = limpiar_texto(combinacion.especialidad_1)
        esp2 = limpiar_texto(combinacion.especialidad_2)
        longitud = 4 if combinacion.bloque == "X4" else 2
        if esp1 not in especialidades_distribucion or esp2 not in especialidades_distribucion:
            raise ParametriaError("Las combinaciones solo pueden usar especialidades distribuidas")
        if longitud == 4 and esp1 != esp2:
            raise ParametriaError("Los bloques X4 requieren que ambas especialidades sean iguales")
        periodos_bloques += longitud
        if longitud == 4:
            consumo_por_especialidad[esp1] += 4
        else:
            consumo_por_especialidad[esp1] += 1
            consumo_por_especialidad[esp2] += 1

    if periodos_bloques > payload.asignacion.numero_periodos:
        raise ParametriaError("Las combinaciones consumen más periodos que los configurados")

    asignacion_por_especialidad = {
        limpiar_texto(item.especialidad): item.asignacion for item in payload.distribucion_periodos
    }
    excedidas = [
        esp
        for esp, consumo in consumo_por_especialidad.items()
        if consumo > asignacion_por_especialidad[esp]
    ]
    if excedidas:
        raise ParametriaError(
            "Las combinaciones exceden la distribución de: " + ", ".join(sorted(excedidas))
        )


def crear_parametria(session: Session, payload: ParametriaCargaIn) -> Parametria:
    validar_carga(payload)

    config = payload.asignacion
    parametria = Parametria(
        nombre=payload.nombre,
        numero_periodos=config.numero_periodos,
        estudiantes_aleatorio=config.estudiantes_aleatorio,
        instituciones_aleatorio=config.instituciones_aleatorio,
        estrategia=limpiar_texto(config.asignacion),
        institucion_residual=limpiar_texto(config.institucion_residual),
    )
    session.add(parametria)
    session.flush()

    for item in payload.estudiantes:
        estudiante = _get_or_create_estudiante(session, item.id, item.nombre, item.semestre)
        session.add(ParametriaEstudiante(parametria_id=parametria.id, estudiante_id=estudiante.id))

    for item in payload.instituciones:
        clinica = _get_or_create_clinica(session, item.institucion)
        session.add(
            ParametriaInstitucion(
                parametria_id=parametria.id,
                clinica_id=clinica.id,
                especialidad=limpiar_texto(item.especialidad),
                cantidad=item.cantidad,
            )
        )

    for item in payload.restricciones:
        clinica = _get_or_create_clinica(session, item.institucion)
        session.add(
            Restriccion(
                parametria_id=parametria.id,
                estudiante_id=str(item.estudiante).strip(),
                clinica_id=clinica.id,
                especialidad=limpiar_texto(item.especialidad) or None,
            )
        )

    for item in payload.distribucion_periodos:
        session.add(
            DistribucionPeriodo(
                parametria_id=parametria.id,
                especialidad=limpiar_texto(item.especialidad),
                asignacion=item.asignacion,
            )
        )

    for item in payload.combinaciones:
        longitud = 4 if item.bloque == "X4" else 2
        session.add(
            Combinacion(
                parametria_id=parametria.id,
                especialidad_1=limpiar_texto(item.especialidad_1),
                especialidad_2=limpiar_texto(item.especialidad_2),
                bloque=item.bloque,
                longitud_bloque=longitud,
            )
        )

    session.commit()
    session.refresh(parametria)
    return parametria


def actualizar_parametria(
    session: Session, parametria_id: int, payload: ParametriaCargaIn
) -> Parametria | None:
    validar_carga(payload)
    parametria = session.get(Parametria, parametria_id)
    if parametria is None:
        return None

    _limpiar_resultados_parametria(session, parametria_id)
    _limpiar_detalle_parametria(session, parametria_id)

    config = payload.asignacion
    parametria.nombre = payload.nombre
    parametria.numero_periodos = config.numero_periodos
    parametria.estudiantes_aleatorio = config.estudiantes_aleatorio
    parametria.instituciones_aleatorio = config.instituciones_aleatorio
    parametria.estrategia = limpiar_texto(config.asignacion)
    parametria.institucion_residual = limpiar_texto(config.institucion_residual)
    session.flush()

    _crear_detalle_parametria(session, parametria.id, payload)

    session.commit()
    session.refresh(parametria)
    return parametria


def eliminar_parametria(session: Session, parametria_id: int) -> bool:
    parametria = session.get(Parametria, parametria_id)
    if parametria is None:
        return False

    _limpiar_resultados_parametria(session, parametria_id)
    _limpiar_detalle_parametria(session, parametria_id)
    session.delete(parametria)
    session.commit()
    return True


def _crear_detalle_parametria(
    session: Session, parametria_id: int, payload: ParametriaCargaIn
) -> None:
    for item in payload.estudiantes:
        estudiante = _get_or_create_estudiante(session, item.id, item.nombre, item.semestre)
        session.add(ParametriaEstudiante(parametria_id=parametria_id, estudiante_id=estudiante.id))

    for item in payload.instituciones:
        clinica = _get_or_create_clinica(session, item.institucion)
        session.add(
            ParametriaInstitucion(
                parametria_id=parametria_id,
                clinica_id=clinica.id,
                especialidad=limpiar_texto(item.especialidad),
                cantidad=item.cantidad,
            )
        )

    for item in payload.restricciones:
        clinica = _get_or_create_clinica(session, item.institucion)
        session.add(
            Restriccion(
                parametria_id=parametria_id,
                estudiante_id=str(item.estudiante).strip(),
                clinica_id=clinica.id,
                especialidad=limpiar_texto(item.especialidad) or None,
            )
        )

    for item in payload.distribucion_periodos:
        session.add(
            DistribucionPeriodo(
                parametria_id=parametria_id,
                especialidad=limpiar_texto(item.especialidad),
                asignacion=item.asignacion,
            )
        )

    for item in payload.combinaciones:
        longitud = 4 if item.bloque == "X4" else 2
        session.add(
            Combinacion(
                parametria_id=parametria_id,
                especialidad_1=limpiar_texto(item.especialidad_1),
                especialidad_2=limpiar_texto(item.especialidad_2),
                bloque=item.bloque,
                longitud_bloque=longitud,
            )
        )


def _limpiar_detalle_parametria(session: Session, parametria_id: int) -> None:
    for model in (
        Restriccion,
        Combinacion,
        DistribucionPeriodo,
        ParametriaInstitucion,
        ParametriaEstudiante,
    ):
        session.execute(delete(model).where(model.parametria_id == parametria_id))
    session.flush()


def _limpiar_resultados_parametria(session: Session, parametria_id: int) -> None:
    ejecuciones_ids = list(
        session.scalars(
            select(AsignacionEjecucion.id).where(AsignacionEjecucion.parametria_id == parametria_id)
        )
    )
    for ejecucion_id in ejecuciones_ids:
        session.execute(delete(Asignacion).where(Asignacion.ejecucion_id == ejecucion_id))
    session.execute(delete(Asignacion).where(Asignacion.parametria_id == parametria_id))
    session.execute(delete(AsignacionEjecucion).where(AsignacionEjecucion.parametria_id == parametria_id))
    session.flush()


def obtener_parametria_completa(session: Session, parametria_id: int) -> Parametria | None:
    return session.scalar(
        select(Parametria)
        .where(Parametria.id == parametria_id)
        .options(
            selectinload(Parametria.instituciones).selectinload(ParametriaInstitucion.clinica),
            selectinload(Parametria.restricciones).selectinload(Restriccion.clinica),
            selectinload(Parametria.restricciones).selectinload(Restriccion.estudiante),
            selectinload(Parametria.distribuciones),
            selectinload(Parametria.combinaciones),
            selectinload(Parametria.estudiantes).selectinload(ParametriaEstudiante.estudiante),
        )
    )
