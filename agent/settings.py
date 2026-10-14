"""Private assistant settings stored under the ignored memory directory."""

from __future__ import annotations

import ipaddress
import json
import os
import socket
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, TypeVar
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentSettings(_Model):
    memory_enabled: bool = True


class StoredModelConfig(_Model):
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None


class MemoryDisabledError(RuntimeError):
    pass


class SettingsFieldError(ValueError):
    def __init__(self, field: str, message: str) -> None:
        self.field = field
        super().__init__(message)


T = TypeVar("T")


def settings_directory() -> Path:
    raw = os.getenv("AGENT_SETTINGS_DIR", "").strip()
    if raw:
        return Path(raw)
    configured = os.getenv("AGENT_SETTINGS_PATH", "").strip()
    if configured:
        return Path(configured).parent
    return Path(__file__).resolve().parents[1] / "memory"


def settings_path() -> Path:
    raw = os.getenv("AGENT_SETTINGS_PATH", "").strip()
    return Path(raw) if raw else settings_directory() / "AGENT_SETTINGS.json"


def model_config_path() -> Path:
    raw = os.getenv("AGENT_MODEL_CONFIG_PATH", "").strip()
    return Path(raw) if raw else settings_directory() / "AGENT_MODEL_CONFIG.json"


@contextmanager
def settings_lock() -> Iterator[None]:
    directory = settings_directory()
    _secure_directory(directory)
    path = directory / ".agent-settings.lock"
    with open(path, "a+b") as handle:
        _secure_file(path)
        if os.name == "nt":
            import msvcrt

            if path.stat().st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def read_public_settings() -> dict[str, object]:
    with settings_lock():
        settings = _load_settings()
    public = _public_model()
    public["memory_enabled"] = settings.memory_enabled
    return public


def effective_model_config() -> dict[str, str]:
    path = env_file_path()
    with _env_lock(path):
        state = _ensure_startup_locked(path)
        resolved = _resolved_model(state, path)
        # Local Docker injects the host relay. Chat keeps using it; the settings page edits .env.
        relay = str(state["env"]["AGENT_BASE_URL"])  # type: ignore[index]
        if _is_local_relay(relay):
            resolved["AGENT_BASE_URL"] = relay.rstrip("/")
    return {
        "base_url": resolved["AGENT_BASE_URL"],
        "model": resolved["AGENT_MODEL"],
        "api_key": resolved["AGENT_API_KEY"],
    }


def update_model_config(
    *,
    base_url: str,
    model: str,
    api_key: str | None,
    clear_api_key: bool,
) -> None:
    if clear_api_key and api_key is not None and api_key.strip():
        raise SettingsFieldError("api_key", "清除 API Key 和填写新密钥不能同时进行。")
    path = env_file_path()
    with _env_lock(path):
        state = _ensure_startup_locked(path)
        current = _resolved_model(state, path)
        updates = _model_updates(
            state,
            current,
            base_url=base_url,
            model=model,
            api_key=api_key,
            clear_api_key=clear_api_key,
        )
        if updates:
            _write_env_keys_unlocked(path, updates)


def memory_snapshot(loader: Callable[[], T]) -> tuple[bool, T | None]:
    with settings_lock():
        enabled = _load_settings().memory_enabled
        return enabled, loader() if enabled else None


def memory_enabled() -> bool:
    with settings_lock():
        return _load_settings().memory_enabled


def mutate_memory(callback: Callable[[], T]) -> T:
    with settings_lock():
        if not _load_settings().memory_enabled:
            raise MemoryDisabledError("长期记忆未开启。")
        return callback()


def enable_memory() -> None:
    with settings_lock():
        _atomic_json(settings_path(), AgentSettings(memory_enabled=True).model_dump())


def disable_memory_and_clear(clear: Callable[[], None]) -> None:
    with settings_lock():
        _atomic_json(settings_path(), AgentSettings(memory_enabled=False).model_dump())
        clear()


