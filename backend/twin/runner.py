"""
Runs the twin loop in a background thread, so the API process keeps the twin alive
(decision: the backend updates the twin on its own, whether or not anyone has the page open).
The API can stop it and start a new one with other settings (live / replay from a date / speed).
"""
from __future__ import annotations

import threading
import time
import traceback
from types import SimpleNamespace


class TwinRunner(threading.Thread):
    def __init__(self, mode: str | None = None, reset: bool = True, start: str | None = None,
                 speed: float | None = None, tick: float | None = None, data_from: str | None = None):
        super().__init__(daemon=True, name="twin-runner")
        self.args = SimpleNamespace(mode=mode, start=start, until=None, speed=speed, fast=False, reset=reset,
                                    data_from=data_from)
        self.tick = tick
        self.status = "starting"     # starting -> running -> stopped | error
        self.error: str | None = None
        self.last_step = None
        self.store = None
        self.source = None
        self._stop = threading.Event()

    def run(self):
        try:
            from scripts.run_twin import build   # heavy imports happen here, off the request path
            engine, source, clock, store, t, rt = build(self.args)
            self.store = store
            self.source = source
            from backend.twin.clock import STEP
            self.status = "running"
            while not self._stop.is_set():
                target = clock.now()
                while t <= target and not self._stop.is_set():
                    engine.step(t, source.get(t))
                    self.last_step = t
                    t += STEP
                engine.flush()
                self._stop.wait(self.tick or rt["tick_seconds"])
        except Exception as ex:  # noqa: BLE001 - reported through /api/health
            self.status = "error"
            self.error = f"{type(ex).__name__}: {ex}\n{traceback.format_exc(limit=3)}"
        finally:
            if self.store is not None:
                self.store.close()
            if self.status == "running":
                self.status = "stopped"

    def stop(self):
        self._stop.set()


def wait_until_ready(runner: TwinRunner, timeout: float = 120.0) -> bool:
    t0 = time.time()
    while runner.status == "starting" and time.time() - t0 < timeout:
        time.sleep(0.5)
    return runner.status == "running"
