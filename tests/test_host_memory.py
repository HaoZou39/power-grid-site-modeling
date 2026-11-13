"""Host RAM queries keep the batch planner's byte units on Windows and Linux."""

import ctypes
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from algorithms.guided_search import batch_planner

GiB = 1024**3


def test_windows_memory_uses_physical_bytes_and_does_not_read_proc(monkeypatch):
    monkeypatch.setattr(batch_planner, "sys", SimpleNamespace(platform="win32"))

    def no_proc(*_args, **_kwargs):
        raise AssertionError("Windows must not read /proc/meminfo")

    monkeypatch.setattr(Path, "read_text", no_proc)

    class Query:
        def __call__(self, pointer):
            status = ctypes.cast(pointer, self.argtypes[0]).contents
            assert status.dwLength == ctypes.sizeof(status) == 64
            status.ullTotalPhys = 64 * GiB
            status.ullAvailPhys = 21 * GiB
            status.ullTotalPageFile = 128 * GiB
            status.ullAvailPageFile = 90 * GiB
            return 1

    query = Query()

    def load_library(name, *, use_last_error):
        assert name == "kernel32" and use_last_error is True
        return SimpleNamespace(GlobalMemoryStatusEx=query)

    monkeypatch.setattr(ctypes, "WinDLL", load_library, raising=False)
    assert batch_planner.read_host_memory() == batch_planner.MemorySnapshot(21 * GiB, 64 * GiB)
    assert query.restype is ctypes.c_int


def test_windows_memory_query_failure_is_not_hidden(monkeypatch):
    monkeypatch.setattr(batch_planner, "sys", SimpleNamespace(platform="win32"))

    class Query:
        def __call__(self, _pointer):
            return 0

    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: SimpleNamespace(GlobalMemoryStatusEx=Query()), raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5, raising=False)
    monkeypatch.setattr(ctypes, "WinError", lambda error: OSError(error, "memory query denied"), raising=False)
    with pytest.raises(OSError, match="memory query denied") as error:
        batch_planner.read_host_memory()
    assert error.value.errno == 5


def test_linux_memory_keeps_available_ram_and_converts_kib_to_bytes(monkeypatch):
    monkeypatch.setattr(batch_planner, "sys", SimpleNamespace(platform="linux"))

    def meminfo(path, *, encoding):
        assert path.as_posix() == "/proc/meminfo" and encoding == "utf-8"
        return "MemTotal: 20000000 kB\nMemFree: 1000000 kB\nMemAvailable: 9000000 kB\n"

    monkeypatch.setattr(Path, "read_text", meminfo)
    assert batch_planner.read_host_memory() == batch_planner.MemorySnapshot(9000000 * 1024, 20000000 * 1024)


def test_linux_memory_requires_available_ram(monkeypatch):
    monkeypatch.setattr(batch_planner, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(Path, "read_text", lambda *_args, **_kwargs: "MemTotal: 10000000 kB\n")
    with pytest.raises(RuntimeError, match="MemTotal and MemAvailable are required"):
        batch_planner.read_host_memory()


@pytest.mark.skipif(sys.platform not in {"win32", "linux"}, reason="host RAM query supports Windows and Linux")
def test_native_host_memory_query():
    memory = batch_planner.read_host_memory()
    assert 0 < memory.free_bytes <= memory.total_bytes
