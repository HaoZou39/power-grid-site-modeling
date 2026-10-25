import json
import os

from experiments.audit_scene_links import audit_scene_links, file_sha256


def test_audit_preserves_evidence_before_detaching(tmp_path):
    scenes, outputs = tmp_path / "scenes", tmp_path / "outputs"
    scene, experiment = scenes / "demo", outputs / "experiment"
    scene.mkdir(parents=True)
    experiment.mkdir(parents=True)
    source = experiment / "metadata.json"
    source.write_text('{"observed":"not proven original"}')
    os.link(source, scene / source.name)
    before = file_sha256(source)
    backup = outputs / "audit"
    report = audit_scene_links(scenes, outputs, backup, detach=True)
    assert report["files"][0]["detached"]
    assert file_sha256(backup / "outputs/experiment/metadata.json") == before
    assert file_sha256(backup / "scenes/demo/metadata.json") == before
    assert json.loads((backup / "audit.json").read_text()) == report
    (scene / source.name).write_text("later scene update")
    assert file_sha256(source) == before
    assert source.stat().st_nlink == 1


def test_audit_without_detach_is_read_only_for_source(tmp_path):
    scene = tmp_path / "scenes/demo"
    scene.mkdir(parents=True)
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    path = outputs / "source"
    path.write_bytes(b"evidence")
    os.link(path, scene / "source")
    report = audit_scene_links(scene.parent, outputs, tmp_path / "backup")
    assert not report["files"][0]["detached"]
    assert path.stat().st_nlink == 2
