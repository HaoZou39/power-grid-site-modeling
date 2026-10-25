"""Persistent scene provenance shared by readers, results and cache keys."""
import hashlib
import json
import os
import tempfile
from pathlib import Path
from uuid import uuid4

from data_tools.metric_grid import frame_id


def scene_data_version(directory: Path, metadata: dict | None = None) -> dict:
    metadata = _metadata(directory) if metadata is None else metadata
    dem = metadata.get("dem", {})
    shape = dem.get("shape")
    identity = None
    if shape and dem.get("target_transform") and dem.get("reference_crs"):
        identity = frame_id({"crs": dem["reference_crs"], "transform": dem["target_transform"],
                             "height": shape[0], "width": shape[1]})
    revision = metadata.get("scene_revision")
    if not revision:
        # Older scenes have no saved revision. Their file identity is stable across page reloads.
        files = []
        for name in ("dem_1m.npy", "landuse_1m.npy", "obstacle_mask_1m.npy", "road_segments_local.npy",
                     "road_segment_kind.npy", "road_voronoi_1m.npy", "protected_farmland_mask_1m.npy"):
            path = directory / name
            if path.is_file():
                stat = path.stat()
                files.append((name, stat.st_size, stat.st_mtime_ns))
        revision = hashlib.sha256(json.dumps(files).encode()).hexdigest()
    return {"frame_id": identity, "scene_revision": revision}


def write_scene_revision(directory: Path, metadata: dict | None = None) -> dict:
    metadata = dict(_metadata(directory) if metadata is None else metadata)
    metadata["scene_revision"] = uuid4().hex
    fd, name = tempfile.mkstemp(prefix=".metadata-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(metadata, stream, ensure_ascii=False, indent=2, allow_nan=False)
        os.replace(name, directory / "data_metadata.json")
    finally:
        Path(name).unlink(missing_ok=True)
    return metadata


def _metadata(directory: Path) -> dict:
    path = directory / "data_metadata.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
