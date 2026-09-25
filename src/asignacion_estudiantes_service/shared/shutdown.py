from __future__ import annotations

import signal
import threading


class ShutdownSignal:
    def __init__(self) -> None:
        self._event = threading.Event()
        signal.signal(signal.SIGINT, self._handle)
        signal.signal(signal.SIGTERM, self._handle)

    def _handle(self, *_):
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout=timeout)
