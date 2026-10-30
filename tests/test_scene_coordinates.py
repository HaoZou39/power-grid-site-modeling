import os
from pathlib import Path

import pytest

from data_tools.scene_coordinates import local_to_lonlat, lonlat_to_local, projection
from modeling.routing.types import RoutingFrame

NANXI = {
    "crs": "EPSG:32651",
    "transform": [1.0, 0.0, 280694.551436199, 0.0, -1.0, 3130907.64382529],
    "width": 9000,
    "height": 9000,
}
ROOT = Path(__file__).resolve().parents[1]


def test_cgcs2000_degrees_match_wgs84_and_round_trip():
    lon, lat = 120.79755385600004, 28.26049599000003
    east_4490, north_4490 = projection(4490, 32651).transform(lon, lat)
    east_4326, north_4326 = projection(4326, 32651).transform(lon, lat)
    assert east_4490 == east_4326
    assert north_4490 == north_4326
    local = lonlat_to_local(NANXI, lon, lat)
    back_lon, back_lat = local_to_lonlat(NANXI, *local)
    assert back_lon == pytest.approx(lon, abs=1e-9)
    assert back_lat == pytest.approx(lat, abs=1e-9)
    again = lonlat_to_local(NANXI, back_lon, back_lat)
    assert again[0] == pytest.approx(local[0], abs=1e-6)
    assert again[1] == pytest.approx(local[1], abs=1e-6)


def test_routing_frame_uses_the_same_round_trip():
    frame = RoutingFrame("EPSG:32651", tuple(NANXI["transform"]), 9000, 9000)
    local = frame.to_local(120.810599, 28.246101)
    lon, lat = frame.to_wgs84(local)
    assert lon == pytest.approx(120.810599, abs=1e-9)
    assert lat == pytest.approx(28.246101, abs=1e-9)


def test_rotated_frame_is_rejected():
    frame = {**NANXI, "transform": [1.0, 0.1, 0.0, 0.1, -1.0, 0.0]}
    with pytest.raises(ValueError, match="unrotated"):
        lonlat_to_local(frame, 120.8, 28.2)


def _python_files():
    skipped = {".git", ".venv", ".worktrees", "node_modules", "outputs", "__pycache__", ".tmp-problem-snapshot", "site-packages"}
    for directory, names, files in os.walk(ROOT):
        names[:] = [name for name in names if name not in skipped]
        for name in files:
            if name.endswith(".py"):
                yield Path(directory) / name


def test_scene_projection_is_not_reimplemented():
    offenders = []
    for path in _python_files():
        if "tests" in path.parts or path.name == "scene_coordinates.py":
            continue
        if "Transformer.from_crs" in path.read_text(encoding="utf-8"):
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []

    frontend_offenders = []
    frontend = ROOT / "frontend" / "src"
    for path in frontend.rglob("*"):
        if path.suffix not in {".ts", ".tsx"} or path.name == "site_frame.ts":
            continue
        if "proj4" in path.read_text(encoding="utf-8"):
            frontend_offenders.append(path.relative_to(ROOT).as_posix())
    assert frontend_offenders == []
