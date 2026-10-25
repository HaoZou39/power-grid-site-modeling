"""Imported roads share the existing grid and publish as one guarded bundle."""

import json
import os
from pathlib import Path
import zipfile

import numpy as np
from pyproj import CRS
import pytest
import shapefile

from experiments import import_road_shapefile as importer
from experiments import scene_store
from experiments.scene_store import ROAD_PRODUCT_FILES, ROAD_REBUILD_MARKER, SCENE_ARRAYS


@pytest.fixture
def road_trial(tmp_path):
    scene = tmp_path / "scenes/demo"
    scene.mkdir(parents=True)
    arrays = {
        "dem_1m.npy": np.ones((3, 4), np.float32),
        "landuse_1m.npy": np.zeros((3, 4), np.uint8),
        "obstacle_mask_1m.npy": np.zeros((3, 4), np.uint8),
        "road_segments_local.npy": np.array([[0, 1, 4, 1]], np.float32),
        "road_segment_kind.npy": np.zeros(1, np.int8),
        "road_voronoi_1m.npy": np.zeros((3, 4), np.int64),
        "demand_points.npy": np.array([[0.5, 0.5]], np.float32),
        "protected_farmland_mask_1m.npy": np.zeros((3, 4), np.uint8),
    }
    for name, array in arrays.items():
        np.save(scene / name, array)
    metadata = {"dem": {"reference_crs": "EPSG:3857", "target_transform": [1, 0, 100, 0, -1, 200], "shape": [3, 4]},
                "road": {"n_segments": 1}, "kept": "non-road metadata"}
    for name, data in (("data_metadata.json", metadata), ("road_segments_local.json", {"old": True}),
                       ("road_voronoi_1m.json", {"old": True})):
        (scene / name).write_text(json.dumps(data), encoding="utf-8")
    source = tmp_path / "roads.shp"
    with shapefile.Writer(str(source), shapeType=shapefile.POLYLINE, encoding="utf-8") as writer:
        writer.field("class", "C", 80)
        for road_class, line in (
            ("四级道路", [[100, 199], [102, 199], [104, 199]]),
            ("四级道路", [[102, 199], [102, 197]]),
            ("在建道路", [[100, 198], [104, 198]]),
        ):
            writer.line([line])
            writer.record(road_class)
    source.with_suffix(".prj").write_text(CRS.from_epsg(3857).to_wkt(), encoding="utf-8")
    source.with_suffix(".cpg").write_text("UTF-8", encoding="ascii")
    return scene, source


def _preview(tmp_path, scene, source):
    output = tmp_path / "preview"
    config = importer.RoadImportConfig("demo", source, output, 0, ("在建道路",), "gaode")
    summary = importer.preview_road_source(config, root=scene.parent)
    return output, summary


def test_preview_filters_classes_and_uses_prepared_grid_without_raw_geotiff(tmp_path, road_trial):
    scene, source = road_trial
    before = {name: (scene / name).read_bytes() for name in SCENE_ARRAYS}
    output, summary = _preview(tmp_path, scene, source)
    road = summary["road"]
    assert road["provider"] == "gaode"
    assert road["reference_grid_source"] == "prepared_scene"
    assert road["reference_geotiff_path"] is None
    assert road["import"]["source_crs"] == "EPSG:3857"
    assert road["import"]["included_parts"] == 2
    assert road["import"]["excluded_feature_counts"] == {"在建道路": 1}
    assert road["n_segments"] == 3
    assert road["raw_component_count"] == road["simplified_component_count"] == 1
    assert np.load(output / "road_voronoi_1m.npy").shape == (3, 4)
    assert {name: (scene / name).read_bytes() for name in SCENE_ARRAYS} == before


def test_apply_backs_up_roads_and_preserves_other_scene_data(tmp_path, road_trial):
    scene, source = road_trial
    before = {name: (scene / name).read_bytes() for name in SCENE_ARRAYS}
    farmland = (scene / "protected_farmland_mask_1m.npy").read_bytes()
    output, _ = _preview(tmp_path, scene, source)
    backup = importer.apply_road_preview(scene, output, tmp_path / "backups")
    assert (backup / "road_segments_local.npy").read_bytes() == before["road_segments_local.npy"]
    assert np.load(scene / "road_segments_local.npy").shape == (3, 4)
    for name in SCENE_ARRAYS:
        if not name.startswith("road_"):
            assert (scene / name).read_bytes() == before[name]
    assert (scene / "protected_farmland_mask_1m.npy").read_bytes() == farmland
    saved = json.loads((scene / "data_metadata.json").read_text())
    assert saved["road"]["provider"] == "gaode"
    assert saved["kept"] == "non-road metadata"
    assert not (scene / ROAD_REBUILD_MARKER).exists()


