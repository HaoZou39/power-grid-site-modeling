"""Scene files are loaded as-is. These tests do not rebuild rasters or start a search."""

import json
import threading
from pathlib import Path

import numpy as np
import pytest
import torch

from experiments.scene_store import (
    ROAD_REBUILD_MARKER,
    SCENE_ARRAYS,
    SCENE_METADATA,
    adopt_scene,
    list_scenes,
    load_scene,
    rebuild_scene_roads,
    prepare_scene,
)


def _write_products(directory: Path) -> None:
    directory.mkdir(parents=True)
    np.save(directory / "dem_1m.npy", np.ones((2, 3), dtype=np.float32))
    np.save(directory / "landuse_1m.npy", np.zeros((2, 3), dtype=np.int32))
    np.save(directory / "obstacle_mask_1m.npy", np.zeros((2, 3), dtype=np.uint8))
    np.save(directory / "road_voronoi_1m.npy", np.zeros((2, 3), dtype=np.int64))
    np.save(directory / "road_segments_local.npy", np.zeros((1, 4), dtype=np.float32))
    np.save(directory / "road_segment_kind.npy", np.zeros(len(np.load(directory / "road_segments_local.npy")), np.int8))
    np.save(directory / "demand_points.npy", np.array([[0.5, 0.5]], dtype=np.float32))
    (directory / SCENE_METADATA).write_text(
        '{"dem": {"reference_crs": "EPSG:3857", "target_transform": [1, 0, 100, 0, -1, 200], "shape": [2, 3]}, "demand": {"n_demand_points": 1}}',
        encoding="utf-8",
    )


def test_load_scene_reads_saved_arrays_without_raw_inputs(tmp_path: Path) -> None:
    _write_products(tmp_path / "cangnan")
    context, metadata = load_scene("cangnan", torch.device("cpu"), tmp_path)
    assert context.dem.shape == (2, 3)
    assert context.demand_points.shape == (1, 2)
    assert context.dem_tensor.device.type == "cpu"
    assert metadata["scene_id"] == "cangnan"


def test_missing_scene_names_the_files_optimization_must_not_rebuild(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="dem_1m.npy"):
        load_scene("cangnan", torch.device("cpu"), tmp_path)


def test_adopt_scene_copies_existing_products(tmp_path: Path) -> None:
    source = tmp_path / "built"
    _write_products(source)
    scene = adopt_scene(source, "cangnan", tmp_path / "scenes")
    listed = list_scenes(tmp_path / "scenes")
    assert scene.name == "cangnan"
    cangnan = next(item for item in listed if item["id"] == "cangnan")
    yongjia = next(item for item in listed if item["id"] == "yongjia")
    assert cangnan["title"] == "苍南" and cangnan["ready"] is True
    assert cangnan["frame"]["width"] == 3
    assert yongjia["title"] == "永嘉"
    assert (scene / "dem_1m.npy").stat().st_ino != (source / "dem_1m.npy").stat().st_ino
    np.save(scene / "dem_1m.npy", np.zeros((2, 3)))
    np.testing.assert_array_equal(np.load(source / "dem_1m.npy"), np.ones((2, 3)))
    assert set(SCENE_ARRAYS).issubset({path.name for path in scene.iterdir()})


def _write_road_rebuild_scene(directory: Path) -> dict[str, np.ndarray]:
    directory.mkdir(parents=True)
    kept = {
        "dem_1m.npy": np.ones((3, 4), dtype=np.float32),
        "landuse_1m.npy": np.full((3, 4), 4, dtype=np.uint8),
        "obstacle_mask_1m.npy": np.zeros((3, 4), dtype=np.uint8),
        "demand_points.npy": np.array([[0.5, 0.5]], dtype=np.float32),
    }
    for name, array in kept.items():
        np.save(directory / name, array)
    np.save(directory / "road_segments_local.npy", np.array([[0, 0, 1, 0]], dtype=np.float32))
    np.save(directory / "road_segment_kind.npy", np.zeros(len(np.load(directory / "road_segments_local.npy")), np.int8))
    np.save(directory / "road_voronoi_1m.npy", np.zeros((3, 4), dtype=np.int64))
    (directory / "road_segments_local.json").write_text('{"n_segments": 1}', encoding="utf-8")
    (directory / "road_voronoi_1m.json").write_text('{"n_segments": 1}', encoding="utf-8")
    (directory / SCENE_METADATA).write_text('{"road": {"n_segments": 1}, "kept": true}', encoding="utf-8")
    (directory / "scene.json").write_text(json.dumps({"id": directory.name, "source_files": {"osm_roads_path": "dummy.geojson"}}))
    metadata = json.loads((directory / SCENE_METADATA).read_text())
    metadata["dem"] = {"reference_crs": "EPSG:3857", "target_transform": [1, 0, 100, 0, -1, 200], "shape": [3, 4]}
    (directory / SCENE_METADATA).write_text(json.dumps(metadata))
    return kept


