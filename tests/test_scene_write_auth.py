"""Public-scene writes stay admin-only, including CAD landuse deletion."""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from backend.app.api.auth_middleware import _scene_mutation
from backend.app.main import create_app
from experiments.landuse_edits import CAD_LAYER_FILE
from tests.auth_flags import skip_auto_login

PASSWORD = "user-pass-9f3c"

# Every registered scene route. A new one fails this test until it is classified.
SCENE_ROUTE_CLASS = {
    ("GET", "/api/v1/scenes"): "read",
    ("DELETE", "/api/v1/scenes/{scene_id}"): "admin",
    ("PATCH", "/api/v1/scenes/{scene_id}"): "admin",
    ("GET", "/api/v1/scenes/{scene_id}/landuse-overlay/{layer}"): "read",
    ("GET", "/api/v1/scenes/{scene_id}/obstacle-overlay"): "read",
    ("GET", "/api/v1/scenes/{scene_id}/map-layers"): "read",
    ("GET", "/api/v1/scenes/{scene_id}/cad-files"): "read",
    ("POST", "/api/v1/scenes/{scene_id}/cad-files"): "admin",
    ("POST", "/api/v1/scenes/{scene_id}/cad-files/{cad_id}/replace"): "admin",
    ("DELETE", "/api/v1/scenes/{scene_id}/cad-files/{cad_id}"): "admin",
    ("POST", "/api/v1/scenes/{scene_id}/cad-files/{cad_id}/inspect"): "admin",
    ("POST", "/api/v1/scenes/{scene_id}/cad-files/{cad_id}/feasible-preview"): "admin",
    ("POST", "/api/v1/scenes/{scene_id}/cad-files/feasible-confirm"): "admin",
    ("POST", "/api/v1/scenes/{scene_id}/cad-files/{cad_id}/preview"): "admin",
    ("GET", "/api/v1/scenes/{scene_id}/cad-files/preview/{token}.png"): "admin",
    ("POST", "/api/v1/scenes/{scene_id}/cad-files/confirm"): "admin",
    ("DELETE", "/api/v1/scenes/{scene_id}/cad-landuse"): "admin",
    ("POST", "/api/v1/scenes/{scene_id}/data-import/preview"): "admin",
    ("GET", "/api/v1/scenes/{scene_id}/data-import/preview/{token}/farmland.png"): "admin",
    ("GET", "/api/v1/scenes/{scene_id}/data-import/preview/{token}/roads"): "admin",
    ("POST", "/api/v1/scenes/{scene_id}/data-import/confirm"): "admin",
    ("POST", "/api/v1/scenes/{scene_id}/data-import/restore-osm"): "admin",
    ("DELETE", "/api/v1/scenes/{scene_id}/protected-farmland"): "admin",
    ("GET", "/api/v1/scenes/{scene_id}/protected-farmland-overlay"): "read",
    ("GET", "/api/v1/scenes/{scene_id}/dem-overlay"): "read",
    ("GET", "/api/v1/scenes/{scene_id}/road-segments"): "read",
    ("GET", "/api/v1/scenes/{scene_id}/admin-boundaries"): "read",
    ("POST", "/api/v1/scenes/{scene_id}/landuse-patch"): "admin",
    ("GET", "/api/v1/scenes/{scene_id}/landuse-edits"): "read",
    ("POST", "/api/v1/scenes/{scene_id}/landuse-edits/batch"): "admin",
    ("DELETE", "/api/v1/scenes/{scene_id}/landuse-edits"): "admin",
    ("POST", "/api/v1/scenes/{scene_id}/landuse-edits"): "admin",
    ("PUT", "/api/v1/scenes/{scene_id}/landuse-edits/{edit_id}"): "admin",
    ("DELETE", "/api/v1/scenes/{scene_id}/landuse-edits/{edit_id}"): "admin",
    ("POST", "/api/v1/scenes/{scene_id}/site-report"): "compute",
    ("POST", "/api/v1/scenes/{scene_id}/pose-objectives"): "compute",
    ("POST", "/api/v1/scenes/{scene_id}/construction-feasibility-overlay"): "compute",
    ("GET", "/api/v1/scenes/{scene_id}/favorites"): "owner",
    ("POST", "/api/v1/scenes/{scene_id}/favorites"): "owner",
    ("PUT", "/api/v1/scenes/{scene_id}/favorites/{favorite_id}"): "owner",
    ("DELETE", "/api/v1/scenes/{scene_id}/favorites/{favorite_id}"): "owner",
}