def env_file_path() -> Path:
    raw = os.getenv("AGENT_ENV_FILE", "").strip()
    return Path(raw) if raw else Path(__file__).resolve().parents[1] / ".env"


def validate_base_url(value: str, *, trusted_current: str | None = None, resolve: bool = True) -> str:
    text = value.strip().rstrip("/")
    if trusted_current is not None and text == trusted_current.strip().rstrip("/"):
        return text
    parsed = urlsplit(text)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("API Base URL 不能包含凭据、查询参数或片段。")
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ValueError("API Base URL 必须是完整的 HTTPS 地址。")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("API Base URL 的端口无效。") from exc
    host = parsed.hostname.lower()
    # The container does not dial this URL when chat goes through the host relay.
    if not resolve:
        if parsed.scheme != "https":
            raise ValueError("API Base URL 必须是完整的 HTTPS 地址。")
        return text
    trusted_host = host in {"localhost", "host.docker.internal"}
    addresses = _resolve_addresses(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    loopback = trusted_host or bool(addresses) and all(address.is_loopback for address in addresses)
    if parsed.scheme == "http" and not loopback:
        raise ValueError("HTTP 只允许本机 loopback 或 host.docker.internal。")
    if host == "host.docker.internal":
        return text
    if not loopback and any(
        address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_multicast
        for address in addresses
    ):
        raise ValueError("API Base URL 不能解析到内网或保留地址。")
    return text


def validate_model(value: str) -> str:
    model = value.strip()
    if not model or len(model) > 128:
        raise ValueError("Model 必须是 1 到 128 个字符。")
    if any(character.isspace() or ord(character) < 32 for character in model):
        raise ValueError("Model 不能包含空白或控制字符。")
    return model


def _resolve_addresses(host: str, port: int) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("API Base URL 的主机无法解析。") from exc
    addresses = {ipaddress.ip_address(info[4][0].split("%", 1)[0]) for info in infos}
    if not addresses:
        raise ValueError("API Base URL 的主机无法解析。")
    return addresses


_MODEL_KEYS = ("AGENT_BASE_URL", "AGENT_MODEL", "AGENT_API_KEY")
_MODEL_LABELS = {"AGENT_BASE_URL": "API Base URL", "AGENT_MODEL": "Model", "AGENT_API_KEY": "API Key"}
_EXTERNAL_NOTICE = "标记为外部环境变量的字段由进程环境强制注入，保存 .env 不会改变它们。请修改 Docker Compose 或系统环境后重启 API。"
_RELAY_NOTICE = "本地对话经本机中继转发。这里显示和保存的是 .env 中的上游地址，下一次请求会转到新地址。"
_startup: dict[str, object] | None = None


def _public_model() -> dict[str, object]:
    path = env_file_path()
    with _env_lock(path):
        state = _ensure_startup_locked(path)
        resolved = _resolved_model(state, path)
        locked = state["locked"]
    relay = _is_local_relay(str(state["env"]["AGENT_BASE_URL"]))  # type: ignore[index]
    external = [_MODEL_LABELS[key] for key in _MODEL_KEYS if locked[key]]
    managed = [_MODEL_LABELS[key] for key in _MODEL_KEYS if not locked[key]]
    if external and managed:
        source = f"{'、'.join(external)} 来自外部环境变量；{'、'.join(managed)} 来自后端 .env"
    elif external:
        source = "外部环境变量"
    else:
        source = "后端 .env"
    return {
        "base_url": resolved["AGENT_BASE_URL"],
        "model": resolved["AGENT_MODEL"],
        "api_key_configured": bool(resolved["AGENT_API_KEY"]),
        "config_source": source,
        "base_url_editable": not locked["AGENT_BASE_URL"],
        "model_editable": not locked["AGENT_MODEL"],
        "api_key_editable": not locked["AGENT_API_KEY"],
        "external_notice": _RELAY_NOTICE if relay and not locked["AGENT_BASE_URL"] else (_EXTERNAL_NOTICE if external else ""),
    }


def _is_local_relay(value: str) -> bool:
    host = (urlsplit(value.strip()).hostname or "").lower()
    return host == "host.docker.internal"


def _model_updates(
    state: dict[str, object],
    current: dict[str, str],
    *,
    base_url: str,
    model: str,
    api_key: str | None,
    clear_api_key: bool,
) -> dict[str, str]:
    locked: dict[str, bool] = state["locked"]  # type: ignore[assignment]
    requested_url = base_url.strip().rstrip("/")
    requested_model = model.strip()
    if locked["AGENT_BASE_URL"] and requested_url != current["AGENT_BASE_URL"]:
        raise SettingsFieldError(
            "base_url",
            "API Base URL 由外部环境变量注入，修改 .env 不会改变当前生效值。请修改 Docker Compose 或系统环境中的 AGENT_BASE_URL 后重启 API。",
        )
    if locked["AGENT_MODEL"] and requested_model != current["AGENT_MODEL"]:
        raise SettingsFieldError(
            "model",
            "Model 由外部环境变量注入，修改 .env 不会改变当前生效值。请修改 Docker Compose 或系统环境中的 AGENT_MODEL 后重启 API。",
        )
    if locked["AGENT_API_KEY"] and (clear_api_key or (api_key is not None and api_key.strip())):
        raise SettingsFieldError(
            "api_key",
            "API Key 由外部环境变量提供。清除或替换 .env 中的值不会取消当前密钥，请从部署环境中修改 AGENT_API_KEY。",
        )
    updates: dict[str, str] = {}
    if not locked["AGENT_BASE_URL"]:
        try:
            updates["AGENT_BASE_URL"] = validate_base_url(
                requested_url,
                trusted_current=current["AGENT_BASE_URL"],
                resolve=not _is_local_relay(str(state["env"]["AGENT_BASE_URL"])),
            )
        except ValueError as exc:
            raise SettingsFieldError("base_url", str(exc)) from exc
    if not locked["AGENT_MODEL"]:
        try:
            updates["AGENT_MODEL"] = validate_model(requested_model)
        except ValueError as exc:
            raise SettingsFieldError("model", str(exc)) from exc
    if not locked["AGENT_API_KEY"]:
        if clear_api_key:
            updates["AGENT_API_KEY"] = ""
        elif api_key is not None and api_key.strip():
            updates["AGENT_API_KEY"] = api_key.strip()
    return updates


def _ensure_startup_locked(path: Path) -> dict[str, object]:
    global _startup
    env = {key: os.getenv(key, "").strip() for key in _MODEL_KEYS}
    marker = (str(path), tuple(env[key] for key in _MODEL_KEYS))
    if _startup is not None and _startup["marker"] == marker:
        return _startup
    values, present = _read_model_entries(path)
    # A process value that differs is what this process actually calls.
    # The local relay address is the Docker path, not the upstream edited in settings.
    locked = {
        key: bool(env[key])
        and (key not in present or values.get(key, "") != env[key])
        and not (key == "AGENT_BASE_URL" and _is_local_relay(env[key]))
        for key in _MODEL_KEYS
    }
    _migrate_model_json_locked(path, locked)
    _startup = {"marker": marker, "locked": locked, "env": env}
    return _startup


def _resolved_model(state: dict[str, object], path: Path) -> dict[str, str]:
    values, present = _read_model_entries(path)
    locked: dict[str, bool] = state["locked"]  # type: ignore[assignment]
    env: dict[str, str] = state["env"]  # type: ignore[assignment]
    resolved: dict[str, str] = {}
    for key in _MODEL_KEYS:
        if locked[key]:
            resolved[key] = env[key]
        elif key in present:
            resolved[key] = values[key]
        else:
            resolved[key] = env[key]
    return resolved


def _migrate_model_json_locked(path: Path, locked: dict[str, bool]) -> None:
    source = model_config_path()
    if not source.is_file():
        return
    try:
        stored = StoredModelConfig.model_validate(_read_json(source, {}))
    except ValueError:
        return
    raw = {
        "AGENT_BASE_URL": stored.base_url,
        "AGENT_MODEL": stored.model,
        "AGENT_API_KEY": stored.api_key,
    }
    updates: dict[str, str] = {}
    held_back = False
    for key, value in raw.items():
        if value is None or not value.strip():
            continue
        if locked[key]:
            held_back = True
            continue
        text = value.strip()
        updates[key] = text.rstrip("/") if key == "AGENT_BASE_URL" else text
    if updates:
        _write_env_keys_unlocked(path, updates)
        written, _present = _read_model_entries(path)
        if any(written.get(key) != expected for key, expected in updates.items()):
            return
    if not held_back:
        source.unlink()


def _read_model_entries(path: Path) -> tuple[dict[str, str], set[str]]:
    values: dict[str, str] = {}
    present: set[str] = set()
    text, _bom = _env_text(path)
    for line in text.splitlines():
        parsed = _parse_assignment(line)
        if parsed is None or parsed[0] not in _MODEL_KEYS:
            continue
        present.add(parsed[0])
        values[parsed[0]] = parsed[1]
    return values, present


def _parse_assignment(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    name, value = stripped.split("=", 1)
    name = name.strip()
    if not name:
        return None
    return name, value.strip().strip('"').strip("'")


def _write_env_keys_unlocked(path: Path, updates: dict[str, str]) -> None:
    original, bom = _env_text(path)
    newline = "\r\n" if "\r\n" in original else "\n"
    lines = original.splitlines()
    seen: set[str] = set()
    rewritten: list[str] = []
    for line in lines:
        parsed = _parse_assignment(line)
        if parsed is not None and parsed[0] in updates:
            if parsed[0] not in seen:
                rewritten.append(f"{parsed[0]}={_format_env_value(updates[parsed[0]])}")
                seen.add(parsed[0])
            continue
        rewritten.append(line)
    for key, value in updates.items():
        if key not in seen:
            rewritten.append(f"{key}={_format_env_value(value)}")
    text = newline.join(rewritten)
    if original.endswith(("\n", "\r\n")) or not original:
        text += newline
    _atomic_text(path, text, bom=bom)


def _format_env_value(value: str) -> str:
    if value == "":
        return ""
    if any(character in value for character in " \t#'\""):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def _env_text(path: Path) -> tuple[str, bool]:
    if not path.is_file():
        return "", False
    raw = path.read_bytes()
    return raw.decode("utf-8-sig"), raw.startswith(b"\xef\xbb\xbf")


@contextmanager
def _env_lock(path: Path) -> Iterator[None]:
    _secure_directory(path.parent)
    lock_path = path.with_name(path.name + ".lock")
    with open(lock_path, "a+b") as handle:
        _secure_file(lock_path)
        if os.name == "nt":
            import msvcrt

            if lock_path.stat().st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _atomic_text(path: Path, text: str, *, bom: bool) -> None:
    _secure_directory(path.parent)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
    payload = ("\ufeff" + text) if bom else text
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.replace(temp, path)
        except OSError as exc:
            # A bind-mounted .env cannot be renamed over on Docker Desktop.
            if exc.errno not in {16, 18}:
                raise
            data = temp.read_bytes()
            with open(path, "r+b") as handle:
                handle.write(data)
                handle.truncate()
                handle.flush()
                os.fsync(handle.fileno())
        _secure_file(path)
        try:
            os.chmod(path, mode)
        except OSError:
            pass
    finally:
        if temp.exists():
            temp.unlink()


def _load_settings() -> AgentSettings:
    return AgentSettings.model_validate(_read_json(settings_path(), {}))


def _read_json(path: Path, default: dict[str, object]) -> dict[str, object]:
    if not path.is_file():
        return default
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"设置文件不是有效 JSON：{path.name}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"设置文件必须是 JSON 对象：{path.name}")
    return value


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    _secure_directory(path.parent)
    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        _secure_file(path)
    finally:
        if temp.exists():
            temp.unlink()


def _secure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


def _secure_file(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