def _fake_road_builder(*args, **kwargs):
    segments_path = Path(args[1])
    voronoi_path = Path(args[2])
    shape = args[4]
    segments = np.array([[0, 0, 3, 0], [3, 0, 3, 2]], dtype=np.float32)
    voronoi = np.zeros(shape, dtype=np.int64)
    voronoi[:, 2:] = 1
    metadata = {"n_segments": 2, "shape": list(shape), "road_product_id": "test-product"}
    np.save(segments_path, segments)
    np.save(segments_path.with_name("road_segment_kind.npy"), np.zeros(len(segments), np.int8))
    np.save(voronoi_path, voronoi)
    segments_path.with_suffix(".json").write_text('{"n_segments": 2}', encoding="utf-8")
    voronoi_path.with_suffix(".json").write_text('{"n_segments": 2}', encoding="utf-8")
    return segments, voronoi, np.zeros(len(segments), np.int8), metadata


def test_road_only_rebuild_backs_up_and_preserves_non_road_products(tmp_path: Path, monkeypatch) -> None:
    scene = tmp_path / "scenes" / "demo"
    kept = _write_road_rebuild_scene(scene)
    road_file_id = (scene / "road_segments_local.npy").stat().st_ino
    monkeypatch.setattr("data_tools.traffic_tool.build_road_product", _fake_road_builder)

    rebuilt, backup, metadata = rebuild_scene_roads(
        "demo",
        root=tmp_path / "scenes",
        backup_root=tmp_path / "backups",
    )

    assert rebuilt == scene
    assert metadata["road_product_id"]
    assert np.load(scene / "road_segments_local.npy").shape == (2, 4)
    assert (scene / "road_segments_local.npy").stat().st_ino == road_file_id
    assert int(np.load(scene / "road_voronoi_1m.npy").max()) == 1
    assert (backup / "road_segments_local.npy").is_file()
    assert (backup / "road_voronoi_1m.npy").is_file()
    assert not (scene / ROAD_REBUILD_MARKER).exists()
    assert '"kept": true' in (scene / SCENE_METADATA).read_text(encoding="utf-8")
    for name, expected in kept.items():
        assert np.array_equal(np.load(scene / name), expected)


