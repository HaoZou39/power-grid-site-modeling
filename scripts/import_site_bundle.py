#!/usr/bin/env python3
"""Import one QA-passed masking_pipeline four-file bundle as an offline site scene.

This deliberately does not run Mask2Former or change the web UI. It prepares the
standard scene arrays with the existing project tools, then publishes the scene
only after preparation completes. Existing scenes are never overwritten.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SOURCE_FIELDS = ("reference_geotiff_path", "landuse_path", "dem_path", "osm_roads_path")
SCENE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,80}$")


def validate_bundle(source: Path) -> tuple[dict, dict, dict[str, Path]]:
    source = source.expanduser().resolve(strict=True)
    metadata_path = source / "metadata.json"
    qa_path = source / "qa_report.json"
    if not metadata_path.is_file() or not qa_path.is_file():
        raise ValueError(f"{source}: metadata.json and qa_report.json are required")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    if qa.get("overall_status") != "passed":
        raise ValueError(f"Refusing bundle with QA status {qa.get('overall_status')!r}")
    if metadata.get("schema_version") != "1.0" or not metadata.get("site_id"):
        raise ValueError("Expected masking_pipeline metadata schema_version=1.0 and site_id")
    if qa.get("site_id") != metadata["site_id"]:
        raise ValueError("metadata and QA refer to different site IDs")
    files = metadata.get("files") or {}
    paths: dict[str, Path] = {}
    for key in SOURCE_FIELDS:
        relative = files.get(key)
        if not isinstance(relative, str) or not relative.startswith("bundle/"):
            raise ValueError(f"metadata.files.{key} must be a bundle-relative path")
        resolved = (source / relative).resolve(strict=True)
        if resolved.parent != source / "bundle" or not resolved.is_file():
            raise ValueError(f"bundle path escapes expected bundle/ directory: {relative}")
        paths[key] = resolved
    actual = {item.name for item in (source / "bundle").iterdir() if item.is_file()}
    expected = {path.name for path in paths.values()}
    if actual != expected or len(expected) != 4:
        raise ValueError(f"bundle must contain exactly four official files: {actual} != {expected}")
    return metadata, qa, paths


def import_site_bundle(
    source: Path,
    scene_id: str,
    title: str,
    scene_root: Path = Path("scenes"),
    base_config: Path = Path("config/default_config.json"),
    dry_run: bool = False,
) -> Path:
    if not SCENE_ID_RE.fullmatch(scene_id):
        raise ValueError(f"Invalid scene ID: {scene_id!r}")
    metadata, qa, paths = validate_bundle(source)
    scene_root = scene_root.expanduser().resolve()
    destination = scene_root / scene_id
    if destination.exists():
        raise FileExistsError(
            f"Scene {destination} already exists; existing scenes are intentionally protected"
        )
    base_config = base_config.expanduser().resolve(strict=True)
    config = json.loads(base_config.read_text(encoding="utf-8"))
    for field in SOURCE_FIELDS:
        config["data"][field] = str(paths[field])

    print(f"Source site_id: {metadata['site_id']}")
    print(f"Destination scene: {scene_id} ({title})")
    for field in SOURCE_FIELDS:
        print(f"  {field}: {paths[field]}")
    if dry_run:
        return destination

    scene_root.mkdir(parents=True, exist_ok=True)
    # A private staging root prevents half-built scenes from appearing in GET /scenes.
    with tempfile.TemporaryDirectory(prefix=".site-import-", dir=scene_root) as temp_name:
        staging_root = Path(temp_name)
        config_path = staging_root / "import_config.json"
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        from experiments.scene_store import prepare_scene, missing_scene_files

        def reporter(progress: float, stage: str, message: str) -> None:
            print(f"[{progress * 100:5.1f}%] {stage}: {message}", flush=True)

        prepared = prepare_scene(
            scene_id,
            reporter=reporter,
            config_path=config_path,
            root=staging_root,
        )
        missing = missing_scene_files(prepared)
        if missing or not (prepared / "landuse_1m.npy").is_file():
            raise RuntimeError(f"Scene preparation incomplete: missing {missing}")
        scene_info = {
            "id": scene_id,
            "title": title,
            "source_site_id": metadata["site_id"],
            "source_bundle": str(source.expanduser().resolve()),
            "source_qa_status": qa["overall_status"],
        }
        (prepared / "scene.json").write_text(
            json.dumps(scene_info, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # Both paths live on the same filesystem, so publication is one rename.
        os.replace(prepared, destination)
    print(f"Published ready scene: {destination}")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True, help="masking_pipeline site directory containing metadata.json and bundle/")
    parser.add_argument("--scene-id", required=True, help="Stable short ID such as yongjia_demo")
    parser.add_argument("--title", required=True, help="Display title shown in scene picker")
    parser.add_argument("--scene-root", type=Path, default=Path("scenes"))
    parser.add_argument("--base-config", type=Path, default=Path("config/default_config.json"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    import_site_bundle(args.bundle, args.scene_id, args.title, args.scene_root, args.base_config, args.dry_run)


if __name__ == "__main__":
    main()
