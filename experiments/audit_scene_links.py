"""Back up shared scene files before optionally isolating them from experiments."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from experiments.coordinate_scene import scene_write_lock
from experiments.scene_store import detach_shared_file


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def audit_scene_links(scene_root: Path, output_root: Path, backup: Path, *, detach: bool = False) -> dict:
    scene_root, output_root, backup = (p.resolve() for p in (scene_root, output_root, backup))
    shared = [p for scene in scene_root.iterdir() if scene.is_dir() and not scene.name.startswith(".")
              for p in scene.iterdir() if p.is_file() and p.stat().st_nlink > 1]
    identities = {(p.stat().st_dev, p.stat().st_ino) for p in shared}
    counterparts: dict[tuple[int, int], list[Path]] = {key: [] for key in identities}
    for path in output_root.rglob("*"):
        if path.is_file() and not path.is_relative_to(backup):
            stat = path.stat()
            key = (stat.st_dev, stat.st_ino)
            if key in counterparts:
                counterparts[key].append(path)
    backup.mkdir(parents=True, exist_ok=False)
    report = {"scene_root": str(scene_root), "output_root": str(output_root),
              "restoration": "unverified; snapshots preserve observed bytes, not original experiment provenance",
              "files": []}
    for path in shared:
        with scene_write_lock(path.parent.name, scene_root):
            stat = path.stat()
            expected = file_sha256(path)
            copies = [path, *counterparts[(stat.st_dev, stat.st_ino)]]
            for original in copies:
                root, label = (scene_root, "scenes") if original == path else (output_root, "outputs")
                target = backup / label / original.relative_to(root)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(original, target)
                if file_sha256(target) != expected or target.stat().st_ino == stat.st_ino:
                    raise RuntimeError(f"independent backup verification failed: {original}")
            entry = {"scene_file": str(path.relative_to(scene_root)), "sha256": expected,
                     "inode": stat.st_ino, "links": stat.st_nlink,
                     "experiments": [str(p.relative_to(output_root)) for p in copies[1:]], "detached": False}
            report["files"].append(entry)
            (backup / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            if detach:
                detach_shared_file(path)
                if file_sha256(path) != expected or any(file_sha256(p) != expected for p in copies[1:]):
                    raise RuntimeError(f"isolation changed file contents: {path}")
                entry["detached"] = True
                (backup / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (backup / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenes", type=Path, required=True)
    parser.add_argument("--outputs", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--detach", action="store_true")
    args = parser.parse_args()
    report = audit_scene_links(args.scenes, args.outputs, args.backup, detach=args.detach)
    print(json.dumps({"shared_files": len(report["files"]), "detached": sum(p["detached"] for p in report["files"]),
                      "report": str(args.backup / "audit.json")}))


if __name__ == "__main__":
    main()
