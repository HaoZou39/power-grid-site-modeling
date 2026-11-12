"""Start PostgreSQL 16 from the conda package cache, in a private data directory."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

_PKG = Path("/home/haozou/miniconda3/pkgs/postgresql-16.15-h23f1c25_0")
_SHARE = Path("/home/haozou/miniconda3/pkgs/libpq-16.15-hb2dfd55_0")


def library_path() -> str:
    roots = sorted(path for path in Path("/home/haozou/miniconda3/pkgs").glob("*/lib") if path.is_dir())
    return ":".join(str(path) for path in roots)


def binaries_available() -> bool:
    return (_PKG / "bin" / "postgres").is_file() and (_SHARE / "share" / "postgres.bki").is_file()


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _prefix(root: Path) -> Path:
    prefix = root / "prefix"
    bindir = prefix / "bin"
    libdir = prefix / "lib"
    sharedir = prefix / "share"
    bindir.mkdir(parents=True)
    libdir.mkdir()
    shutil.copytree(_SHARE / "share", sharedir)
    extension = _PKG / "share" / "extension"
    if extension.is_dir():
        target = sharedir / "extension"
        target.mkdir(exist_ok=True)
        for item in extension.iterdir():
            destination = target / item.name
            if not destination.exists():
                os.symlink(item, destination)
    for name in ("initdb", "postgres", "pg_isready", "psql", "createdb"):
        shutil.copy2(_PKG / "bin" / name, bindir / name)
    for directory in (_PKG / "lib", _SHARE / "lib"):
        for item in directory.glob("*.so*"):
            destination = libdir / item.name
            if not destination.exists():
                os.symlink(item, destination)
    return prefix


class LocalPostgres:
    def __init__(self, root: Path, password: str) -> None:
        self.root = root
        self.password = password
        self.port = _free_port()
        self.prefix = _prefix(root)
        self.process: subprocess.Popen[bytes] | None = None

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["LD_LIBRARY_PATH"] = f"{self.prefix / 'lib'}:{library_path()}"
        env["PGPASSWORD"] = self.password
        return env

    def start(self) -> None:
        env = self._env()
        password_file = self.root / "password"
        password_file.write_text(self.password, encoding="utf-8")
        password_file.chmod(0o600)
        init = subprocess.run(
            [
                str(self.prefix / "bin" / "initdb"), "-D", str(self.root / "data"),
                "-L", str(self.prefix / "share"), "--username=p2h2", f"--pwfile={password_file}",
                "--auth=scram-sha-256", "--encoding=UTF8", "--locale=C",
            ],
            env=env, check=False, capture_output=True, text=True,
        )
        if init.returncode != 0:
            raise RuntimeError(init.stderr[-2000:] or init.stdout[-2000:])
        log = open(self.root / "postgres.log", "ab")
        self.process = subprocess.Popen(
            [
                str(self.prefix / "bin" / "postgres"), "-D", str(self.root / "data"),
                "-c", "listen_addresses=127.0.0.1", "-c", f"port={self.port}",
                "-c", f"unix_socket_directories={self.root}",
            ],
            env=env, stdout=log, stderr=log,
        )
        deadline = time.monotonic() + 30
        ready = self.prefix / "bin" / "pg_isready"
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError((self.root / "postgres.log").read_text(encoding="utf-8", errors="replace")[-2000:])
            if subprocess.run([str(ready), "-h", "127.0.0.1", "-p", str(self.port)], env=env, stdout=subprocess.DEVNULL).returncode == 0:
                self._createdb("p2h2")
                self._createdb("p1_account_repair")
                return
            time.sleep(0.2)
        raise RuntimeError("PostgreSQL 在 30 秒内没有就绪")

    def _createdb(self, name: str) -> None:
        result = subprocess.run(
            [str(self.prefix / "bin" / "createdb"), "-h", "127.0.0.1", "-p", str(self.port), "-U", "p2h2", name],
            env=self._env(), check=False, capture_output=True, text=True,
        )
        if result.returncode != 0 and "already exists" not in result.stderr:
            raise RuntimeError(result.stderr)

    def url(self, database: str) -> str:
        return f"postgresql://p2h2:{self.password}@127.0.0.1:{self.port}/{database}"

    def version(self) -> str:
        result = subprocess.run(
            [str(self.prefix / "bin" / "psql"), "-h", "127.0.0.1", "-p", str(self.port), "-U", "p2h2", "-d", "p2h2", "-tAc", "SHOW server_version"],
            env=self._env(), check=True, capture_output=True, text=True,
        )
        return result.stdout.strip()

    def stop(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
