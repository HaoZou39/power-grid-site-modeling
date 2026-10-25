"""Assistant settings, model configuration and memory-disable guards."""

from __future__ import annotations

import ipaddress
import json
import os
import threading
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.config import AgentConfig, AgentNotConfigured
from agent.llm import ModelTurn, ToolCall
from agent.loop import AgentReply, ChatTurn, run_turn
from agent.memory import MemoryEntry, load_memory, memory_path, save_memory
from agent.settings import (
    SettingsFieldError,
    disable_memory_and_clear,
    memory_enabled,
    mutate_memory,
    update_model_config,
    validate_base_url,
)
from agent.tools import build_tools
from agent.workspace import Proposal
from backend.app.main import create_app
from backend.app.software_update import reset_for_tests
from tests.test_agent import _ScriptModel, _context, snapshot


def _seed_env(path: Path, *, base_url: str = "https://env.example/v1", model: str = "env-model", api_key: str = "env-secret") -> None:
    path.write_text(
        "# keep\nUPDATE_PASSWORD=admin-secret\n"
        f"AGENT_BASE_URL={base_url}\nAGENT_MODEL={model}\nAGENT_API_KEY={api_key}\nOTHER=keep\n",
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def _private_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    private = tmp_path / "memory"
    _seed_env(tmp_path / ".env")
    monkeypatch.setenv("AGENT_SETTINGS_DIR", str(private))
    monkeypatch.setenv("AGENT_MEMORY_PATH", str(private / "MEMORY.md"))
    monkeypatch.setenv("AGENT_ENV_FILE", str(tmp_path / ".env"))
    monkeypatch.setenv("AGENT_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("AGENT_MODEL", "env-model")
    monkeypatch.setenv("AGENT_API_KEY", "env-secret")
    monkeypatch.setenv("UPDATE_PASSWORD", "admin-secret")
    monkeypatch.setattr(
        "agent.settings._resolve_addresses",
        lambda _host, _port: {ipaddress.ip_address("8.8.8.8")},
    )
    reset_for_tests()
    return private


def test_model_write_requires_admin_before_touching_config():
    before = Path(os.environ["AGENT_ENV_FILE"]).read_bytes()
    client = TestClient(create_app("sqlite://:memory:", ""))
    response = client.put("/api/v1/agent/settings", json={"action":"update_model",
        "base_url":"https://env.example/v1", "model":"unauthorized"})
    assert response.status_code == 401
    assert Path(os.environ["AGENT_ENV_FILE"]).read_bytes() == before


def test_changed_destination_cannot_inherit_the_previous_key():
    before = Path(os.environ["AGENT_ENV_FILE"]).read_bytes()
    with pytest.raises(SettingsFieldError, match="新.*API Key|清除"):
        update_model_config(base_url="https://different.example/v1", model="next",
                            api_key=None, clear_api_key=False)
    assert Path(os.environ["AGENT_ENV_FILE"]).read_bytes() == before


@pytest.mark.parametrize("configured,password,status", [(True,"wrong",401),(False,"admin-secret",503),(True,"admin-secret",200)])
def test_model_admin_failures_and_success_leave_no_password_in_public_data(monkeypatch, configured, password, status):
    if not configured:
        monkeypatch.delenv("UPDATE_PASSWORD")
    before = Path(os.environ["AGENT_ENV_FILE"]).read_bytes()
    response = TestClient(create_app("sqlite://:memory:", "")).put("/api/v1/agent/settings", json={
        "action":"update_model", "password":password, "base_url":"https://env.example/v1", "model":"new-model"})
    assert response.status_code == status
    assert password not in response.text
    if status != 200:
        assert Path(os.environ["AGENT_ENV_FILE"]).read_bytes() == before


def test_locked_external_key_forbids_destination_change(monkeypatch):
    monkeypatch.setenv("AGENT_API_KEY", "externally-forced-fake-key")
    with pytest.raises(SettingsFieldError, match="外部环境锁定"):
        update_model_config(base_url="https://different.example/v1", model="next", api_key=None, clear_api_key=False)


def test_explicit_clear_changes_destination_without_leaking_previous_key():
    update_model_config(base_url="https://different.example/v1", model="next", api_key=None, clear_api_key=True)
    text = Path(os.environ["AGENT_ENV_FILE"]).read_text()
    assert "AGENT_BASE_URL=https://different.example/v1" in text
    assert "env-secret" not in text


def test_settings_default_to_memory_enabled_and_hide_the_key() -> None:
    body = TestClient(create_app("sqlite://:memory:", "")).get("/api/v1/agent/settings")
    assert body.status_code == 200
    assert body.json() == {
        "memory_enabled": True,
        "base_url": "https://env.example/v1",
        "model": "env-model",
        "api_key_configured": True,
        "config_source": "后端 .env",
        "base_url_editable": True,
        "model_editable": True,
        "api_key_editable": True,
        "external_notice": "",
    }
    assert "env-secret" not in body.text


def test_ui_model_config_has_priority_and_blank_key_is_preserved(
    _private_settings: Path,
) -> None:
    client = TestClient(create_app("sqlite://:memory:", ""))
    env_mode = Path(os.environ["AGENT_ENV_FILE"]).stat().st_mode & 0o777
    saved = client.put("/api/v1/agent/settings", json={
        "action": "update_model",
        "password": "admin-secret",
        "base_url": "https://api.example.com/v1",
        "model": "ui-model",
        "api_key": "ui-secret",
        "clear_api_key": False,
    })
    assert saved.status_code == 200
    assert "ui-secret" not in saved.text
    assert AgentConfig.from_env().api_key == "ui-secret"

    kept = client.put("/api/v1/agent/settings", json={
        "action": "update_model",
        "password": "admin-secret",
        "base_url": "https://api.example.com/v1",
        "model": "ui-model-2",
        "api_key": "   ",
        "clear_api_key": False,
    })
    assert kept.status_code == 200
    assert AgentConfig.from_env().api_key == "ui-secret"
    assert AgentConfig.from_env().model == "ui-model-2"
    assert os.environ["AGENT_API_KEY"] == "env-secret"

    cleared = client.put("/api/v1/agent/settings", json={
        "action": "update_model",
        "password": "admin-secret",
        "base_url": "https://api.example.com/v1",
        "model": "ui-model-2",
        "clear_api_key": True,
    })
    assert cleared.status_code == 200
    assert cleared.json()["api_key_configured"] is False
    with pytest.raises(AgentNotConfigured):
        AgentConfig.from_env()
    stored = Path(os.environ["AGENT_ENV_FILE"]).read_text(encoding="utf-8")
    assert "ui-secret" not in stored
    assert "AGENT_API_KEY=" in stored
    assert "UPDATE_PASSWORD=admin-secret" in stored
    assert "OTHER=keep" in stored
    assert "# keep" in stored
    assert Path(os.environ["AGENT_ENV_FILE"]).stat().st_mode & 0o777 == env_mode


@pytest.mark.parametrize(
    ("base_url", "model"),
    [
        ("http://api.example.com/v1", "valid"),
        ("https://10.0.0.1/v1", "valid"),
        ("https://api.example.com/v1?key=x", "valid"),
        ("https://api.example.com/v1", "bad model"),
    ],
)
def test_model_settings_validate_url_and_model(
    monkeypatch: pytest.MonkeyPatch,
    base_url: str,
    model: str,
) -> None:
    monkeypatch.setattr(
        "agent.settings._resolve_addresses",
        lambda host, _port: {
            ipaddress.ip_address("10.0.0.1" if host == "10.0.0.1" else "8.8.8.8")
        },
    )
    before = Path(os.environ["AGENT_ENV_FILE"]).read_text(encoding="utf-8")
    response = TestClient(create_app("sqlite://:memory:", "")).put("/api/v1/agent/settings", json={
        "action": "update_model",
        "password": "admin-secret",
        "base_url": base_url,
        "model": model,
        "clear_api_key": False,
    })
    assert response.status_code == 422
    assert Path(os.environ["AGENT_ENV_FILE"]).read_text(encoding="utf-8") == before


def test_disabling_memory_clears_only_text_memory_and_persists(
    _private_settings: Path,
) -> None:
    client = TestClient(create_app("sqlite://:memory:", ""))
    written = client.post("/api/v1/agent/memory", json={
        "scene_name": "cangnan",
        "ops": [{"kind": "remember", "section": "preference", "source": "stated", "text": "优先平坦区域"}],
    })
    assert written.status_code == 200
    choices = _private_settings / "PREFERENCE_CHOICES.jsonl"
    defaults = _private_settings / "PREFERENCE_DEFAULTS.json"
    choices.write_text('{"choice":"keep"}\n', encoding="utf-8")
    defaults.write_text('{"weights":{"dem_soft":5}}\n', encoding="utf-8")

    disabled = client.put("/api/v1/agent/settings", json={
        "action": "disable_memory_and_clear",
    })
    assert disabled.status_code == 200
    assert disabled.json()["memory_enabled"] is False
    assert not memory_path().exists()
    assert choices.read_text(encoding="utf-8") == '{"choice":"keep"}\n'
    assert defaults.read_text(encoding="utf-8") == '{"weights":{"dem_soft":5}}\n'

    assert TestClient(create_app("sqlite://:memory:", "")).get("/api/v1/agent/settings").json()["memory_enabled"] is False
    assert client.get("/api/v1/agent/memory").json()["entries"] == []
    assert not memory_path().exists()
    rejected = client.post("/api/v1/agent/memory", json={
        "scene_name": "cangnan",
        "ops": [{"kind": "remember", "section": "preference", "source": "stated", "text": "不能写"}],
    })
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "memory_disabled"
    assert not memory_path().exists()

    enabled = client.put("/api/v1/agent/settings", json={"action": "enable_memory"})
    assert enabled.status_code == 200
    again = client.post("/api/v1/agent/memory", json={
        "scene_name": "cangnan",
        "ops": [{"kind": "remember", "section": "preference", "source": "stated", "text": "重新开始"}],
    })
    assert again.json()["entries"][0]["id"] == "m1"


def test_memory_disabled_removes_schema_and_keeps_map_edits() -> None:
    tools = build_tools(replace(_context(), memory_enabled=False))
    propose = {tool.name: tool for tool in tools}["propose_changes"]
    assert '"memory"' not in json.dumps(propose.params_schema)
    with pytest.raises(ValueError, match="长期记忆"):
        propose.handler({
            "rationale": "记住",
            "ops": [{"kind": "clear_origin"}],
            "memory": [{"kind": "remember", "section": "preference", "source": "stated", "text": "x"}],
        })

    pure = run_turn(
        _ScriptModel([]),
        tools,
        [ChatTurn("user", "记住以后优先选择地势平坦的地方。")],
        snapshot(),
        2,
        memory_enabled=False,
    )
    assert pure.proposal is None
    assert "长期记忆未开启" in pure.message

    model = _ScriptModel([
        ModelTurn("", [ToolCall("1", "propose_changes", {
            "rationale": "长期记忆未开启，只移动本次方案。",
            "ops": [{"kind": "update_pose", "pose_id": "pose-1", "x": 30}],
        })]),
    ])
    mixed = run_turn(
        model,
        tools,
        [ChatTurn("user", "把方案 1 向东移动 20 米，以后都这样。")],
        snapshot(),
        2,
        memory_enabled=False,
    )
    assert mixed.proposal is not None
    assert mixed.proposal.memory == []
    assert mixed.proposal.ops[0].kind == "update_pose"


def test_inflight_memory_proposal_is_removed_after_disable(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run_turn(*_args, **_kwargs):
        disable_memory_and_clear(lambda: memory_path().unlink(missing_ok=True))
        return AgentReply(
            message="准备记住。",
            proposal=Proposal.model_validate({
                "rationale": "记住",
                "memory": [{"kind": "remember", "section": "preference", "source": "stated", "text": "平坦"}],
            }),
            tool_trace=[],
        )

    monkeypatch.setattr("backend.app.api.agent_routes.run_turn", fake_run_turn)
    response = TestClient(create_app("sqlite://:memory:", "")).post("/api/v1/agent/chat", json={
        "messages": [{"role": "user", "content": "记住平坦"}],
        "snapshot": snapshot().model_dump(mode="json"),
    })
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]["reply"]["proposal"] is None
    assert "长期记忆未开启" in events[-1]["reply"]["message"]


def test_concurrent_write_cannot_restore_memory_after_disable() -> None:
    original = MemoryEntry(
        id="m1",
        section="preference",
        scene=None,
        date="2026-10-14",
        source="stated",
        text="原有记忆",
    )
    save_memory(memory_path(), [original])
    entered = threading.Event()
    release = threading.Event()

    def write() -> None:
        def callback() -> None:
            entered.set()
            assert release.wait(2)
            save_memory(memory_path(), [
                *load_memory(memory_path()),
                original.model_copy(update={"id": "m2", "text": "并发写入"}),
            ])
        mutate_memory(callback)

    writer = threading.Thread(target=write)
    writer.start()
    assert entered.wait(2)
    closer = threading.Thread(target=lambda: disable_memory_and_clear(lambda: memory_path().unlink(missing_ok=True)))
    closer.start()
    release.set()
    writer.join(2)
    closer.join(2)
    assert memory_enabled() is False
    assert not memory_path().exists()


def test_saved_model_applies_to_the_next_request_without_changing_process_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(create_app("sqlite://:memory:", ""))
    saved = client.put("/api/v1/agent/settings", json={
        "action": "update_model",
        "password": "admin-secret",
        "base_url": "https://api.example.com/v1",
        "model": "next-model",
        "api_key": "replacement-secret",
        "clear_api_key": False,
    })
    assert saved.status_code == 200
    assert os.environ["AGENT_MODEL"] == "env-model"
    assert AgentConfig.from_env().model == "next-model"
    assert AgentConfig.from_env().base_url == "https://api.example.com/v1"
    assert AgentConfig.from_env().api_key == "replacement-secret"
    monkeypatch.setenv("AGENT_MODEL", "next-model")
    monkeypatch.setenv("AGENT_BASE_URL", "https://api.example.com/v1")
    assert AgentConfig.from_env().model == "next-model"


def test_relay_override_shows_and_saves_the_env_file_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_BASE_URL", "http://host.docker.internal:18080/v1")
    client = TestClient(create_app("sqlite://:memory:", ""))
    current = client.get("/api/v1/agent/settings")
    assert current.status_code == 200
    body = current.json()
    assert body["base_url"] == "https://env.example/v1"
    assert body["base_url_editable"] is True
    assert "中继" in body["external_notice"]
    assert "host.docker.internal" not in body["base_url"]

    saved = client.put("/api/v1/agent/settings", json={
        "action": "update_model",
        "password": "admin-secret",
        "base_url": "https://api.example.com/v1",
        "model": "next-model",
        "api_key": "replacement-secret",
        "clear_api_key": False,
    })
    assert saved.status_code == 200
    assert saved.json()["base_url"] == "https://api.example.com/v1"
    assert AgentConfig.from_env().base_url == "http://host.docker.internal:18080/v1"
    assert AgentConfig.from_env().model == "next-model"
    text = Path(os.environ["AGENT_ENV_FILE"]).read_text(encoding="utf-8")
    assert "AGENT_BASE_URL=https://api.example.com/v1" in text
    assert "AGENT_MODEL=next-model" in text


def test_non_relay_process_base_url_cannot_be_saved_over(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_BASE_URL", "https://forced.example/v1")
    client = TestClient(create_app("sqlite://:memory:", ""))
    body = client.get("/api/v1/agent/settings").json()
    assert body["base_url"] == "https://forced.example/v1"
    assert body["base_url_editable"] is False
    env_path = Path(os.environ["AGENT_ENV_FILE"])
    before = env_path.read_text(encoding="utf-8")
    rejected = client.put("/api/v1/agent/settings", json={
        "action": "update_model",
        "password": "admin-secret",
        "base_url": "https://api.example.com/v1",
        "model": "next-model",
        "clear_api_key": False,
    })
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["field"] == "base_url"
    assert env_path.read_text(encoding="utf-8") == before
    assert AgentConfig.from_env().base_url == "https://forced.example/v1"


def test_relay_accepts_campus_url_the_container_cannot_resolve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_BASE_URL", "http://host.docker.internal:18080/v1")

    def fail_resolution(_host: str, _port: int) -> set[ipaddress.IPv4Address]:
        raise ValueError("API Base URL 的主机无法解析。")

    monkeypatch.setattr("agent.settings._resolve_addresses", fail_resolution)
    saved = TestClient(create_app("sqlite://:memory:", "")).put("/api/v1/agent/settings", json={
        "action": "update_model",
        "password": "admin-secret",
        "base_url": "https://hpc-api.westlake.edu.cn/v1",
        "model": "env-model",
        "api_key": "replacement-secret",
        "clear_api_key": False,
    })
    assert saved.status_code == 200
    assert saved.json()["base_url"] == "https://hpc-api.westlake.edu.cn/v1"
    assert "AGENT_BASE_URL=https://hpc-api.westlake.edu.cn/v1" in Path(os.environ["AGENT_ENV_FILE"]).read_text(encoding="utf-8")
    assert AgentConfig.from_env().base_url == "http://host.docker.internal:18080/v1"


def test_docker_host_http_is_an_allowed_new_target(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "agent.settings._resolve_addresses",
        lambda _host, _port: {ipaddress.ip_address("192.168.65.2")},
    )
    assert validate_base_url("http://host.docker.internal:18080/v1") == "http://host.docker.internal:18080/v1"


def test_model_json_migrates_into_env_then_is_removed(_private_settings: Path) -> None:
    source = _private_settings / "AGENT_MODEL_CONFIG.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        json.dumps({"base_url": "https://api.example.com/v1", "model": "json-model", "api_key": "json-secret"}),
        encoding="utf-8",
    )
    body = TestClient(create_app("sqlite://:memory:", "")).get("/api/v1/agent/settings")
    assert body.status_code == 200
    assert body.json()["model"] == "json-model"
    assert body.json()["base_url"] == "https://api.example.com/v1"
    assert "json-secret" not in body.text
    assert not source.exists()
    text = Path(os.environ["AGENT_ENV_FILE"]).read_text(encoding="utf-8")
    assert "AGENT_MODEL=json-model" in text
    assert "AGENT_API_KEY=json-secret" in text
    assert "OTHER=keep" in text
    assert AgentConfig.from_env().api_key == "json-secret"


def test_json_base_url_migrates_when_process_env_differs(
    monkeypatch: pytest.MonkeyPatch,
    _private_settings: Path,
) -> None:
    monkeypatch.setenv("AGENT_BASE_URL", "http://host.docker.internal:18080/v1")
    source = _private_settings / "AGENT_MODEL_CONFIG.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        json.dumps({"base_url": "https://api.example.com/v1", "model": "json-model"}),
        encoding="utf-8",
    )
    body = TestClient(create_app("sqlite://:memory:", "")).get("/api/v1/agent/settings")
    assert body.json()["base_url"] == "https://api.example.com/v1"
    assert body.json()["model"] == "json-model"
    assert not source.exists()
    text = Path(os.environ["AGENT_ENV_FILE"]).read_text(encoding="utf-8")
    assert "AGENT_BASE_URL=https://api.example.com/v1" in text
    assert "AGENT_MODEL=json-model" in text
    assert AgentConfig.from_env().base_url == "http://host.docker.internal:18080/v1"


def test_memory_toggle_does_not_change_model_env() -> None:
    before = Path(os.environ["AGENT_ENV_FILE"]).read_text(encoding="utf-8")
    client = TestClient(create_app("sqlite://:memory:", ""))
    disabled = client.put("/api/v1/agent/settings", json={"action": "disable_memory_and_clear"})
    assert disabled.status_code == 200
    assert disabled.json()["model"] == "env-model"
    assert Path(os.environ["AGENT_ENV_FILE"]).read_text(encoding="utf-8") == before


def test_env_write_falls_back_when_replace_is_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_replace(_src: str, _dst: str) -> None:
        raise OSError(16, "busy")

    monkeypatch.setattr("agent.settings.os.replace", fail_replace)
    saved = TestClient(create_app("sqlite://:memory:", "")).put("/api/v1/agent/settings", json={
        "action": "update_model",
        "password": "admin-secret",
        "base_url": "https://env.example/v1",
        "model": "fallback-model",
        "clear_api_key": False,
    })
    assert saved.status_code == 200
    text = Path(os.environ["AGENT_ENV_FILE"]).read_text(encoding="utf-8")
    assert "AGENT_MODEL=fallback-model" in text
    assert "OTHER=keep" in text


def test_concurrent_model_saves_keep_the_env_file_intact() -> None:
    errors: list[BaseException] = []

    def save(model: str) -> None:
        try:
            update_model_config(
                base_url="https://env.example/v1",
                model=model,
                api_key=None,
                clear_api_key=False,
            )
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=save, args=(name,)) for name in ("model-a", "model-b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert errors == []
    text = Path(os.environ["AGENT_ENV_FILE"]).read_text(encoding="utf-8")
    assert "# keep" in text
    assert "UPDATE_PASSWORD=admin-secret" in text
    assert "OTHER=keep" in text
    assert text.count("AGENT_MODEL=") == 1
    assert "AGENT_MODEL=model-a" in text or "AGENT_MODEL=model-b" in text