def test_road_only_rebuild_restores_previous_bundle_when_publish_fails(tmp_path: Path, monkeypatch) -> None:
    scene = tmp_path / "scenes" / "demo"
    _write_road_rebuild_scene(scene)
    old_segments = np.load(scene / "road_segments_local.npy").copy()
    old_voronoi = np.load(scene / "road_voronoi_1m.npy").copy()
    monkeypatch.setattr("data_tools.traffic_tool.build_road_product", _fake_road_builder)
    from experiments import scene_store

    real_publish = scene_store._publish_road_file
    calls = 0

    def fail_during_publish(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("publish failed")
        return real_publish(source, destination)

    monkeypatch.setattr(scene_store, "_publish_road_file", fail_during_publish)
    with pytest.raises(OSError, match="publish failed"):
        rebuild_scene_roads("demo", root=tmp_path / "scenes", backup_root=tmp_path / "backups")
    assert np.array_equal(np.load(scene / "road_segments_local.npy"), old_segments)
    assert np.array_equal(np.load(scene / "road_voronoi_1m.npy"), old_voronoi)
    assert not (scene / ROAD_REBUILD_MARKER).exists()


@pytest.mark.parametrize("rollback_failure_call", [3, 5])
def test_failed_rebuild_rollback_keeps_scene_blocked_and_reports_backup(
    tmp_path: Path, monkeypatch, rollback_failure_call,
) -> None:
    from experiments import scene_store

    scene = tmp_path / "scenes/demo"
    _write_road_rebuild_scene(scene)
    names = scene_store.ROAD_PRODUCT_FILES
    before = {name: (scene / name).read_bytes() for name in names}
    monkeypatch.setattr("data_tools.traffic_tool.build_road_product", _fake_road_builder)
    publish = scene_store._publish_road_file
    calls = 0

    def fail_publication_and_rollback(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("publication interrupted")
        if calls == rollback_failure_call:
            raise OSError("rollback interrupted")
        publish(source, destination)

    monkeypatch.setattr(scene_store, "_publish_road_file", fail_publication_and_rollback)
    with pytest.raises((OSError, RuntimeError)) as error:
        rebuild_scene_roads("demo", root=scene.parent, backup_root=tmp_path / "backups")

    marker = scene / ROAD_REBUILD_MARKER
    assert marker.is_file()
    with pytest.raises(RuntimeError):
        load_scene("demo", torch.device("cpu"), scene.parent)
    recovery = json.loads(marker.read_text(encoding="utf-8"))
    backup = Path(recovery["backup"])
    assert backup.is_absolute()
    assert str(backup) in str(error.value)
    assert "publication interrupted" in str(error.value)
    assert "rollback interrupted" in str(error.value)
    assert {name: (backup / name).read_bytes() for name in names} == before


def test_scene_load_refuses_a_road_bundle_during_publication(tmp_path: Path) -> None:
    scene = tmp_path / "scenes" / "demo"
    _write_road_rebuild_scene(scene)
    (scene / ROAD_REBUILD_MARKER).write_text("publishing", encoding="utf-8")
    with pytest.raises(RuntimeError, match="正在安全切换"):
        load_scene("demo", torch.device("cpu"), tmp_path / "scenes")


def test_snapshot_reader_waits_for_complete_publication(tmp_path, monkeypatch):
    from experiments import scene_store

    scene = tmp_path / "scenes/demo"
    _write_road_rebuild_scene(scene)
    monkeypatch.setattr("data_tools.traffic_tool.build_road_product", _fake_road_builder)
    partial, resume, read_done = threading.Event(), threading.Event(), threading.Event()
    publish = scene_store._publish_road_file
    observed, failures = [], []

    def pause_after_first_file(source, destination):
        publish(source, destination)
        if not partial.is_set():
            partial.set()
            assert resume.wait(3)

    def write():
        try:
            rebuild_scene_roads("demo", root=scene.parent, backup_root=tmp_path / "backups")
        except Exception as exc:
            failures.append(exc)

    def read():
        try:
            observed.append(load_scene("demo", torch.device("cpu"), scene.parent))
        finally:
            read_done.set()

    monkeypatch.setattr(scene_store, "_publish_road_file", pause_after_first_file)
    writer = threading.Thread(target=write)
    writer.start()
    try:
        assert partial.wait(3)
        reader = threading.Thread(target=read)
        reader.start()
        assert not read_done.wait(.05)
    finally:
        resume.set()
        writer.join(3)
    reader.join(3)
    assert not failures
    context, metadata = observed[0]
    assert len(context.road_segments) == metadata["road"]["n_segments"] == 2


def test_registered_yongjia_sources_do_not_reuse_cangnan() -> None:
    from experiments.scene_store import scene_source_paths

    assert scene_source_paths("yongjia") == {
        "dem_path": Path("data/sites/yongjia/dem.tif"),
        "landuse_path": Path("data/sites/yongjia/landuse.csv"),
        "osm_roads_path": Path("data/sites/yongjia/osm_roads.geojson"),
        "reference_geotiff_path": Path("data/sites/yongjia/satellite_ref.tif"),
    }


def test_prepare_yongjia_uses_only_registered_yongjia_inputs(tmp_path: Path, monkeypatch) -> None:
    from experiments import scene_store

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    sources = {
        "title": "永嘉",
        "dem_path": inputs / "dem.tif",
        "landuse_path": inputs / "landuse.csv",
        "osm_roads_path": inputs / "osm_roads.geojson",
        "reference_geotiff_path": inputs / "satellite_ref.tif",
    }
    for path in sources.values():
        if isinstance(path, Path):
            path.touch()
    monkeypatch.setitem(scene_store.SCENE_SOURCES, "yongjia", sources)
    seen = {}

    def fake_write(config, output_dir, on_step):
        seen.update({
            "dem": config.data.dem_path,
            "landuse": config.data.landuse_path,
            "roads": config.data.osm_roads_path,
            "reference": config.data.reference_geotiff_path,
        })
        _write_products(output_dir)
        np.save(output_dir / "landuse_1m.npy", np.zeros((2, 3), dtype=np.int32))
        return {}, {
            "dem": {
                "reference_crs": "EPSG:3857",
                "target_transform": [1, 0, 100, 0, -1, 200],
                "shape": [2, 3],
            }
        }

    monkeypatch.setattr("experiments.problem_context.write_scene_products", fake_write)
    prepared = prepare_scene("yongjia", lambda *_args: None, root=tmp_path / "scenes")

    assert prepared == tmp_path / "scenes" / "yongjia"
    assert seen == {
        "dem": sources["dem_path"],
        "landuse": sources["landuse_path"],
        "roads": sources["osm_roads_path"],
        "reference": sources["reference_geotiff_path"],
    }
    assert (prepared / "scene.json").is_file()


def test_prepare_failure_does_not_publish_ready_scene(tmp_path: Path, monkeypatch) -> None:
    def fail(*_args, **_kwargs):
        raise ValueError("no valid road LineStrings found")

    monkeypatch.setattr("experiments.problem_context.write_scene_products", fail)
    with pytest.raises(ValueError, match="no valid road"):
        prepare_scene("yongjia", lambda *_args: None, root=tmp_path / "scenes")

    listed = list_scenes(tmp_path / "scenes")
    yongjia = next(item for item in listed if item["id"] == "yongjia")
    assert yongjia["ready"] is False
    assert not (tmp_path / "scenes" / "yongjia").exists()


def test_prepare_missing_registered_input_fails_before_creating_scene(tmp_path: Path, monkeypatch) -> None:
    from experiments import scene_store

    source = dict(scene_store.SCENE_SOURCES["yongjia"])
    source["dem_path"] = tmp_path / "missing-dem.tif"
    monkeypatch.setitem(scene_store.SCENE_SOURCES, "yongjia", source)

    with pytest.raises(FileNotFoundError, match="missing-dem.tif"):
        prepare_scene("yongjia", lambda *_args: None, root=tmp_path / "scenes")
    assert not (tmp_path / "scenes" / "yongjia").exists()


def test_scene_sources_survive_repository_move_and_cwd_change(tmp_path: Path, monkeypatch) -> None:
    from experiments import scene_store

    config_path = Path(__file__).resolve().parents[1] / "config/default_config.json"
    repository = tmp_path / "original"
    bundle = repository / "outputs/masking-sites/demo/bundle"
    bundle.mkdir(parents=True)
    sources = {
        "dem_path": bundle / "dem.tif",
        "landuse_path": bundle / "landuse.csv",
        "osm_roads_path": bundle / "roads.geojson",
        "reference_geotiff_path": bundle / "satellite.tif",
    }
    for source in sources.values():
        source.touch()
    monkeypatch.setattr(scene_store, "REPOSITORY_ROOT", repository, raising=False)
    seen = []

    def build_products(config, output_dir, _on_step):
        seen.append({key: getattr(config.data, key) for key in sources})
        _write_products(output_dir)
        return {}, json.loads((output_dir / SCENE_METADATA).read_text(encoding="utf-8"))

    monkeypatch.setattr("experiments.problem_context.write_scene_products", build_products)
    prepared = scene_store.prepare_scene_from_sources(
        "demo", sources, lambda *_: None, title="demo", source_site_id="demo",
        root=repository / "scenes", config_path=config_path,
    )
    relative = {key: value.relative_to(repository).as_posix() for key, value in sources.items()}
    record = json.loads((prepared / "scene.json").read_text(encoding="utf-8"))
    assert record["source_files"] == relative

    moved = tmp_path / "moved"
    repository.rename(moved)
    monkeypatch.setattr(scene_store, "REPOSITORY_ROOT", moved)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)
    rebuilt = prepare_scene(
        "demo", lambda *_: None, root=moved / "scenes", config_path=config_path, rebuild=True,
    )
    assert rebuilt == moved / "scenes/demo"
    assert seen[-1] == {key: moved / value for key, value in relative.items()}
    assert json.loads((rebuilt / "scene.json").read_text(encoding="utf-8"))["source_files"] == relative


def test_published_external_absolute_sources_are_not_relocated(tmp_path: Path, monkeypatch) -> None:
    from experiments import scene_store

    repository = tmp_path / "repository"
    scene = repository / "scenes/demo"
    scene.mkdir(parents=True)
    sources = {
        key: str(tmp_path / "external" / name)
        for key, name in {
            "dem_path": "dem.tif", "landuse_path": "landuse.csv",
            "osm_roads_path": "roads.geojson", "reference_geotiff_path": "satellite.tif",
        }.items()
    }
    (scene / "scene.json").write_text(json.dumps({"source_files": sources}), encoding="utf-8")
    monkeypatch.setattr(scene_store, "REPOSITORY_ROOT", repository, raising=False)
    monkeypatch.chdir(tmp_path)
    loaded, _, _ = scene_store._published_scene_sources(scene, "demo")
    assert loaded == {key: Path(value) for key, value in sources.items()}


def test_missing_relative_raw_sources_preserve_existing_scene(tmp_path: Path, monkeypatch) -> None:
    from experiments import scene_store

    repository = tmp_path / "repository"
    scene = repository / "scenes/demo"
    _write_products(scene)
    sources = {
        key: f"outputs/missing/{name}"
        for key, name in {
            "dem_path": "dem.tif", "landuse_path": "landuse.csv",
            "osm_roads_path": "roads.geojson", "reference_geotiff_path": "satellite.tif",
        }.items()
    }
    record = json.dumps({"source_files": sources})
    (scene / "scene.json").write_text(record, encoding="utf-8")
    before = (scene / "dem_1m.npy").read_bytes()
    monkeypatch.setattr(scene_store, "REPOSITORY_ROOT", repository, raising=False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError) as error:
        prepare_scene("demo", lambda *_: None, root=repository / "scenes", rebuild=True)
    assert str(repository / sources["dem_path"]) in str(error.value)
    assert (scene / "dem_1m.npy").read_bytes() == before
    assert (scene / "scene.json").read_text(encoding="utf-8") == record
