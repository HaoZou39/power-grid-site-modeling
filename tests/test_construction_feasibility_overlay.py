from io import BytesIO

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from backend.app.main import create_app
from experiments.constraint_mask import compose_constraint_masks, polygons_from_form, policy_from_form
from experiments.scene_store import construction_feasibility_png
from modeling.context import compose_building_hard_mask


ALLOWED = np.array([45, 184, 138, 38], dtype=np.uint8)
BLOCKED = np.array([235, 98, 109, 89], dtype=np.uint8)


def _form(**updates):
    return {
        "mountain_policy": "allowed",
        "field_policy": "allowed",
        "field_cost": 0.5,
        "exclusion_zones": [],
        "feasible_zones": [],
        **updates,
    }


def _pixels(tmp_path, landuse, form):
    scene = tmp_path / "cangnan"
    scene.mkdir(exist_ok=True)
    np.save(scene / "landuse_1m.npy", landuse)
    np.save(scene / "road_segments_local.npy", np.zeros((0, 4), dtype=np.float64))
    return np.asarray(Image.open(BytesIO(construction_feasibility_png("cangnan", form, tmp_path))).convert("RGBA"))


def test_overlay_colours_match_composed_hard_mask(tmp_path) -> None:
    landuse = np.array([
        [0, 1, 2, 3, 4, 5],
        [0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0],
    ], dtype=np.int16)
    form = _form(
        field_policy="costly",
        mountain_policy="blocked",
        exclusion_zones=[{"points": [[1, 1], [3, 1], [1, 3]]}],
        feasible_zones=[{"points": [[0, 0], [5, 0], [5, 5], [0, 5]]}],
    )
    pixels = _pixels(tmp_path, landuse, form)
    hard, _ = compose_constraint_masks(
        landuse,
        polygons_from_form(form),
        policy_from_form(form),
        polygons_from_form(form, "feasible_zones"),
    )
    building = compose_building_hard_mask(hard, landuse, np.zeros(landuse.shape, dtype=bool), form.get("road_setback_m", 5.0))
    assert np.all(pixels[building == 0] == ALLOWED)
    assert np.all(pixels[building > 0] == BLOCKED)


def test_overlay_respects_landuse_policies(tmp_path) -> None:
    landuse = np.array([[1, 2, 3, 4, 5]], dtype=np.int16)
    allowed = _pixels(tmp_path, landuse, _form(road_setback_m=0))
    assert np.all(allowed[0, 0] == ALLOWED)
    assert np.all(allowed[0, 1] == BLOCKED)
    assert np.all(allowed[0, 2] == BLOCKED)
    assert np.all(allowed[0, 3] == ALLOWED)
    assert np.all(allowed[0, 4] == BLOCKED)

    blocked = _pixels(
        tmp_path,
        landuse,
        _form(field_policy="blocked", mountain_policy="blocked", road_setback_m=0),
    )
    assert np.all(blocked[0] == BLOCKED)
    costly = _pixels(tmp_path, landuse, _form(field_policy="costly", road_setback_m=0))
    assert np.all(costly[0, 0] == ALLOWED)


def test_overlay_api_returns_png_without_writing_scene(monkeypatch, tmp_path) -> None:
    scene = tmp_path / "cangnan"
    scene.mkdir()
    np.save(scene / "landuse_1m.npy", np.array([[0, 2]], dtype=np.int16))
    np.save(scene / "road_segments_local.npy", np.zeros((0, 4), dtype=np.float64))
    before = sorted(path.name for path in scene.iterdir())
    monkeypatch.setenv("SCENE_ROOT", str(tmp_path))

    response = TestClient(create_app("sqlite://:memory:", "")).post(
        "/api/v1/scenes/cangnan/construction-feasibility-overlay",
        json=_form(),
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "no-store"
    assert Image.open(BytesIO(response.content)).size == (2, 1)
    assert sorted(path.name for path in scene.iterdir()) == before


def test_overlay_api_reports_missing_scene_and_invalid_rules(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SCENE_ROOT", str(tmp_path))
    client = TestClient(create_app("sqlite://:memory:", ""))
    missing = client.post(
        "/api/v1/scenes/missing/construction-feasibility-overlay",
        json=_form(),
    )
    assert missing.status_code == 404

    scene = tmp_path / "cangnan"
    scene.mkdir()
    np.save(scene / "landuse_1m.npy", np.zeros((2, 2), dtype=np.int16))
    np.save(scene / "road_segments_local.npy", np.zeros((0, 4), dtype=np.float64))
    invalid = client.post(
        "/api/v1/scenes/cangnan/construction-feasibility-overlay",
        json=_form(exclusion_zones=[{"points": [[0, 0], [3, 0], [0, 1]]}]),
    )
    assert invalid.status_code == 422
