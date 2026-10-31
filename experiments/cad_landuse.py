"""Preview and publish CAD classes through the existing land-use transaction."""
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import tempfile
from uuid import uuid4

import numpy as np

from data_tools.cad_tool import read_cad_drawing, rasterize_cad_landuse
from experiments import landuse_edits
from experiments.import_retention import preview_lock, prune_previews, release_preview_payload
from experiments.scene_cad_files import CAD_DIRECTORY, _require_scene
from experiments.scene_data_import import preview_directory
from experiments.scene_lock import scene_write_lock
from experiments.scene_store import scene_frame_info
from experiments.scene_version import scene_data_version


def _attachment(scene: Path, cad_id: str) -> Path:
    if len(cad_id) != 32 or any(c not in "0123456789abcdef" for c in cad_id):
        raise ValueError("CAD 文件 id 无效")
    directory = scene / CAD_DIRECTORY / cad_id
    if not (directory / "metadata.json").is_file():
        raise FileNotFoundError("CAD 附件不存在")
    return directory


def _drawing(scene: Path, cad_id: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="scene-cad-") as temporary:
        with scene_write_lock(scene.name, scene.parent, blocking=True):
            _require_scene(scene)
            directory = _attachment(scene, cad_id)
            record = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
            suffix = Path(record["source_name"]).suffix.lower()
            source = Path(temporary) / ("source" + suffix)
            shutil.copyfile(directory / source.name, source)
        return read_cad_drawing(source)


def inspect_cad(scene: Path, cad_id: str) -> dict:
    drawing = _drawing(scene, cad_id)
    return {key: value for key, value in drawing.items() if key != "features"}


def _preview_image(layer: np.ndarray, frame: dict, destination: Path) -> None:
    from PIL import Image
    from data_tools.display_grid import project_landuse_classes
    from experiments.constraint_mask import CLASS_COLORS
    classes = np.maximum(layer, 0).astype(np.uint8)
    if frame["crs"] != "EPSG:3857":
        classes = project_landuse_classes(classes, frame)
    image = Image.fromarray(classes, mode="P")
    palette = [0] * (256 * 3)
    alpha = bytearray(256)
    for class_id, rgba in CLASS_COLORS.values():
        palette[class_id * 3:class_id * 3 + 3] = rgba[:3]
        alpha[class_id] = rgba[3]
    image.putpalette(palette)
    image.save(destination, transparency=bytes(alpha))


def preview_cad(scene: Path, cad_id: str, source_crs: str, layer_kinds: dict[str, str]) -> dict:
    with scene_write_lock(scene.name, scene.parent, blocking=True):
        _require_scene(scene)
        version = scene_data_version(scene)
        frame = scene_frame_info(scene)
    drawing = _drawing(scene, cad_id)
    layer, statistics = rasterize_cad_landuse(drawing, source_crs, layer_kinds, frame)
    prune_previews(scene)
    token = uuid4().hex
    with preview_lock(scene, token):
        directory = preview_directory(scene, token)
        directory.mkdir(parents=True)
        try:
            np.save(directory / "cad_landuse.npy", layer)
            _preview_image(layer, frame, directory / "cad.png")
            summary = {"kind": "cad", "token": token, "cad_id": cad_id, "scene_id": scene.name,
                       "data_version": version, "frame": frame, **statistics, "warnings": drawing["warnings"],
                       "saved": False, "created_at": datetime.now(timezone.utc).isoformat()}
            with scene_write_lock(scene.name, scene.parent, blocking=True):
                _require_scene(scene)
                _attachment(scene, cad_id)
                if version != scene_data_version(scene):
                    raise ValueError("场景已变化，请重新生成 CAD 预览")
            (directory / "summary.json").write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
            return summary
        except Exception:
            shutil.rmtree(directory)
            raise


def cad_preview_png(scene: Path, token: str) -> tuple[bytes, dict]:
    with preview_lock(scene, token, blocking=True):
        directory = preview_directory(scene, token)
        summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
        if summary.get("kind") != "cad":
            raise ValueError("不是 CAD 预览")
        return (directory / "cad.png").read_bytes(), summary["frame"]


def confirm_cad(scene: Path, token: str) -> dict:
    with preview_lock(scene, token):
        directory = preview_directory(scene, token)
        path = directory / "summary.json"
        summary = json.loads(path.read_text(encoding="utf-8"))
        with scene_write_lock(scene.name, scene.parent):
            _require_scene(scene)
            if summary.get("kind") != "cad" or summary.get("scene_id") != scene.name or summary.get("saved"):
                raise ValueError("CAD 预览无效或已应用，请重新生成预览")
            _attachment(scene, summary["cad_id"])
            if summary["data_version"] != scene_data_version(scene):
                raise ValueError("场景已变化，请重新生成 CAD 预览")
            metadata = {key: summary[key] for key in ("cad_id", "source_crs", "layer_kinds", "cell_counts", "feature_counts")}
            metadata["imported_at"] = datetime.now(timezone.utc).isoformat()
            revision = landuse_edits.publish_cad_landuse(scene.name, np.load(directory / "cad_landuse.npy"), metadata, scene.parent)
            summary.update(saved=True, scene_revision=revision)
            path.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
        release_preview_payload(directory)
        return summary


def clear_cad(scene: Path) -> dict:
    with scene_write_lock(scene.name, scene.parent):
        _require_scene(scene)
        if not (scene / landuse_edits.CAD_LAYER_FILE).is_file():
            return {"changed": False}
        revision = landuse_edits.publish_cad_landuse(scene.name, None, None, scene.parent)
        return {"changed": True, "scene_revision": revision}


def retain_cad_landuse(previous: Path, staged: Path) -> None:
    path = previous / landuse_edits.CAD_METADATA_FILE
    if not path.is_file():
        return
    metadata = json.loads(path.read_text(encoding="utf-8"))
    drawing = _drawing(staged, metadata["cad_id"])
    layer, statistics = rasterize_cad_landuse(drawing, metadata["source_crs"], metadata["layer_kinds"], scene_frame_info(staged))
    landuse_edits.publish_cad_landuse(staged.name, layer, {**metadata, **statistics}, staged.parent)
