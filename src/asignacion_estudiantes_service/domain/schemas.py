from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def limpiar_texto(valor: str | None) -> str:
    if valor is None:
        return ""
    return " ".join(str(valor).strip().upper().split())


class InstitucionIn(BaseModel):
    institucion: str = Field(min_length=1)
    especialidad: str = Field(min_length=1)
    cantidad: int = Field(ge=0)


class RestriccionIn(BaseModel):
    estudiante: str = Field(min_length=1)
    institucion: str = Field(min_length=1)
    especialidad: str | None = None


class AsignacionConfigIn(BaseModel):
    numero_periodos: int = Field(ge=5, le=8)
    estudiantes_aleatorio: bool = True
    instituciones_aleatorio: bool = True
    asignacion: str = "BALANCEADA"
    institucion_residual: str = "SABANA"

    @field_validator("asignacion")
    @classmethod
    def validar_estrategia(cls, value: str) -> str:
        normalized = limpiar_texto(value)
        if normalized not in {"BALANCEADA", "CONCENTRADA"}:
            raise ValueError("asignacion debe ser BALANCEADA o CONCENTRADA")
        return normalized


class DistribucionPeriodoIn(BaseModel):
    especialidad: str = Field(min_length=1)
    asignacion: int = Field(ge=0)


class PeriodoFechaIn(BaseModel):
    periodo: int = Field(ge=1, le=8)
    fecha_inicio: date | None = None
    fecha_fin: date | None = None
    fecha: date | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def normalizar_rango(self) -> PeriodoFechaIn:
        if self.fecha_inicio is None and self.fecha is not None:
            self.fecha_inicio = self.fecha
        if (
            self.fecha_inicio is not None
            and self.fecha_fin is not None
            and self.fecha_fin < self.fecha_inicio
        ):
            raise ValueError("fecha_fin no puede ser anterior a fecha_inicio")
        return self


class CombinacionIn(BaseModel):
    especialidad_1: str = Field(min_length=1)
    especialidad_2: str = Field(min_length=1)
    bloque: str = "X2"

    @field_validator("bloque")
    @classmethod
    def validar_bloque(cls, value: str) -> str:
        normalized = limpiar_texto(value).replace(" ", "")
        if normalized in {"2", "X2"}:
            return "X2"
        if normalized in {"4", "X4"}:
            return "X4"
        raise ValueError("bloque debe ser X2 o X4")


class EstudianteIn(BaseModel):
    id: str = Field(min_length=1)
    nombre: str | None = None
    semestre: str | None = None


class ParametriaCargaIn(BaseModel):
    nombre: str = "Parametria"
    instituciones: list[InstitucionIn]
    restricciones: list[RestriccionIn] = Field(default_factory=list)
    asignacion: AsignacionConfigIn
    distribucion_periodos: list[DistribucionPeriodoIn]
    fechas_periodos: list[PeriodoFechaIn] = Field(default_factory=list)
    combinaciones: list[CombinacionIn] = Field(default_factory=list)
    estudiantes: list[EstudianteIn]


class ParametriaResumenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    numero_periodos: int
    estudiantes_aleatorio: bool
    instituciones_aleatorio: bool
    estrategia: str
    institucion_residual: str


class ParametriaCreadaOut(BaseModel):
    id: int
    mensaje: str


class ClinicaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str


class EstudianteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    nombre: str | None = None
    semestre: str | None = None


class EjecutarAsignacionOut(BaseModel):
    ejecucion_id: int
    parametria_id: int
    estado: str
    total_estudiantes: int
    total_asignaciones: int
    total_pendientes: int
    mensaje: str | None = None


class AsignacionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ejecucion_id: int
    estudiante_id: str
    estudiante_nombre: str | None = None
    estudiante_semestre: str | None = None
    periodo: int
    especialidad: str
    institucion: str
    pendiente: bool


class AsignacionEjecucionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    parametria_id: int
    estado: str
    total_estudiantes: int
    total_asignaciones: int
    total_pendientes: int
    mensaje: str | None = None
    created_at: datetime | None = None


class MatrizAsignacionRowIn(BaseModel):
    estudiante_id: str = Field(min_length=1)
    periodo: int = Field(ge=1, le=8)
    especialidad: str = ""
    institucion: str = ""


class MatrizAsignacionIn(BaseModel):
    filas: list[MatrizAsignacionRowIn]
    mensaje: str | None = "Malla cargada desde archivo ajustado por usuario."


class LimpiezaResultadosOut(BaseModel):
    ejecuciones_eliminadas: int
    asignaciones_eliminadas: int
    detalles_parametria_eliminados: int


class DiagnosticoMensajeOut(BaseModel):
    severidad: str
    titulo: str
    detalle: str
    entidad: str


class DiagnosticoAccionOut(BaseModel):
    id: str
    label: str
    target: str


class DiagnosticoAsignacionOut(BaseModel):
    ejecucion_id: int
    parametria_id: int
    nivel: str
    confianza: float
    resumen_ejecutivo: str
    metricas: dict[str, str | int | float]
    riesgos: list[DiagnosticoMensajeOut]
    causas_probables: list[DiagnosticoMensajeOut]
    recomendaciones: list[DiagnosticoMensajeOut]
    acciones_rapidas: list[DiagnosticoAccionOut]


class OptimizarParametriaIn(BaseModel):
    max_intentos: int = Field(default=20, ge=1, le=20)


class CupoSugeridoOut(BaseModel):
    institucion: str
    especialidad: str
    cupo_actual: int
    cupo_sugerido: int
    demanda_estimada: int
    uso_estimado: int
    capacidad_actual: int
    capacidad_sugerida: int
    proveedor_unico: bool
    razon: str


class OptimizacionCuposOut(BaseModel):
    parametria_id: int
    fase: str
    resultado: str
    estudiantes: int
    numero_periodos: int
    cupos_totales_actuales: int
    cupos_totales_sugeridos: int
    reduccion_cupos: int
    resumen: str
    parametria_sugerida: list[CupoSugeridoOut]
    advertencias: list[str]


class OptimizacionParametriaOut(OptimizacionCuposOut):
    parametria_simulada_id: int
    ejecucion_simulada_id: int
    pendientes_estimados: int
    diagnostico: DiagnosticoAsignacionOut
