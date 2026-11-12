"""Samples one process on one physical GPU. Other processes stay in the baseline."""

from __future__ import annotations

import subprocess
import threading
import time


class GpuSampler:
    def __init__(self, index: int) -> None:
        self.index = index
        self.samples: list[tuple[float, int | None]] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self.pid: int | None = None

    def start(self, pid: int) -> None:
        self.pid = pid
        self._thread.start()

    def stop(self) -> dict:
        self._stop.set()
        self._thread.join(timeout=5)
        owned = [used for _stamp, used in self.samples if used is not None]
        return {
            "samples": len(self.samples),
            "peak_process_mib": max(owned) if owned else None,
            "last_process_mib": owned[-1] if owned else None,
        }

    def _run(self) -> None:
        while not self._stop.is_set():
            self.samples.append((time.time(), self._used()))
            self._stop.wait(1)

    def _used(self) -> int | None:
        result = subprocess.run(
            ["nvidia-smi", f"--id={self.index}", "--query-compute-apps=pid,used_gpu_memory", "--format=csv,noheader,nounits"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return None
        for line in result.stdout.splitlines():
            pid, _comma, used = line.partition(",")
            if pid.strip() == str(self.pid):
                return int(used.strip())
        return None
