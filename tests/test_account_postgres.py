"""Account schema and frozen legacy migration against an isolated PostgreSQL database."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest

URL = os.getenv("TEST_ACCOUNT_DATABASE_URL", "")


def _require_isolated_database() -> str:
    if not URL:
        pytest.skip("requires an isolated TEST_ACCOUNT_DATABASE_URL")
    parsed = urlparse(URL)
    name = parsed.path.lstrip("/")
    if name != "p1_account_repair":
        pytest.fail(f"refusing database {name or URL!r}; only p1_account_repair is allowed")
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        pytest.fail("refusing a non-local PostgreSQL host")
    return URL


def _reset(url: str) -> None:
    import psycopg

    with psycopg.connect(url) as connection:
        connection.execute("DROP TABLE IF EXISTS sessions, login_attempts, users, jobs")


def test_postgres_account_migration_is_idempotent_and_does_not_claim_new_rows(tmp_path: Path) -> None:
    url = _require_isolated_database()
    import psycopg

    from backend.app.infrastructure.account_store import AccountStore, verify_password
    from backend.app.infrastructure.postgres_repository import PostgresJobRepository
    from backend.app.application.legacy_ownership import freeze_manifest, migrate_legacy, restore_backup, save_manifest

    _reset(url)
    with psycopg.connect(url) as connection:
        connection.execute(
            """CREATE TABLE jobs (
                id TEXT PRIMARY KEY,
                plugin_id TEXT NOT NULL,
                plugin_version TEXT NOT NULL,
                config_json TEXT NOT NULL,
                status TEXT NOT NULL,
                progress DOUBLE PRECISION NOT NULL,
                stage TEXT NOT NULL,
                message TEXT NOT NULL,
                result_json TEXT,
                error_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            "INSERT INTO jobs VALUES ('old-job', 'demo.algorithm', '0', %s, 'succeeded', 1, 'done', '', NULL, NULL, 't', 't')",
            ('{"scene_name":"legacy-scene","values":[1]}',),
        )
    repository = PostgresJobRepository(url)
    store = AccountStore(url, repository)
    with psycopg.connect(url) as connection:
        preserved = connection.execute(
            "SELECT config_json, status, owner_id FROM jobs WHERE id = 'old-job'"
        ).fetchone()
    assert preserved == ('{"scene_name":"legacy-scene","values":[1]}', "succeeded", None)
    with psycopg.connect(url) as connection:
        columns = {row[0] for row in connection.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'jobs'"
        )}
        tables = {row[0] for row in connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )}
    assert "owner_id" in columns
    assert {"users", "sessions", "login_attempts", "jobs"} <= tables
    admin = store.create_user("pg-admin", "pg-admin-pass-9f3c", "admin")
    assert admin.password_hash.startswith("$argon2id$")
    assert verify_password(admin.password_hash, "pg-admin-pass-9f3c")
    assert store.authenticate("pg-admin", "wrong-pass-9f3c") is None
    logged = store.authenticate("pg-admin", "pg-admin-pass-9f3c")
    assert logged is not None and logged.id == admin.id
    token, _csrf, _expires = store.create_session(admin.id)
    assert store.session_user(token)[0].id == admin.id
    store.delete_session(token)
    assert store.session_user(token) is None
    token, _csrf, _expires = store.create_session(admin.id)
    store.set_disabled(admin.id, True)
    assert store.session_user(token) is None
    assert store.authenticate("pg-admin", "pg-admin-pass-9f3c") is None
    store.set_disabled(admin.id, False)
    output = tmp_path / "outputs"
    old = output / "old-run"
    old.mkdir(parents=True)
    (old / "run_summary.json").write_text(json.dumps({"n_feasible": 4}), encoding="utf-8")
    favorites = tmp_path / "favorites.sqlite3"
    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "MEMORY.md").write_text("旧记忆\n", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    save_manifest(manifest_path, freeze_manifest(store, output, favorites, memory))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    backup = tmp_path / "backup"
    state = tmp_path / "state.json"
    first = migrate_legacy(store, admin.id, output, favorites, memory, manifest, state, backup)
    assert first["jobs"] == 1 and repository.get_job("old-job").owner_id == admin.id
    with psycopg.connect(url) as connection:
        after = connection.execute("SELECT config_json, status FROM jobs WHERE id = 'old-job'").fetchone()
    assert after == ('{"scene_name":"legacy-scene","values":[1]}', "succeeded")
    assert json.loads((old / "run_summary.json").read_text(encoding="utf-8"))["n_feasible"] == 4
    before = (old / "run_summary.json").read_bytes()
    repository.create_job("new-job", "demo.algorithm", "0", {"values": [2]})
    (output / "new-run").mkdir()
    (output / "new-run" / "run_summary.json").write_text(json.dumps({"n_feasible": 8}), encoding="utf-8")
    second = migrate_legacy(store, admin.id, output, favorites, memory, manifest, state, backup)
    assert second["conflicts"] == []
    assert repository.get_job("new-job").owner_id is None
    assert repository.get_job("old-job").owner_id == admin.id
    assert (old / "run_summary.json").read_bytes() == before
    assert "owner_id" not in json.loads((output / "new-run" / "run_summary.json").read_text(encoding="utf-8"))
    restore_backup(store, output, favorites, memory, backup, admin.id)
    assert repository.get_job("old-job").owner_id is None
    assert json.loads((old / "run_summary.json").read_text(encoding="utf-8")) == {"n_feasible": 4}
    assert not (memory / "users" / admin.id / "MEMORY.md").exists()
    user_count = store.count_users()
    store.migrate()
    store.migrate()
    assert store.count_users() == user_count
    assert store.get_user(admin.id).username == "pg-admin"
    owned = repository.create_job("owned-job", "demo.algorithm", "0", {"kept": True}, owner_id=admin.id)
    assert repository.get_job(owned.id).owner_id == admin.id
    assert repository.get_job(owned.id).config == {"kept": True}


def test_postgres_cli_batch_two_apis_and_restore(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    url = _require_isolated_database()
    import sqlite3

    import psycopg
    from fastapi.testclient import TestClient

    from backend.app.application.legacy_ownership import main
    from backend.app.infrastructure.account_store import AccountStore
    from backend.app.infrastructure.favorite_repository import FavoritePointRepository
    from backend.app.infrastructure.postgres_repository import PostgresJobRepository
    from backend.app.main import create_app
    from experiments.auto_result_retention import retain_auto_results
    from tests.auth_flags import skip_auto_login

    _reset(url)
    legacy_config = '{"scene_name":"legacy-scene","n_feasible":4}'
    with psycopg.connect(url) as connection:
        connection.execute(
            """CREATE TABLE jobs (
                id TEXT PRIMARY KEY,
                plugin_id TEXT NOT NULL,
                plugin_version TEXT NOT NULL,
                config_json TEXT NOT NULL,
                status TEXT NOT NULL,
                progress DOUBLE PRECISION NOT NULL,
                stage TEXT NOT NULL,
                message TEXT NOT NULL,
                result_json TEXT,
                error_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            "INSERT INTO jobs VALUES ('old-job', 'demo.algorithm', '0', %s, 'succeeded', 1, 'done', '', NULL, NULL, 't', 't')",
            (legacy_config,),
        )
        connection.execute(
            "INSERT INTO jobs VALUES ('contested-job', 'demo.algorithm', '0', '{}', 'succeeded', 1, 'done', '', NULL, NULL, 't', 't')"
        )
    output = tmp_path / "outputs"
    old = output / "old-run"
    old.mkdir(parents=True)
    summary = {"n_feasible": 4, "n_pareto": 1}
    (old / "run_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    summary_bytes = (old / "run_summary.json").read_bytes()
    favorites = tmp_path / "favorites.sqlite3"
    FavoritePointRepository(favorites)
    with sqlite3.connect(favorites) as connection:
        connection.execute(
            "INSERT INTO favorite_points (id, scene_id, longitude, latitude, width_m, height_m, bearing_deg, created_at, updated_at) "
            "VALUES ('fav-old', 'cangnan', 1, 2, 3, 4, 5, 't', 't')"
        )
    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "MEMORY.md").write_text("旧记忆\n", encoding="utf-8")
    other_memory = memory / "users" / "other-person" / "MEMORY.md"
    other_memory.parent.mkdir(parents=True)
    other_memory.write_text("别人的记忆\n", encoding="utf-8")
    other_bytes = other_memory.read_bytes()
    manifest = tmp_path / "manifest.json"
    state = tmp_path / "state.json"
    backup = tmp_path / "backup"
    common = [
        "--database-url", url, "--output-root", str(output), "--favorite-db", str(favorites),
        "--memory-root", str(memory), "--manifest", str(manifest), "--state", str(state),
    ]
    assert main(["--freeze", *common]) == 0
    capsys.readouterr()
    assert main(["--dry-run", *common]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["migratable"]["jobs"] == ["contested-job", "old-job"]
    assert preview["migratable"]["experiments"] == ["old-run"]
    assert preview["migratable"]["favorites"] == ["fav-old"]
    store = AccountStore(url, PostgresJobRepository(url))
    other = store.create_user("other-owner", "other-pass-9f3c", "user")
    admin = store.create_user("cli-admin", "cli-admin-pass-9f3c", "admin")
    store._execute("UPDATE jobs SET owner_id = ? WHERE id = ?", (other.id, "contested-job"))
    assert main(["--apply", *common, "--admin-id", admin.id, "--backup-dir", str(backup)]) == 0
    applied = json.loads(capsys.readouterr().out)
    assert any(item["id"] == "contested-job" for item in applied["conflicts"])
    assert store._query("SELECT owner_id FROM jobs WHERE id = 'old-job'")[0][0] == admin.id
    assert store._query("SELECT owner_id, config_json, status FROM jobs WHERE id = 'contested-job'")[0] == (other.id, "{}", "succeeded")
    assert store._query("SELECT config_json, status FROM jobs WHERE id = 'old-job'")[0] == (legacy_config, "succeeded")
    assert (old / "run_summary.json").read_bytes() != summary_bytes
    stamped = json.loads((old / "run_summary.json").read_text(encoding="utf-8"))
    assert stamped["owner_id"] == admin.id and stamped["n_feasible"] == 4
    claimed_bytes = (old / "run_summary.json").read_bytes()
    assert main(["--status", *common]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["completed"]["jobs"] == 1 and status["remaining"]["jobs"] == 1
    repository = PostgresJobRepository(url)
    repository.create_job("new-job", "demo.algorithm", "0", {"values": [9]})
    fresh = output / "new-run"
    fresh.mkdir()
    (fresh / "run_summary.json").write_text(json.dumps({
        "n_feasible": 9, "result_origin": "auto", "problem_type": "site", "scene_name": "scene",
        "completed_at": "2026-02-01T00:00:00+00:00",
    }), encoding="utf-8")
    with sqlite3.connect(favorites) as connection:
        connection.execute(
            "INSERT INTO favorite_points (id, scene_id, longitude, latitude, width_m, height_m, bearing_deg, created_at, updated_at) "
            "VALUES ('fav-new', 'cangnan', 1, 2, 3, 4, 5, 't', 't')"
        )
    assert main(["--apply", *common, "--admin-id", admin.id, "--backup-dir", str(backup)]) == 0
    capsys.readouterr()
    assert repository.get_job("new-job").owner_id is None
    assert repository.get_job("old-job").owner_id == admin.id
    assert (old / "run_summary.json").read_bytes() == claimed_bytes
    assert "owner_id" not in json.loads((fresh / "run_summary.json").read_text(encoding="utf-8"))
    assert [row[0] for row in sqlite3.connect(favorites).execute(
        "SELECT id FROM favorite_points WHERE user_id = ?", (admin.id,)
    )] == ["fav-old"]
    assert [row[0] for row in sqlite3.connect(favorites).execute(
        "SELECT id FROM favorite_points WHERE user_id IS NULL"
    )] == ["fav-new"]
    assert other_memory.read_bytes() == other_bytes
    assert (memory / "users" / admin.id / "MEMORY.md").read_text(encoding="utf-8") == "旧记忆\n"
    retain_auto_results(output, scene_name="scene", problem_type="site", trigger_id="new-run", owner_id=admin.id)
    assert fresh.is_dir()
    left = AccountStore(url, PostgresJobRepository(url))
    token, _csrf, _expires = left.create_session(admin.id)
    right = AccountStore(url, PostgresJobRepository(url))
    assert right.session_user(token)[0].id == admin.id
    app_a = create_app(url, "", experiment_root=tmp_path / "api-a", favorite_db_path=tmp_path / "api-a.sqlite3")
    app_b = create_app(url, "", experiment_root=tmp_path / "api-b", favorite_db_path=tmp_path / "api-b.sqlite3")
    client_a = TestClient(app_a)
    client_b = TestClient(app_b)
    client_a.__enter__()
    client_b.__enter__()
    try:
        flag = skip_auto_login.set(True)
        try:
            logged = client_a.post("/api/v1/auth/login", json={"username": "cli-admin", "password": "cli-admin-pass-9f3c"})
        finally:
            skip_auto_login.reset(flag)
        assert logged.status_code == 200, logged.text
        client_b.cookies.set("site_session", client_a.cookies.get("site_session"))
        seen = client_b.get("/api/v1/auth/me")
        assert seen.status_code == 200, seen.text
        assert seen.json()["user"]["id"] == admin.id
    finally:
        client_a.__exit__(None, None, None)
        client_b.__exit__(None, None, None)
    assert main(["--restore", *common, "--admin-id", admin.id, "--backup-dir", str(backup)]) == 0
    assert repository.get_job("old-job").owner_id is None
    assert repository.get_job("contested-job").owner_id == other.id
    assert (old / "run_summary.json").read_bytes() == summary_bytes
    assert not (memory / "users" / admin.id / "MEMORY.md").exists()
    assert other_memory.read_bytes() == other_bytes
    assert [row[0] for row in sqlite3.connect(favorites).execute("SELECT id FROM favorite_points")] == ["fav-old"]
