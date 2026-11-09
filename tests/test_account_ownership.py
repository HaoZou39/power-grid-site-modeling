"""Account login, resource ownership and the legacy migration. Temporary directories only."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.infrastructure.account_store import AccountStore
from backend.app.infrastructure.repository import SQLiteJobRepository
from backend.app.main import create_app
from experiments.auto_result_retention import auto_marker_fields, retain_auto_results, retain_published_auto_result
from experiments.ownership import bind_owner, reset_owner
from tests.auth_flags import skip_auto_login

PASSWORD = "user-pass-9f3c"


def _app(tmp_path: Path) -> TestClient:
    app = create_app(
        f"sqlite:///{tmp_path / 'app.sqlite3'}",
        "",
        experiment_root=tmp_path / "outputs",
        favorite_db_path=tmp_path / "favorites.sqlite3",
    )
    client = TestClient(app)
    client.__enter__()
    return client


def _login(client: TestClient, username: str, password: str) -> dict:
    token = skip_auto_login.set(True)
    try:
        response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    finally:
        skip_auto_login.reset(token)
    assert response.status_code == 200, response.text
    client.csrf_token = response.json()["csrf_token"]
    return response.json()["user"]


def _users(admin: TestClient) -> None:
    assert admin.post("/api/v1/admin/users", json={"username": "user_A", "password": PASSWORD, "role": "user"}).status_code == 201
    assert admin.post("/api/v1/admin/users", json={"username": "user_B", "password": PASSWORD, "role": "user"}).status_code == 201


def test_private_routes_require_login(tmp_path: Path) -> None:
    client = _app(tmp_path)
    token = skip_auto_login.set(True)
    try:
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/v1/experiments").status_code == 401
        assert client.get("/api/v1/jobs/missing").status_code == 401
    finally:
        skip_auto_login.reset(token)


def test_admin_creates_and_disables_accounts(tmp_path: Path) -> None:
    admin = _app(tmp_path)
    _login(admin, "pytest-admin", os.environ["BOOTSTRAP_ADMIN_PASSWORD"])
    created = admin.post("/api/v1/admin/users", json={"username": "user_A", "password": PASSWORD, "role": "user"})
    assert created.status_code == 201
    user_id = created.json()["id"]
    user = TestClient(admin.app)
    _login(user, "user_A", PASSWORD)
    assert user.get("/api/v1/auth/me").json()["user"]["username"] == "user_A"
    assert admin.patch(f"/api/v1/admin/users/{user_id}", json={"disabled": True}).status_code == 200
    assert user.get("/api/v1/experiments").status_code == 401


def test_wrong_password_is_limited(tmp_path: Path) -> None:
    client = _app(tmp_path)
    token = skip_auto_login.set(True)
    try:
        for _ in range(5):
            assert client.post("/api/v1/auth/login", json={"username": "nobody", "password": "wrong-pass"}).status_code == 401
        assert client.post("/api/v1/auth/login", json={"username": "nobody", "password": "wrong-pass"}).status_code == 429
    finally:
        skip_auto_login.reset(token)


def test_logout_invalidates_the_cookie(tmp_path: Path) -> None:
    client = _app(tmp_path)
    _login(client, "pytest-admin", os.environ["BOOTSTRAP_ADMIN_PASSWORD"])
    assert client.post("/api/v1/auth/logout").status_code == 200
    token = skip_auto_login.set(True)
    try:
        assert client.get("/api/v1/auth/me").status_code == 401
    finally:
        skip_auto_login.reset(token)


def test_users_cannot_see_each_others_jobs(tmp_path: Path) -> None:
    admin = _app(tmp_path)
    _login(admin, "pytest-admin", os.environ["BOOTSTRAP_ADMIN_PASSWORD"])
    _users(admin)
    user_a = TestClient(admin.app)
    user_b = TestClient(admin.app)
    _login(user_a, "user_A", PASSWORD)
    _login(user_b, "user_B", PASSWORD)
    created = user_a.post("/api/v1/jobs", json={"plugin_id": "demo.algorithm", "config": {"values": [1], "multiplier": 2}})
    assert created.status_code == 202, created.text
    job_id = created.json()["job_id"]
    assert user_b.get(f"/api/v1/jobs/{job_id}").status_code == 404
    assert user_b.post(f"/api/v1/jobs/{job_id}/cancel").status_code == 404
    assert admin.get(f"/api/v1/jobs/{job_id}").status_code == 200
    stored = admin.app.state.job_service.repository.get_job(job_id)
    assert stored.owner_id == user_a.get("/api/v1/auth/me").json()["user"]["id"]
    assert "owner_id" not in stored.config


def test_users_cannot_read_each_others_experiments(tmp_path: Path) -> None:
    admin = _app(tmp_path)
    _login(admin, "pytest-admin", os.environ["BOOTSTRAP_ADMIN_PASSWORD"])
    _users(admin)
    user_a = TestClient(admin.app)
    user_b = TestClient(admin.app)
    owner_a = _login(user_a, "user_A", PASSWORD)["id"]
    owner_b = _login(user_b, "user_B", PASSWORD)["id"]
    root = tmp_path / "outputs"
    for name, owner in (("run-a", owner_a), ("run-b", owner_b)):
        directory = root / name
        directory.mkdir(parents=True)
        (directory / "run_summary.json").write_text(json.dumps({"owner_id": owner, "n_pareto": 1}), encoding="utf-8")
        (directory / "solutions.csv").write_text("id\n1\n", encoding="utf-8")
    assert [item["id"] for item in user_a.get("/api/v1/experiments").json()] == ["run-a"]
    assert user_a.get("/api/v1/experiments/run-b").status_code == 404
    assert user_a.get("/api/v1/experiments/run-b/artifacts/solutions.csv").status_code == 404
    assert user_a.delete("/api/v1/experiments/run-b").status_code == 404
    assert (root / "run-b").is_dir()
    assert {item["id"] for item in admin.get("/api/v1/experiments").json()} == {"run-a", "run-b"}


def test_foreign_save_sources_are_rejected(tmp_path: Path) -> None:
    admin = _app(tmp_path)
    _login(admin, "pytest-admin", os.environ["BOOTSTRAP_ADMIN_PASSWORD"])
    _users(admin)
    user_a = TestClient(admin.app)
    owner_b = _login(TestClient(admin.app), "user_B", PASSWORD)["id"]
    _login(user_a, "user_A", PASSWORD)
    directory = tmp_path / "outputs" / "owned-by-b"
    directory.mkdir(parents=True)
    (directory / "run_summary.json").write_text(json.dumps({"owner_id": owner_b, "algorithm": "guided_search"}), encoding="utf-8")
    body = {
        "name": "案例", "scene_name": "demo", "source_experiment_id": "owned-by-b",
        "rect_w_m": 4, "rect_h_m": 3, "mountain_policy": "allowed", "field_policy": "allowed", "field_cost": 0.5,
        "road_setback_m": 0, "water_setback_m": 0, "exclusion_zones": [], "feasible_zones": [], "include_demand": False,
        "poses": [{"id": "kept", "x": 1, "y": 1, "theta": 0, "pareto_layer": 1}],
    }
    assert user_a.post("/api/v1/experiments", json=body).status_code == 404
    body["fast_save_source_experiment_id"] = "owned-by-b"
    body["source_experiment_id"] = None
    assert user_a.post("/api/v1/experiments", json=body).status_code == 404


def test_favorites_stay_with_their_user(tmp_path: Path) -> None:
    (tmp_path / "scenes" / "cangnan").mkdir(parents=True)
    admin = _app(tmp_path)
    _login(admin, "pytest-admin", os.environ["BOOTSTRAP_ADMIN_PASSWORD"])
    _users(admin)
    user_a = TestClient(admin.app)
    user_b = TestClient(admin.app)
    _login(user_a, "user_A", PASSWORD)
    _login(user_b, "user_B", PASSWORD)
    url = "/api/v1/scenes/cangnan/favorites"
    body = {"longitude": 120.2, "latitude": 27.5, "width_m": 30, "height_m": 40, "bearing_deg": 10}
    created = user_a.post(url, json=body)
    assert created.status_code == 201, created.text
    assert user_b.get(url).json() == []
    assert user_b.delete(f"{url}/{created.json()['id']}").status_code == 404
    assert len(user_a.get(url).json()) == 1


def test_memory_and_preferences_are_per_user(tmp_path: Path) -> None:
    admin = _app(tmp_path)
    _login(admin, "pytest-admin", os.environ["BOOTSTRAP_ADMIN_PASSWORD"])
    _users(admin)
    user_a = TestClient(admin.app)
    user_b = TestClient(admin.app)
    owner_a = _login(user_a, "user_A", PASSWORD)["id"]
    owner_b = _login(user_b, "user_B", PASSWORD)["id"]
    written = user_a.post("/api/v1/agent/memory", json={
        "scene_name": "cangnan",
        "ops": [{"kind": "remember", "section": "preference", "source": "stated", "text": "只要 A 的记忆"}],
    })
    assert written.status_code == 200, written.text
    assert user_b.get("/api/v1/agent/memory").json()["entries"] == []
    root = Path(os.environ["AGENT_MEMORY_ROOT"])
    assert "只要 A 的记忆" in (root / "users" / owner_a / "MEMORY.md").read_text(encoding="utf-8")
    assert not (root / "users" / owner_b / "MEMORY.md").exists() or "只要 A" not in (root / "users" / owner_b / "MEMORY.md").read_text(encoding="utf-8")
    choice = {
        "scene_name": "cangnan", "experiment_id": None, "chosen_id": "pose-1",
        "candidates": [{"id": "pose-1", "objectives": {"dem_soft": 1}}, {"id": "pose-2", "objectives": {"dem_soft": 2}}],
    }
    assert user_a.post("/api/v1/agent/preferences/choices", json=choice).status_code == 200
    assert user_b.get("/api/v1/agent/preferences").json()["choice_count"] == 0


def test_user_cannot_change_global_settings_or_scenes(tmp_path: Path) -> None:
    admin = _app(tmp_path)
    _login(admin, "pytest-admin", os.environ["BOOTSTRAP_ADMIN_PASSWORD"])
    _users(admin)
    user = TestClient(admin.app)
    _login(user, "user_A", PASSWORD)
    assert user.put("/api/v1/agent/settings", json={"action": "update_model", "password": "x", "base_url": "https://example.invalid/v1", "model": "x"}).status_code == 403
    assert user.get("/api/v1/software-update").status_code == 403
    assert user.post("/api/v1/software-update", json={"password": "x"}).status_code == 403
    assert user.delete("/api/v1/scenes/cangnan").status_code == 403
    assert user.get("/api/v1/scenes").status_code == 200
    created = user.post("/api/v1/jobs", json={"plugin_id": "demo.algorithm", "config": {"values": [1], "multiplier": 1}})
    assert created.status_code == 202, created.text
    assert user.post("/api/v1/jobs", json={"plugin_id": "site.build_scene", "config": {"lat": 27.5, "lon": 120.2, "side_length_m": 1800}}).status_code == 403


def test_retention_keeps_other_owners_and_skips_missing_owners(tmp_path: Path) -> None:
    root = tmp_path / "outputs"
    root.mkdir()
    for name, owner, when in (
        ("a1", "owner-a", "2026-01-01T00:00:01+00:00"),
        ("a2", "owner-a", "2026-01-01T00:00:02+00:00"),
        ("a3", "owner-a", "2026-01-01T00:00:03+00:00"),
        ("b1", "owner-b", "2026-01-01T00:00:01+00:00"),
        ("loose", None, "2026-01-01T00:00:04+00:00"),
    ):
        directory = root / name
        directory.mkdir()
        summary = {"result_origin": "auto", "problem_type": "site", "scene_name": "scene", "algorithm": "guided_search", "completed_at": when}
        if owner:
            summary["owner_id"] = owner
        (directory / "run_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    retain_auto_results(root, scene_name="scene", problem_type="site", trigger_id="a3", owner_id="owner-a")
    assert (root / "b1").is_dir() and (root / "loose").is_dir()
    assert (root / "a1").exists() is False
    token = bind_owner("owner-a")
    try:
        marker = auto_marker_fields("scene", "site")
    finally:
        reset_owner(token)
    assert marker["owner_id"] == "owner-a"
    published = root / "a3"
    (published / "run_summary.json").write_text(json.dumps({**marker, "scene_name": "scene"}), encoding="utf-8")
    seen = {}

    def capture(*_args, **_kwargs):
        seen["owner"] = json.loads((published / "run_summary.json").read_text(encoding="utf-8"))["owner_id"]

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("experiments.auto_result_retention.retain_auto_results", capture)
    try:
        retain_published_auto_result(published, "site")
    finally:
        monkeypatch.undo()
    assert seen["owner"] == "owner-a"


def test_legacy_migration_does_not_claim_new_unowned_results(tmp_path: Path) -> None:
    database = tmp_path / "jobs.sqlite3"
    repository = SQLiteJobRepository(database)
    repository.create_job("old-job", "demo.algorithm", "0", {"values": [1]})
    store = AccountStore(f"sqlite:///{database}", repository)
    admin = store.create_user("migrator", PASSWORD, "admin")
    output = tmp_path / "outputs"
    old = output / "old-run"
    old.mkdir(parents=True)
    (old / "run_summary.json").write_text(json.dumps({"n_feasible": 3, "n_pareto": 1}), encoding="utf-8")
    favorites = tmp_path / "favorites.sqlite3"
    from backend.app.infrastructure.favorite_repository import FavoritePointRepository

    favorites_repo = FavoritePointRepository(favorites)
    import sqlite3
    with sqlite3.connect(favorites) as connection:
        connection.execute(
            "INSERT INTO favorite_points (id, scene_id, longitude, latitude, width_m, height_m, bearing_deg, created_at, updated_at) VALUES (?, ?, 1, 2, 3, 4, 5, 't', 't')",
            ("fav-old", "cangnan"),
        )
    from backend.app.application.legacy_ownership import freeze_manifest, migrate_legacy, precheck, save_manifest

    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "MEMORY.md").write_text("旧记忆\n", encoding="utf-8")
    assert precheck(store, output, favorites, memory)["unowned_jobs"] == 1
    manifest_path = tmp_path / "legacy-manifest.json"
    save_manifest(manifest_path, freeze_manifest(store, output, favorites, memory))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["jobs"] == ["old-job"] and manifest["experiments"] == ["old-run"] and manifest["favorites"] == ["fav-old"]
    report = migrate_legacy(
        store, admin.id, output, favorites, memory, manifest, tmp_path / "state.json", tmp_path / "backup",
    )
    assert report["jobs"] == 1 and report["experiments"] == 1 and report["favorites"] == 1
    assert repository.get_job("old-job").owner_id == admin.id
    stamped = json.loads((old / "run_summary.json").read_text(encoding="utf-8"))
    assert stamped["owner_id"] == admin.id and stamped["n_feasible"] == 3 and stamped["owner_origin"] == "legacy"
    before_second = (old / "run_summary.json").read_bytes()
    repository.create_job("new-job", "demo.algorithm", "0", {"values": [9]})
    fresh = output / "new-run"
    fresh.mkdir()
    (fresh / "run_summary.json").write_text(json.dumps({
        "n_feasible": 9, "result_origin": "auto", "problem_type": "site", "scene_name": "scene",
        "completed_at": "2026-02-01T00:00:00+00:00",
    }), encoding="utf-8")
    with sqlite3.connect(favorites) as connection:
        connection.execute(
            "INSERT INTO favorite_points (id, scene_id, longitude, latitude, width_m, height_m, bearing_deg, created_at, updated_at) VALUES (?, ?, 1, 2, 3, 4, 5, 't', 't')",
            ("fav-new", "cangnan"),
        )
    again = migrate_legacy(
        store, admin.id, output, favorites, memory, manifest, tmp_path / "state.json", tmp_path / "backup",
    )
    assert again["conflicts"] == [] and repository.get_job("new-job").owner_id is None
    assert repository.get_job("old-job").owner_id == admin.id
    assert (old / "run_summary.json").read_bytes() == before_second
    fresh_summary = json.loads((fresh / "run_summary.json").read_text(encoding="utf-8"))
    assert "owner_id" not in fresh_summary and fresh_summary["n_feasible"] == 9
    assert favorites_repo.list_for_scene("cangnan", admin.id)[0].id == "fav-old"
    assert [row[0] for row in sqlite3.connect(favorites).execute("SELECT id FROM favorite_points WHERE user_id IS NULL")] == ["fav-new"]
    from experiments.auto_result_retention import retain_auto_results

    retain_auto_results(output, scene_name="scene", problem_type="site", trigger_id="new-run", owner_id=admin.id)
    assert fresh.is_dir()
    app = create_app(f"sqlite:///{database}", "", experiment_root=output, favorite_db_path=favorites)
    client = TestClient(app)
    client.__enter__()
    _login(client, "migrator", PASSWORD)
    listed = {item["id"] for item in client.get("/api/v1/experiments").json()}
    assert "old-run" in listed and "new-run" not in listed
    assert client.get("/api/v1/experiments/new-run").status_code == 404


def test_csrf_and_cookie_flags(tmp_path: Path) -> None:
    client = _app(tmp_path)
    token = skip_auto_login.set(True)
    try:
        response = client.post("/api/v1/auth/login", json={"username": "pytest-admin", "password": os.environ["BOOTSTRAP_ADMIN_PASSWORD"]})
    finally:
        skip_auto_login.reset(token)
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    blocked = skip_auto_login.set(True)
    try:
        assert client.post("/api/v1/auth/logout").status_code == 403
    finally:
        skip_auto_login.reset(blocked)


def test_legacy_cli_dry_run_reads_without_writing_and_refuses_the_live_tree(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    database = tmp_path / "jobs.sqlite3"
    repository = SQLiteJobRepository(database)
    repository.create_job("listed-job", "demo.algorithm", "0", {"values": [1]})
    repository.create_job("later-job", "demo.algorithm", "0", {"values": [2]})
    output = tmp_path / "outputs"
    (output / "listed-run").mkdir(parents=True)
    (output / "listed-run" / "run_summary.json").write_text("{}", encoding="utf-8")
    favorites = tmp_path / "favorites.sqlite3"
    memory = tmp_path / "memory"
    memory.mkdir()
    from backend.app.application.legacy_ownership import main

    manifest = tmp_path / "manifest.json"
    assert main([
        "--freeze", "--database-url", f"sqlite:///{database}", "--output-root", str(output),
        "--favorite-db", str(favorites), "--memory-root", str(memory), "--manifest", str(manifest),
    ]) == 0
    frozen = manifest.read_text(encoding="utf-8")
    repository.create_job("after-freeze", "demo.algorithm", "0", {"values": [3]})
    capsys.readouterr()
    assert main([
        "--dry-run", "--database-url", f"sqlite:///{database}", "--output-root", str(output),
        "--favorite-db", str(favorites), "--memory-root", str(memory), "--manifest", str(manifest),
    ]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["migratable"]["jobs"] == ["later-job", "listed-job"]
    assert report["unrecognized"]["jobs"] == ["after-freeze"]
    assert manifest.read_text(encoding="utf-8") == frozen
    assert repository.get_job("after-freeze").owner_id is None
    live = Path(__file__).resolve().parents[1]
    with pytest.raises(SystemExit):
        main([
            "--dry-run", "--database-url", f"sqlite:///{live / 'outputs' / 'user-state' / 'app.sqlite3'}",
            "--output-root", str(live / "outputs"), "--favorite-db", str(live / "outputs" / "user-state" / "favorites.sqlite3"),
            "--memory-root", str(live / "memory"), "--manifest", str(live / "outputs" / "legacy-manifest.json"),
        ])
