from __future__ import annotations

import time

from asignacion_estudiantes_service.shared.config import load_config
from asignacion_estudiantes_service.shared.logger import get_logger
from asignacion_estudiantes_service.shared.shutdown import ShutdownSignal

log = get_logger("asignacion_estudiantes_service.worker")


def tick() -> None:
    log.info("Worker tick ✅ (placeholder)")


def main() -> None:
    cfg = load_config()
    if not cfg["worker"]["enabled"]:
        log.info("Worker deshabilitado por config.")
        return
    interval = cfg["worker"]["interval_seconds"]
    shutdown = ShutdownSignal()
    log.info(f"Worker iniciado. interval_seconds={interval}")
    while not shutdown.is_set():
        start = time.time()
        try:
            tick()
        except Exception as e:
            log.exception(f"Error en tick: {e}")
        elapsed = time.time() - start
        shutdown.wait(timeout=max(0.0, interval - elapsed))
    log.info("Worker detenido (shutdown).")


if __name__ == "__main__":
    main()
