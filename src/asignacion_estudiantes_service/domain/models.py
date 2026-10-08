from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Estudiante(Base):
    __tablename__ = "estudiantes"

    id: Mapped[str] = mapped_column(String(30), primary_key=True)
    nombre: Mapped[str | None] = mapped_column(String(255), nullable=True)
    semestre: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Clinica(Base):
    __tablename__ = "clinicas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Parametria(Base):
    __tablename__ = "parametria"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(255), default="Parametria")
    numero_periodos: Mapped[int] = mapped_column(Integer)
    estudiantes_aleatorio: Mapped[bool] = mapped_column(Boolean, default=True)
    instituciones_aleatorio: Mapped[bool] = mapped_column(Boolean, default=True)
    estrategia: Mapped[str] = mapped_column(String(30), default="BALANCEADA")
    institucion_residual: Mapped[str] = mapped_column(String(255), default="SABANA")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    instituciones: Mapped[list[ParametriaInstitucion]] = relationship(
        back_populates="parametria", cascade="all, delete-orphan"
    )
    restricciones: Mapped[list[Restriccion]] = relationship(
        back_populates="parametria", cascade="all, delete-orphan"
    )
    distribuciones: Mapped[list[DistribucionPeriodo]] = relationship(
        back_populates="parametria", cascade="all, delete-orphan"
    )
    fechas_periodos: Mapped[list[ParametriaPeriodoFecha]] = relationship(
        back_populates="parametria", cascade="all, delete-orphan"
    )
    combinaciones: Mapped[list[Combinacion]] = relationship(
        back_populates="parametria", cascade="all, delete-orphan"
    )
    estudiantes: Mapped[list[ParametriaEstudiante]] = relationship(
        back_populates="parametria", cascade="all, delete-orphan"
    )


class ParametriaInstitucion(Base):
    __tablename__ = "parametria_instituciones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parametria_id: Mapped[int] = mapped_column(ForeignKey("parametria.id"), index=True)
    clinica_id: Mapped[int] = mapped_column(ForeignKey("clinicas.id"), index=True)
    especialidad: Mapped[str] = mapped_column(String(255), index=True)
    cantidad: Mapped[int] = mapped_column(Integer)

    parametria: Mapped[Parametria] = relationship(back_populates="instituciones")
    clinica: Mapped[Clinica] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "parametria_id", "clinica_id", "especialidad", name="uq_param_clinica_esp"
        ),
    )


class ParametriaEstudiante(Base):
    __tablename__ = "parametria_estudiantes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parametria_id: Mapped[int] = mapped_column(ForeignKey("parametria.id"), index=True)
    estudiante_id: Mapped[str] = mapped_column(ForeignKey("estudiantes.id"), index=True)

    parametria: Mapped[Parametria] = relationship(back_populates="estudiantes")
    estudiante: Mapped[Estudiante] = relationship()

    __table_args__ = (
        UniqueConstraint("parametria_id", "estudiante_id", name="uq_param_estudiante"),
    )


class Restriccion(Base):
    __tablename__ = "restricciones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parametria_id: Mapped[int] = mapped_column(ForeignKey("parametria.id"), index=True)
    estudiante_id: Mapped[str] = mapped_column(ForeignKey("estudiantes.id"), index=True)
    clinica_id: Mapped[int] = mapped_column(ForeignKey("clinicas.id"), index=True)
    especialidad: Mapped[str | None] = mapped_column(String(255), nullable=True)

    parametria: Mapped[Parametria] = relationship(back_populates="restricciones")
    estudiante: Mapped[Estudiante] = relationship()
    clinica: Mapped[Clinica] = relationship()


class DistribucionPeriodo(Base):
    __tablename__ = "distribucion_periodos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parametria_id: Mapped[int] = mapped_column(ForeignKey("parametria.id"), index=True)
    especialidad: Mapped[str] = mapped_column(String(255), index=True)
    asignacion: Mapped[int] = mapped_column(Integer)

    parametria: Mapped[Parametria] = relationship(back_populates="distribuciones")

    __table_args__ = (
        UniqueConstraint("parametria_id", "especialidad", name="uq_param_distribucion_esp"),
    )


class ParametriaPeriodoFecha(Base):
    __tablename__ = "parametria_periodo_fechas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parametria_id: Mapped[int] = mapped_column(ForeignKey("parametria.id"), index=True)
    periodo: Mapped[int] = mapped_column(Integer)
    fecha_inicio: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_fin: Mapped[date | None] = mapped_column(Date, nullable=True)

    parametria: Mapped[Parametria] = relationship(back_populates="fechas_periodos")

    __table_args__ = (
        UniqueConstraint("parametria_id", "periodo", name="uq_param_periodo_fecha"),
    )


class Combinacion(Base):
    __tablename__ = "combinaciones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parametria_id: Mapped[int] = mapped_column(ForeignKey("parametria.id"), index=True)
    especialidad_1: Mapped[str] = mapped_column(String(255))
    especialidad_2: Mapped[str] = mapped_column(String(255))
    bloque: Mapped[str] = mapped_column(String(10))
    longitud_bloque: Mapped[int] = mapped_column(Integer)

    parametria: Mapped[Parametria] = relationship(back_populates="combinaciones")


class AsignacionEjecucion(Base):
    __tablename__ = "asignacion_ejecuciones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parametria_id: Mapped[int] = mapped_column(ForeignKey("parametria.id"), index=True)
    estado: Mapped[str] = mapped_column(String(30), default="COMPLETADA")
    total_estudiantes: Mapped[int] = mapped_column(Integer, default=0)
    total_asignaciones: Mapped[int] = mapped_column(Integer, default=0)
    total_pendientes: Mapped[int] = mapped_column(Integer, default=0)
    mensaje: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    parametria: Mapped[Parametria] = relationship()
    asignaciones: Mapped[list[Asignacion]] = relationship(
        back_populates="ejecucion", cascade="all, delete-orphan"
    )


class Asignacion(Base):
    __tablename__ = "asignaciones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ejecucion_id: Mapped[int] = mapped_column(ForeignKey("asignacion_ejecuciones.id"), index=True)
    parametria_id: Mapped[int] = mapped_column(ForeignKey("parametria.id"), index=True)
    estudiante_id: Mapped[str] = mapped_column(ForeignKey("estudiantes.id"), index=True)
    periodo: Mapped[int] = mapped_column(Integer)
    especialidad: Mapped[str] = mapped_column(String(255))
    clinica_id: Mapped[int | None] = mapped_column(ForeignKey("clinicas.id"), nullable=True)
    institucion: Mapped[str] = mapped_column(String(255))
    pendiente: Mapped[bool] = mapped_column(Boolean, default=False)

    ejecucion: Mapped[AsignacionEjecucion] = relationship(back_populates="asignaciones")
    estudiante: Mapped[Estudiante] = relationship()
    clinica: Mapped[Clinica | None] = relationship()

    __table_args__ = (
        UniqueConstraint("ejecucion_id", "estudiante_id", "periodo", name="uq_ejec_est_periodo"),
    )

    @property
    def estudiante_nombre(self) -> str | None:
        return self.estudiante.nombre if self.estudiante else None

    @property
    def estudiante_semestre(self) -> str | None:
        return self.estudiante.semestre if self.estudiante else None