@pytest.mark.parametrize("fail", [False, True])
def test_publishing_and_rollback_never_write_through_historical_hardlinks(tmp_path, road_trial, monkeypatch, fail):
    scene, source = road_trial
    experiment = tmp_path / "historical"
    experiment.mkdir()
    for name in ROAD_PRODUCT_FILES:
        os.link(scene / name, experiment / name)
    before = {name: (experiment / name).read_bytes() for name in ROAD_PRODUCT_FILES}
    output, _ = _preview(tmp_path, scene, source)
    if fail:
        publish = scene_store._publish_road_file
        calls = 0

        def interrupted(src, dest):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OSError("injected publication failure")
            publish(src, dest)

        monkeypatch.setattr(scene_store, "_publish_road_file", interrupted)
        with pytest.raises(OSError, match="injected"):
            importer.apply_road_preview(scene, output, tmp_path / "backups")
    else:
        importer.apply_road_preview(scene, output, tmp_path / "backups")
    assert {name: (experiment / name).read_bytes() for name in ROAD_PRODUCT_FILES} == before
    for name in ROAD_PRODUCT_FILES:
        assert (experiment / name).stat().st_nlink == 1


def test_failed_road_publication_restores_the_entire_previous_bundle(tmp_path, road_trial, monkeypatch):
    scene, source = road_trial
    before = {name: (scene / name).read_bytes() for name in ROAD_PRODUCT_FILES}
    output, _ = _preview(tmp_path, scene, source)
    publish = scene_store._publish_road_file
    calls = 0

    def fail_second(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("publication interrupted")
        publish(source, destination)

    monkeypatch.setattr(scene_store, "_publish_road_file", fail_second)
    with pytest.raises(OSError, match="publication interrupted"):
        importer.apply_road_preview(scene, output, tmp_path / "backups")
    assert {name: (scene / name).read_bytes() for name in ROAD_PRODUCT_FILES} == before
    assert not (scene / ROAD_REBUILD_MARKER).exists()


@pytest.mark.parametrize("rollback_failure_call", [3, 5])
def test_failed_import_rollback_keeps_scene_blocked_and_reports_backup(
    tmp_path, road_trial, monkeypatch, rollback_failure_call,
):
    scene, source = road_trial
    before = {name: (scene / name).read_bytes() for name in ROAD_PRODUCT_FILES}
    output, _ = _preview(tmp_path, scene, source)
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
        importer.apply_road_preview(scene, output, tmp_path / "backups")

    marker = scene / ROAD_REBUILD_MARKER
    assert marker.is_file()
    with pytest.raises(RuntimeError):
        scene_store.ensure_scene_readable(scene)
    recovery = json.loads(marker.read_text(encoding="utf-8"))
    backup = Path(recovery["backup"])
    assert backup.is_absolute()
    assert str(backup) in str(error.value)
    assert "publication interrupted" in str(error.value)
    assert "rollback interrupted" in str(error.value)
    assert {name: (backup / name).read_bytes() for name in ROAD_PRODUCT_FILES} == before


def test_successful_rollback_restores_originally_absent_sidecar(tmp_path, road_trial, monkeypatch):
    scene, source = road_trial
    missing_sidecar = scene / "road_segments_local.json"
    missing_sidecar.unlink()
    before = {name: (scene / name).read_bytes() for name in ROAD_PRODUCT_FILES if (scene / name).is_file()}
    output, _ = _preview(tmp_path, scene, source)
    publish = scene_store._publish_road_file
    calls = 0

    def fail_after_new_sidecar(source, destination):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("publication interrupted after creating sidecar")
        publish(source, destination)

    monkeypatch.setattr(scene_store, "_publish_road_file", fail_after_new_sidecar)
    with pytest.raises(OSError, match="after creating sidecar"):
        importer.apply_road_preview(scene, output, tmp_path / "backups")
    assert not missing_sidecar.exists()
    assert {name: (scene / name).read_bytes() for name in before} == before
    assert not (scene / ROAD_REBUILD_MARKER).exists()
    scene_store.ensure_scene_readable(scene)


def test_incomplete_candidate_does_not_start_publication(tmp_path, road_trial):
    scene, source = road_trial
    before = {name: (scene / name).read_bytes() for name in ROAD_PRODUCT_FILES}
    output, _ = _preview(tmp_path, scene, source)
    (output / "road_voronoi_1m.json").unlink()
    with pytest.raises(FileNotFoundError, match="road_voronoi_1m.json"):
        importer.apply_road_preview(scene, output, tmp_path / "backups")
    assert {name: (scene / name).read_bytes() for name in ROAD_PRODUCT_FILES} == before
    assert not (scene / ROAD_REBUILD_MARKER).exists()
    assert not (tmp_path / "backups").exists()


@pytest.mark.parametrize("changed", ["dem_1m.npy", "road_segments_local.npy"])
def test_stale_road_preview_cannot_overwrite_changed_scene(tmp_path, road_trial, changed):
    scene, source = road_trial
    output, _ = _preview(tmp_path, scene, source)
    array = np.load(scene / changed).copy()
    np.save(scene / changed, array + 1)
    with pytest.raises(ValueError, match="变化"):
        importer.apply_road_preview(scene, output, tmp_path / "backups")
    assert not (scene / ROAD_REBUILD_MARKER).exists()


def test_zip_shapefile_uses_the_same_import_path(tmp_path, road_trial):
    scene, source = road_trial
    archive = tmp_path / "roads.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        for suffix in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
            zipped.write(source.with_suffix(suffix), "roads" + suffix)
    _, summary = _preview(tmp_path, scene, archive)
    assert summary["road"]["n_segments"] == 3
    assert summary["road"]["source_name"] == "roads.zip"


@pytest.mark.parametrize("as_zip", [False, True])
@pytest.mark.parametrize("exclusions", [("在建道路",), ()])
def test_missing_class_field_only_rejected_when_exclusions_requested(
    tmp_path, road_trial, as_zip, exclusions,
):
    scene, source = road_trial
    before = {name: (scene / name).read_bytes() for name in SCENE_ARRAYS}
    with shapefile.Reader(str(source), encoding="utf-8") as reader:
        records = [(item.shape, item.record[0]) for item in reader.iterShapeRecords()]
    with shapefile.Writer(str(source), shapeType=shapefile.POLYLINE, encoding="utf-8") as writer:
        writer.field("fclass", "C", 80)
        for geometry, road_class in records:
            writer.shape(geometry)
            writer.record(road_class)
    if as_zip:
        archive = tmp_path / "roads.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            for suffix in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
                zipped.write(source.with_suffix(suffix), "roads" + suffix)
        source = archive
    output = tmp_path / "preview"
    config = importer.RoadImportConfig("demo", source, output, 0, exclusions, "gaode")
    if exclusions:
        with pytest.raises(ValueError, match="class"):
            importer.preview_road_source(config, root=scene.parent)
        assert not (output / "roads_wgs84.geojson").exists()
        assert not (output / "import_summary.json").exists()
    else:
        summary = importer.preview_road_source(config, root=scene.parent)
        assert summary["road"]["import"]["included_parts"] == 3
    assert {name: (scene / name).read_bytes() for name in SCENE_ARRAYS} == before


def test_grid_change_during_preview_is_not_recorded_as_valid(tmp_path, road_trial, monkeypatch):
    scene, source = road_trial
    build = importer.build_road_product

    def move_frame_during_build(*args, **kwargs):
        result = build(*args, **kwargs)
        path = scene / "data_metadata.json"
        metadata = json.loads(path.read_text())
        metadata["dem"]["target_transform"][2] += 1
        path.write_text(json.dumps(metadata), encoding="utf-8")
        return result

    monkeypatch.setattr(importer, "build_road_product", move_frame_during_build)
    with pytest.raises(ValueError, match="构建过程中"):
        _preview(tmp_path, scene, source)
    assert not (tmp_path / "preview/import_summary.json").exists()


def test_nonfinite_buffer_is_rejected(tmp_path, road_trial):
    scene, source = road_trial
    config = importer.RoadImportConfig("demo", source, tmp_path / "preview", float("nan"), (), "gaode")
    with pytest.raises(ValueError, match="clip_buffer_m"):
        importer.preview_road_source(config, root=scene.parent)


def test_two_reference_sources_are_rejected(tmp_path, road_trial):
    from data_tools.traffic_tool import build_road_product

    source = tmp_path / "roads.geojson"
    source.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    with pytest.raises(ValueError, match="either"):
        build_road_product(source, None, None, Path("unused.tif"), (3, 4), 0,
                           reference_frame={"height": 3, "width": 4})
