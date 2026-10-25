"""Coordinate scene builds stay inside the existing job and scene store."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import numpy as np
import pytest

from backend.app.application.registry import build_registry
from backend.app.application.service import JobService
from backend.app.infrastructure.queue import InMemoryTaskQueue
from backend.app.infrastructure.repository import SQLiteJobRepository
from experiments.coordinate_scene import (
    CoordinateSceneError,
    build_scene_from_coordinates,
    inspect_published_bundle,
    radius_km_from_side_length,
    scene_write_lock,
    validate_build_config,
)
from experiments.scene_store import list_scenes
from masking_pipeline.bundle import release_staged_bundle
from masking_pipeline.naming import build_site_id, build_site_paths


def _request(**overrides):
    payload = {
        "lat": 27.501662,
        "lon": 120.194639,
        "side_length_m": 4,
    }
    payload.update(overrides)
    return validate_build_config(payload)


def _write_tif(path: Path, crs: str = "EPSG:3857", bounds=(0, 0, 100, 100)) -> None:
    import rasterio
    from rasterio.transform import from_bounds

    data = np.ones((4, 4), dtype=np.float32)
    transform = from_bounds(*bounds, 4, 4)
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path, "w", driver="GTiff", height=4, width=4, count=1,
        dtype="float32", crs=crs, transform=transform,
    ) as dataset:
        dataset.write(data, 1)


def _write_bundle(site_dir: Path, request, *, landuse: np.ndarray | None = None, satellite_crs: str = "EPSG:3857", qa: str = "passed", omit: str = "") -> None:
    paths = build_site_paths(request.source_site_id, site_dir=str(site_dir))
    Path(paths["bundle_dir"]).mkdir(parents=True, exist_ok=True)
    names = {
        "satellite": Path(paths["satellite"]),
        "landuse": Path(paths["landuse"]),
        "dem": Path(paths["dem"]),
        "osm_roads": Path(paths["osm_roads"]),
    }
    grid = landuse if landuse is not None else np.array([
        [0, 1, 2, 3],
        [4, 5, 0, 1],
        [2, 3, 4, 5],
        [0, 1, 2, 3],
    ], dtype=np.int32)
    from pyproj import Transformer
    cx, cy = Transformer.from_crs(4326, 3857, always_xy=True).transform(request.lon, request.lat)
    half = request.download_radius_km * 1000
    bounds = (cx - half, cy - half, cx + half, cy + half)
    if omit != "satellite":
        _write_tif(names["satellite"], satellite_crs, bounds)
    if omit != "landuse":
        np.savetxt(names["landuse"], grid, fmt="%d", delimiter=",")
    if omit != "dem":
        _write_tif(names["dem"], bounds=bounds)
    if omit != "osm_roads":
        names["osm_roads"].write_text(json.dumps({
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"highway": "residential"},
                "geometry": {"type": "LineString", "coordinates": [[120.19, 27.50], [120.20, 27.51]]},
            }],
        }), encoding="utf-8")
    report = {"overall_status": qa, "errors": [] if qa == "passed" else ["landuse_codes: class 9"]}
    Path(paths["qa_report"]).write_text(json.dumps(report), encoding="utf-8")


def _regional(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    osm = tmp_path / "zhejiang.osm.pbf"
    dem = tmp_path / "wenzhou.tif"
    osm.write_bytes(b"pbf")
    dem.write_bytes(b"dem")
    monkeypatch.setenv("MASKING_OSM_PBF", str(osm))
    monkeypatch.setenv("MASKING_DEM_SOURCE", str(dem))
    monkeypatch.setenv("MASKING_OUTPUT_ROOT", str(tmp_path / "sites"))
    monkeypatch.setenv("SCENE_ROOT", str(tmp_path / "scenes"))


def _ready_scene(directory: Path, marker: str = "keep") -> None:
    directory.mkdir(parents=True)
    np.save(directory / "dem_1m.npy", np.ones((2, 3), dtype=np.float32))
    np.save(directory / "landuse_1m.npy", np.zeros((2, 3), dtype=np.int32))
    np.save(directory / "obstacle_mask_1m.npy", np.zeros((2, 3), dtype=np.uint8))
    np.save(directory / "road_voronoi_1m.npy", np.zeros((2, 3), dtype=np.int64))
    np.save(directory / "road_segments_local.npy", np.zeros((1, 4), dtype=np.float32))
    np.save(directory / "road_segment_kind.npy", np.zeros(len(np.load(directory / "road_segments_local.npy")), np.int8))
    np.save(directory / "demand_points.npy", np.array([[0.5, 0.5]], dtype=np.float32))
    (directory / "data_metadata.json").write_text(
        '{"dem": {"reference_crs": "EPSG:3857", "target_transform": [1, 0, 100, 0, -1, 200], "shape": [2, 3]}}',
        encoding="utf-8",
    )
    (directory / "sentinel.txt").write_text(marker, encoding="utf-8")


def test_side_length_1800_is_a_0_9_km_half_side() -> None:
    assert radius_km_from_side_length(1800) == 0.9
    request = validate_build_config({
        "lat": 27.501662,
        "lon": 120.194639,
        "side_length_m": 1800,
        "site_name": "east",
    })
    assert request.radius_km == 0.9
    assert request.target_height == 1800
    assert request.target_width == 1800
    assert request.site_id == build_site_id(27.501662, 120.194639, 0.9, 18, 1800, 1800, 500, "east") + "_utm_v2"
    assert "east" not in request.site_id
    named = validate_build_config({
        "lat": 27.501662, "lon": 120.194639, "side_length_m": 1800, "site_name": "苍南",
    })
    assert named.site_name == "苍南"
    assert "苍南" not in named.site_id
    with pytest.raises(CoordinateSceneError, match="lat"):
        validate_build_config({"lat": float("nan"), "lon": 120.0, "side_length_m": 1800})
    with pytest.raises(CoordinateSceneError, match="-90"):
        validate_build_config({"lat": 91, "lon": 0, "side_length_m": 1800})
    with pytest.raises(CoordinateSceneError, match="side_length_m"):
        validate_build_config({"lat": 27.5, "lon": 120.1, "side_length_m": 0})
    with pytest.raises(CoordinateSceneError, match="偶数米"):
        validate_build_config({"lat": 27.5, "lon": 120.1, "side_length_m": 1801})
    with pytest.raises(CoordinateSceneError, match="不能单独指定"):
        validate_build_config({"lat": 27.5, "lon": 120.1, "side_length_m": 1800, "target_height": 4})
    with pytest.raises(CoordinateSceneError, match="site_name"):
        validate_build_config({"lat": 27.5, "lon": 120.1, "side_length_m": 1800, "site_name": "cang nan"})


def test_build_plugin_rejects_invalid_coordinates_before_queueing() -> None:
    service = JobService(SQLiteJobRepository(":memory:"), InMemoryTaskQueue(), build_registry())
    with pytest.raises(ValueError, match="-90"):
        service.create_job("site.build_scene", {"lat": 91, "lon": 120.0, "side_length_m": 1800})
    assert service.queue.dequeue(timeout=0) is None


def test_bundle_checks_reject_missing_bad_landuse_bad_crs_and_failed_qa(tmp_path: Path) -> None:
    request = _request()
    site = tmp_path / request.site_id
    _write_bundle(site, request, omit="dem")
    with pytest.raises(CoordinateSceneError, match="dem"):
        inspect_published_bundle(site, request)
    _write_bundle(site, request, landuse=np.full((4, 4), 9))
    with pytest.raises(CoordinateSceneError, match="0 到 5"):
        inspect_published_bundle(site, request)
    _write_bundle(site, request, satellite_crs="EPSG:4326")
    with pytest.raises(CoordinateSceneError, match="EPSG:3857"):
        inspect_published_bundle(site, request)
    _write_bundle(site, request, qa="failed")
    with pytest.raises(CoordinateSceneError, match="校验未通过"):
        inspect_published_bundle(site, request)


def test_incomplete_release_keeps_the_previous_bundle(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    kept = bundle / "kept.tif"
    kept.write_text("previous", encoding="utf-8")
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "only-one.tif").write_text("partial", encoding="utf-8")
    with pytest.raises(RuntimeError, match="incomplete"):
        release_staged_bundle(str(staging), str(bundle), ["a.tif", "b.tif", "c.tif", "d.tif"])
    assert kept.read_text(encoding="utf-8") == "previous"


def _service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pipeline, products):
    _regional(monkeypatch, tmp_path)
    monkeypatch.setattr("masking_pipeline.run.run_pipeline", pipeline)
    monkeypatch.setattr("experiments.problem_context.write_scene_products", products)
    repository = SQLiteJobRepository(":memory:")
    service = JobService(repository, InMemoryTaskQueue(), build_registry())
    return service, repository


def _products(config, output_dir, on_step, *, reference_frame):
    on_step("正在读取用地")
    output_dir.mkdir(parents=True, exist_ok=True)
    np.save(output_dir / "dem_1m.npy", np.ones((reference_frame["height"], reference_frame["width"]), dtype=np.float32))
    np.save(output_dir / "landuse_1m.npy", np.zeros((reference_frame["height"], reference_frame["width"]), dtype=np.int32))
    np.save(output_dir / "obstacle_mask_1m.npy", np.zeros((reference_frame["height"], reference_frame["width"]), dtype=np.uint8))
    np.save(output_dir / "road_voronoi_1m.npy", np.zeros((reference_frame["height"], reference_frame["width"]), dtype=np.int64))
    np.save(output_dir / "road_segments_local.npy", np.ones((1, 4), dtype=np.float32))
    np.save(output_dir / "road_segment_kind.npy", np.zeros(len(np.load(output_dir / "road_segments_local.npy")), np.int8))
    np.save(output_dir / "demand_points.npy", np.array([[0.2, 0.3]], dtype=np.float32))
    assert Path(config.data.landuse_path).is_file()
    assert Path(config.data.reference_geotiff_path).is_file()
    return {}, {
        "dem": {"reference_crs": reference_frame["crs"], "target_transform": reference_frame["transform"], "shape": [reference_frame["height"], reference_frame["width"]]},
        "demand": {"n_demand_points": 64, "demand_seed": 42},
    }


def test_job_reaches_ready_and_publishes_only_that_scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    request = _request()
    calls: list[dict] = []

    def pipeline(**kwargs):
        calls.append(kwargs)
        if kwargs["step"] == "download":
            _write_bundle(Path(kwargs["output_root"]) / request.source_site_id, request)
        return {"site_id": request.site_id}

    service, repository = _service(tmp_path, monkeypatch, pipeline, _products)
    record = service.create_job("site.build_scene", {
        "lat": 27.501662,
        "lon": 120.194639,
        "side_length_m": 4,
    })
    stages: list[str] = []
    original = repository.update_progress

    def record_progress(job_id, progress, stage, message):
        stages.append(stage)
        original(job_id, progress, stage, message)

    repository.update_progress = record_progress  # type: ignore[method-assign]
    final = service.execute_job(record.id)
    assert final.status.value == "succeeded"
    assert final.stage == "ready"
    assert final.result["data"]["scene_id"] == request.site_id
    assert calls[0]["radius_km"] == request.download_radius_km
    assert calls[0]["lat"] == 27.501662
    assert calls[0]["target_height"] == 4
    assert calls[0]["output_root"].endswith("sites")
    assert [step for step in ("download", "osm", "dem", "segment", "downsample", "export") if step in {item["step"] for item in calls}] == [
        "download", "osm", "dem", "segment", "downsample", "export",
    ]
    assert stages[:1] == ["generating_data"]
    assert "validating_data" in stages
    assert "rebuilding_scene" in stages
    assert stages[-1] == "ready"
    listed = list_scenes(tmp_path / "scenes")
    built = next(item for item in listed if item["id"] == request.site_id)
    assert built["ready"] is True
    assert built["source_site_id"] == request.source_site_id
    assert not (tmp_path / "scenes" / ".locks").name in {item["id"] for item in listed}


def test_pipeline_and_reconstruction_failures_keep_the_previous_scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    request = _request()
    scene = tmp_path / "scenes" / request.site_id
    _ready_scene(scene)
    bundle = tmp_path / "sites" / request.source_site_id / "bundle" / "kept.txt"
    bundle.parent.mkdir(parents=True)
    bundle.write_text("previous-bundle", encoding="utf-8")

    def explode(**_kwargs):
        raise RuntimeError("satellite tile failed")

    service, _repository = _service(tmp_path, monkeypatch, explode, _products)
    failed = service.execute_job(service.create_job("site.build_scene", {
        "lat": request.lat, "lon": request.lon, "side_length_m": 4,
    }).id)
    assert failed.status.value == "failed"
    assert failed.stage == "generating_data"
    assert "satellite tile failed" in failed.error["message"]
    assert "Traceback" not in failed.message
    assert bundle.read_text(encoding="utf-8") == "previous-bundle"
    assert (scene / "sentinel.txt").read_text(encoding="utf-8") == "keep"

    def bad_bundle(**kwargs):
        _write_bundle(Path(kwargs["output_root"]) / request.source_site_id, request, qa="failed")
        return {}

    service, _repository = _service(tmp_path, monkeypatch, bad_bundle, _products)
    checked = service.execute_job(service.create_job("site.build_scene", {
        "lat": request.lat, "lon": request.lon, "side_length_m": 4,
    }).id)
    assert checked.status.value == "failed"
    assert checked.stage == "validating_data"
    assert bundle.read_text(encoding="utf-8") == "previous-bundle"
    assert (scene / "sentinel.txt").read_text(encoding="utf-8") == "keep"

    def good_bundle(**kwargs):
        site = Path(kwargs["output_root"]) / request.source_site_id
        published = site / "bundle"
        if published.exists():
            for child in published.iterdir():
                if child.is_file():
                    child.unlink()
        _write_bundle(site, request)
        return {}

    def broken_products(*_args, **_kwargs):
        raise RuntimeError("road reconstruction failed")

    service, _repository = _service(tmp_path, monkeypatch, good_bundle, broken_products)
    rebuilt = service.execute_job(service.create_job("site.build_scene", {
        "lat": request.lat, "lon": request.lon, "side_length_m": 4,
    }).id)
    assert rebuilt.status.value == "failed"
    assert rebuilt.stage == "rebuilding_scene"
    assert (scene / "sentinel.txt").read_text(encoding="utf-8") == "keep"


def test_second_build_cannot_enter_the_same_scene_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    request = _request()
    _regional(monkeypatch, tmp_path)
    root = tmp_path / "scenes"
    root.mkdir()
    entered = threading.Event()
    release = threading.Event()

    def hold():
        with scene_write_lock(request.site_id, root):
            entered.set()
            assert release.wait(2)

    worker = threading.Thread(target=hold)
    worker.start()
    assert entered.wait(2)
    with pytest.raises(CoordinateSceneError, match="同一目录"):
        with scene_write_lock(request.site_id, root):
            pass
    release.set()
    worker.join(2)
    assert not worker.is_alive()

    lock = root / ".locks" / request.site_id
    lock.mkdir(parents=True)
    (lock / "pid").write_text(str(__import__("os").getpid()), encoding="utf-8")
    # Legacy PID files, including PID 1 in another namespace, do not own a kernel lock.
    with scene_write_lock(request.site_id, root):
        pass
