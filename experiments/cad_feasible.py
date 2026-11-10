"""Preview CAD boundaries for the existing editable feasible-zone form."""
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from uuid import uuid4

import numpy as np
from affine import Affine
from rasterio.features import rasterize

from data_tools.cad_tool import cad_feasible_zones
from experiments.cad_landuse import _attachment, _drawing, _preview_image
from experiments.import_retention import preview_lock, prune_previews, release_preview_payload
from experiments.scene_cad_files import _require_scene, assert_preview_current
from experiments.scene_data_import import preview_directory
from experiments.scene_lock import scene_write_lock
from experiments.scene_store import scene_frame_info
from experiments.scene_version import scene_data_version


def preview_cad_feasible(scene: Path, cad_id: str, source_crs: str) -> dict:
    with scene_write_lock(scene.name, scene.parent, blocking=True):
        _require_scene(scene)
        frame, version = scene_frame_info(scene), scene_data_version(scene)
    drawing = _drawing(scene, cad_id)
    result = cad_feasible_zones(drawing, source_crs, frame)
    shapes = [{"type": "Polygon", "coordinates": [zone["points"] + [zone["points"][0]]]}
              for zone in result["feasible_zones"]]
    layer = rasterize(shapes, out_shape=(frame["height"], frame["width"]), transform=Affine.identity(),
                      fill=0, default_value=4, dtype=np.uint8)
    prune_previews(scene)
    token = uuid4().hex
    with preview_lock(scene, token):
        directory = preview_directory(scene, token)
        directory.mkdir(parents=True)
        try:
            _preview_image(layer, frame, directory / "cad.png", colors={"feasible": (4, (45, 184, 138, 160))})
            summary = {"kind": "cad_feasible", "token": token, "scene_id": scene.name, "cad_id": cad_id,
                       "data_version": version, "frame": frame, **result, "warnings": drawing["warnings"],
                       "sha256": drawing["source_sha256"],
                       "saved": False, "created_at": datetime.now(timezone.utc).isoformat()}
            with scene_write_lock(scene.name, scene.parent, blocking=True):
                _require_scene(scene)
                if version != scene_data_version(scene):
                    raise ValueError("场景已变化，请重新生成 CAD 预览")
                assert_preview_current(scene, summary)
            (directory / "summary.json").write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
            return summary
        except Exception:
            shutil.rmtree(directory)
            raise


def confirm_cad_feasible(scene: Path, token: str) -> dict:
    with preview_lock(scene, token):
        directory = preview_directory(scene, token)
        path = directory / "summary.json"
        summary = json.loads(path.read_text(encoding="utf-8"))
        with scene_write_lock(scene.name, scene.parent):
            _require_scene(scene)
            if summary.get("kind") != "cad_feasible" or summary.get("scene_id") != scene.name or summary.get("saved"):
                raise ValueError("CAD 可行域预览无效或已应用，请重新生成预览")
            _attachment(scene, summary["cad_id"])
            assert_preview_current(scene, summary)
            if summary["data_version"] != scene_data_version(scene):
                raise ValueError("场景已变化，请重新生成 CAD 预览")
            summary["saved"] = True
            path.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
        release_preview_payload(directory)
        return {"feasible_zones": summary["feasible_zones"]}
