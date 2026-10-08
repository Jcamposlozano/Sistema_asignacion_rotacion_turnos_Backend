from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from asignacion_estudiantes_service.domain.models import Base
from asignacion_estudiantes_service.shared.config import load_config

cfg = load_config()
DATABASE_URL = cfg["database"]["url"]

if DATABASE_URL.startswith("sqlite:///"):
    db_path = DATABASE_URL.replace("sqlite:///", "", 1)
    if db_path.startswith("./"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_columns()


def _ensure_sqlite_columns() -> None:
    if not DATABASE_URL.startswith("sqlite"):
        return

    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    if "estudiantes" not in table_names:
        return

    estudiantes_columns = {column["name"] for column in inspector.get_columns("estudiantes")}
    with engine.begin() as connection:
        if "semestre" not in estudiantes_columns:
            connection.execute(text("ALTER TABLE estudiantes ADD COLUMN semestre VARCHAR(20)"))

    if "parametria_periodo_fechas" not in table_names:
        return

    fechas_columns = {
        column["name"] for column in inspector.get_columns("parametria_periodo_fechas")
    }
    with engine.begin() as connection:
        if "fecha_inicio" not in fechas_columns:
            connection.execute(
                text("ALTER TABLE parametria_periodo_fechas ADD COLUMN fecha_inicio DATE")
            )
        if "fecha_fin" not in fechas_columns:
            connection.execute(
                text("ALTER TABLE parametria_periodo_fechas ADD COLUMN fecha_fin DATE")
            )
        if "fecha" in fechas_columns and "fecha_inicio" not in fechas_columns:
            connection.execute(
                text(
                    "UPDATE parametria_periodo_fechas "
                    "SET fecha_inicio = fecha "
                    "WHERE fecha_inicio IS NULL"
                )
            )


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