def _scene(root: Path) -> Path:
    scene = root / "demo"
    scene.mkdir(parents=True)
    arrays = {
        "dem_1m.npy": np.ones((3, 4), np.float32),
        "landuse_1m.npy": np.zeros((3, 4), np.uint8),
        "obstacle_mask_1m.npy": np.zeros((3, 4), np.uint8),
        "road_segments_local.npy": np.array([[0, 1, 4, 1]], np.float32),
        "road_segment_kind.npy": np.zeros(1, np.int8),
        "road_voronoi_1m.npy": np.zeros((3, 4), np.int64),
        "demand_points.npy": np.array([[0.5, 0.5]], np.float32),
        CAD_LAYER_FILE: np.array([[0, 2, 0, 0], [0, 0, 0, 1], [0, 0, 0, 0]], np.uint8),
    }
    for name, array in arrays.items():
        np.save(scene / name, array)
    (scene / "data_metadata.json").write_text(json.dumps({
        "scene_revision": "rev-before-delete",
        "dem": {"reference_crs": "EPSG:3857", "target_transform": [1, 0, 100, 0, -1, 200], "shape": [3, 4]},
    }), encoding="utf-8")
    (scene / "scene.json").write_text("{}\n", encoding="utf-8")
    return scene


def _files(scene: Path) -> dict[str, bytes]:
    return {path.relative_to(scene).as_posix(): path.read_bytes() for path in scene.rglob("*") if path.is_file()}


def _login(client: TestClient, username: str, password: str) -> None:
    client.cookies.clear()
    token = skip_auto_login.set(True)
    try:
        response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    finally:
        skip_auto_login.reset(token)
    assert response.status_code == 200, response.text
    client.csrf_token = response.json()["csrf_token"]


def test_user_cannot_delete_cad_landuse_and_admin_still_can(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scene = _scene(tmp_path / "scenes")
    monkeypatch.setenv("SCENE_ROOT", str(scene.parent))
    before = _files(scene)
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'app.sqlite3'}", "", favorite_db_path=tmp_path / "favorites.sqlite3"))
    client.__enter__()
    assert client.post("/api/v1/admin/users", json={"username": "cad-user", "password": PASSWORD, "role": "user"}).status_code == 201
    _login(client, "cad-user", PASSWORD)
    denied = client.delete("/api/v1/scenes/demo/cad-landuse")
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "admin_required"
    assert _files(scene) == before
    assert json.loads((scene / "data_metadata.json").read_text(encoding="utf-8"))["scene_revision"] == "rev-before-delete"
    _login(client, os.environ["BOOTSTRAP_ADMIN_USERNAME"], os.environ["BOOTSTRAP_ADMIN_PASSWORD"])
    cleared = client.delete("/api/v1/scenes/demo/cad-landuse")
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["changed"] is True
    assert not (scene / CAD_LAYER_FILE).exists()


def _concrete(path: str) -> str:
    return (
        path.replace("{scene_id}", "demo")
        .replace("{cad_id}", "cad-1")
        .replace("{token}", "token-1")
        .replace("{layer}", "field")
        .replace("{edit_id}", "edit-1")
        .replace("{favorite_id}", "fav-1")
    )


def test_every_scene_route_has_an_authorization_class() -> None:
    app = create_app("sqlite://:memory:", "")
    found = {
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/v1/scenes")
        for method in route.methods
        if method in {"GET", "POST", "PUT", "PATCH", "DELETE"}
    }
    assert found == set(SCENE_ROUTE_CLASS)
    for method, path in found:
        kind = SCENE_ROUTE_CLASS[(method, path)]
        mutation = _scene_mutation(method, _concrete(path))
        if kind == "admin":
            assert mutation, path
        else:
            assert kind in {"read", "owner", "compute"}
            assert not mutation, path
        if method != "GET":
            assert kind in {"admin", "owner", "compute"}
