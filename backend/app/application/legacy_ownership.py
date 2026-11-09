"""Claim only a frozen pre-upgrade manifest. Later unowned rows stay unowned."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from backend.app.infrastructure.account_store import AccountStore
from experiments.scene_lock import SceneBusyError, file_lock

LEGACY_FILES = ("MEMORY.md", "PREFERENCE_CHOICES.jsonl", "PREFERENCE_DEFAULTS.json")
_REPO = Path(__file__).resolve().parents[3]


def precheck(store: AccountStore, output_root: Path, favorite_db: Path, memory_root: Path) -> dict:
    jobs = store._query("SELECT COUNT(*) FROM jobs WHERE owner_id IS NULL")[0][0]
    experiments = _unowned_experiments(output_root)
    favorites = _unowned_favorite_ids(favorite_db)
    return {
        "unowned_jobs": int(jobs),
        "unowned_experiments": len(experiments),
        "unowned_favorites": len(favorites),
        "legacy_memory_file": (memory_root / "MEMORY.md").is_file(),
    }


def freeze_manifest(store: AccountStore, output_root: Path, favorite_db: Path, memory_root: Path) -> dict:
    """Snapshot the unowned rows that exist while writers are stopped. Does not assign them."""
    _require_writers_stopped(output_root)
    body = {
        "version": 1,
        "batch_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "jobs": sorted(row[0] for row in store._query("SELECT id FROM jobs WHERE owner_id IS NULL")),
        "experiments": sorted(path.name for path in _unowned_experiments(output_root)),
        "favorites": sorted(_unowned_favorite_ids(favorite_db)),
        "memory_files": [name for name in LEGACY_FILES if (memory_root / name).is_file()],
    }
    body["sha256"] = _digest(body)
    return body


def load_manifest(path: Path) -> dict:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    _verify_manifest(manifest)
    return manifest


def save_manifest(path: Path, manifest: dict) -> None:
    _verify_manifest(manifest)
    if path.exists():
        raise FileExistsError(f"历史清单已存在，不能扩大或覆盖：{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def dry_run(
    store: AccountStore,
    output_root: Path,
    favorite_db: Path,
    memory_root: Path,
    manifest: dict | None,
) -> dict:
    """Read current unowned rows. A missing manifest reports them as unrecognized and writes nothing."""
    current = _current_unowned(store, output_root, favorite_db, memory_root)
    if manifest is None:
        return {"needs_manifest": True, "migratable": _empty_sets(), "unrecognized": current, "already_owned": _empty_sets()}
    _verify_manifest(manifest)
    migratable = {
        "jobs": sorted(set(manifest["jobs"]) & set(current["jobs"])),
        "experiments": sorted(set(manifest["experiments"]) & set(current["experiments"])),
        "favorites": sorted(set(manifest["favorites"]) & set(current["favorites"])),
        "memory_files": [name for name in manifest["memory_files"] if (memory_root / name).is_file()],
    }
    unrecognized = {
        "jobs": sorted(set(current["jobs"]) - set(manifest["jobs"])),
        "experiments": sorted(set(current["experiments"]) - set(manifest["experiments"])),
        "favorites": sorted(set(current["favorites"]) - set(manifest["favorites"])),
        "memory_files": [name for name in current["memory_files"] if name not in manifest["memory_files"]],
    }
    return {"needs_manifest": False, "batch_id": manifest["batch_id"], "migratable": migratable, "unrecognized": unrecognized}


def migrate_legacy(
    store: AccountStore,
    admin_id: str,
    output_root: Path,
    favorite_db: Path,
    memory_root: Path,
    manifest: dict,
    state_path: Path,
    backup_dir: Path,
) -> dict:
    """Apply one frozen batch. Does not scan for new unowned rows and does not overwrite an owner."""
    _require_admin(store, admin_id)
    _verify_manifest(manifest)
    _require_writers_stopped(output_root)
    state = _load_state(state_path)
    if state.get("batch_id") not in {None, manifest["batch_id"]}:
        raise ValueError("状态文件属于另一迁移批次")
    state.setdefault("batch_id", manifest["batch_id"])
    state.setdefault("manifest_sha256", manifest["sha256"])
    if state["manifest_sha256"] != manifest["sha256"]:
        raise ValueError("状态文件和历史清单不是同一份")
    if not state.get("backup_ready"):
        _write_backup(backup_dir, store, manifest, output_root, favorite_db, memory_root)
        state["backup_dir"] = str(backup_dir)
        state["backup_ready"] = True
        _save_state(state_path, state)
    report = _apply_manifest(
        store, admin_id, output_root, favorite_db, memory_root, manifest, state, state_path,
    )
    _save_state(state_path, state)
    report["batch_id"] = manifest["batch_id"]
    return report


def migration_status(manifest: dict, state_path: Path) -> dict:
    _verify_manifest(manifest)
    state = _load_state(state_path)
    completed = state.get("completed", _empty_sets())
    conflicts = state.get("conflicts", [])
    missing = state.get("missing", [])
    remaining = {
        kind: sorted(set(manifest[kind]) - set(completed.get(kind, [])))
        for kind in ("jobs", "experiments", "favorites", "memory_files")
    }
    return {
        "batch_id": manifest.get("batch_id"),
        "backup_ready": bool(state.get("backup_ready")),
        "completed": {kind: len(completed.get(kind, [])) for kind in remaining},
        "remaining": {kind: len(values) for kind, values in remaining.items()},
        "conflicts": conflicts,
        "missing": missing,
    }


def restore_backup(
    store: AccountStore,
    output_root: Path,
    favorite_db: Path,
    memory_root: Path,
    backup_dir: Path,
    admin_id: str,
) -> None:
    """Put back the pre-images saved before apply. Writers must be stopped."""
    _require_writers_stopped(output_root)
    jobs = json.loads((backup_dir / "jobs.json").read_text(encoding="utf-8"))
    for row in jobs:
        store._execute("UPDATE jobs SET owner_id = ? WHERE id = ?", (row["owner_id"], row["id"]))
    experiments = backup_dir / "experiments"
    if experiments.is_dir():
        for summary in experiments.glob("*/run_summary.json"):
            target = output_root / summary.parent.name / "run_summary.json"
            if target.is_file():
                shutil.copy2(summary, target)
    favorite_copy = backup_dir / "favorites.sqlite3"
    if favorite_copy.is_file():
        _restore_sqlite(favorite_copy, favorite_db)
    for name in LEGACY_FILES:
        source = backup_dir / "memory" / name
        target = memory_root / "users" / admin_id / name
        if source.is_file() and target.is_file() and target.read_bytes() == source.read_bytes():
            target.unlink()


def _apply_manifest(store, admin_id, output_root, favorite_db, memory_root, manifest, state, state_path: Path) -> dict:
    completed = state.setdefault("completed", _empty_sets())
    conflicts = state.setdefault("conflicts", [])
    missing = state.setdefault("missing", [])
    jobs = store.assign_listed_jobs(admin_id, [job_id for job_id in manifest["jobs"] if job_id not in completed["jobs"]])
    completed["jobs"].extend(jobs["claimed"])
    completed["jobs"].extend(job_id for job_id in manifest["jobs"] if job_id not in completed["jobs"] and job_id not in jobs["missing"] and job_id not in jobs["conflicts"])
    conflicts.extend({"kind": "job", "id": job_id} for job_id in jobs["conflicts"] if {"kind": "job", "id": job_id} not in conflicts)
    missing.extend({"kind": "job", "id": job_id} for job_id in jobs["missing"] if {"kind": "job", "id": job_id} not in missing)
    _save_state(state_path, state)
    experiments = _claim_experiments(output_root, admin_id, manifest["experiments"], completed["experiments"], conflicts, missing)
    completed["experiments"].extend(experiments)
    _save_state(state_path, state)
    favorites = _claim_favorites(favorite_db, admin_id, manifest["favorites"], completed["favorites"], conflicts)
    completed["favorites"].extend(favorites)
    _save_state(state_path, state)
    memory = _copy_listed_memory(memory_root, admin_id, manifest["memory_files"], completed["memory_files"])
    completed["memory_files"].extend(memory)
    _save_state(state_path, state)
    return {
        "jobs": len(completed["jobs"]),
        "experiments": len(completed["experiments"]),
        "favorites": len(completed["favorites"]),
        "memory_copied": memory,
        "conflicts": conflicts,
        "missing": missing,
    }


def _claim_experiments(output_root, admin_id, names, done, conflicts, missing) -> list[str]:
    claimed = []
    for name in names:
        if name in done:
            continue
        path = output_root / name / "run_summary.json"
        if not path.is_file() or path.parent.is_symlink():
            if {"kind": "experiment", "id": name} not in missing:
                missing.append({"kind": "experiment", "id": name})
            continue
        summary = json.loads(path.read_text(encoding="utf-8"))
        owner = summary.get("owner_id")
        if owner == admin_id:
            claimed.append(name)
            continue
        if owner:
            if {"kind": "experiment", "id": name} not in conflicts:
                conflicts.append({"kind": "experiment", "id": name})
            continue
        summary["owner_id"] = admin_id
        summary["owner_origin"] = "legacy"
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        claimed.append(name)
    return claimed


def _claim_favorites(favorite_db: Path, admin_id: str, favorite_ids: list[str], done: list[str], conflicts: list) -> list[str]:
    if not favorite_db.is_file() or not favorite_ids:
        return []
    claimed = []
    with sqlite3.connect(favorite_db) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(favorite_points)")}
        if "user_id" not in columns:
            connection.execute("ALTER TABLE favorite_points ADD COLUMN user_id TEXT")
        for favorite_id in favorite_ids:
            if favorite_id in done:
                continue
            row = connection.execute("SELECT user_id FROM favorite_points WHERE id = ?", (favorite_id,)).fetchone()
            if row is None:
                continue
            if row[0] == admin_id:
                claimed.append(favorite_id)
                continue
            if row[0]:
                if {"kind": "favorite", "id": favorite_id} not in conflicts:
                    conflicts.append({"kind": "favorite", "id": favorite_id})
                continue
            connection.execute(
                "UPDATE favorite_points SET user_id = ? WHERE id = ? AND user_id IS NULL",
                (admin_id, favorite_id),
            )
            claimed.append(favorite_id)
        connection.commit()
    return claimed


def _copy_listed_memory(memory_root: Path, admin_id: str, names: list[str], done: list[str]) -> list[str]:
    copied = []
    target_dir = memory_root / "users" / admin_id
    for name in names:
        if name not in LEGACY_FILES or name in done:
            continue
        source = memory_root / name
        if not source.is_file():
            continue
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / name
        if target.exists():
            continue
        shutil.copy2(source, target)
        copied.append(name)
    return copied


def _write_backup(backup_dir: Path, store: AccountStore, manifest: dict, output_root: Path, favorite_db: Path, memory_root: Path) -> None:
    if backup_dir.exists() and any(backup_dir.iterdir()):
        raise FileExistsError(f"备份目录已有内容，拒绝覆盖：{backup_dir}")
    backup_dir.mkdir(parents=True)
    rows = []
    for job_id in manifest["jobs"]:
        found = store._query("SELECT id, owner_id FROM jobs WHERE id = ?", (job_id,))
        if found:
            rows.append({"id": found[0][0], "owner_id": found[0][1]})
    (backup_dir / "jobs.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if favorite_db.is_file():
        _copy_sqlite(favorite_db, backup_dir / "favorites.sqlite3")
    for name in manifest["experiments"]:
        source = output_root / name / "run_summary.json"
        if source.is_file():
            destination = backup_dir / "experiments" / name
            destination.mkdir(parents=True)
            shutil.copy2(source, destination / "run_summary.json")
    copied = {}
    for name in manifest["memory_files"]:
        source = memory_root / name
        if source.is_file():
            folder = backup_dir / "memory"
            folder.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, folder / name)
            copied[name] = True
    (backup_dir / "memory_sources.json").write_text(json.dumps(sorted(copied), ensure_ascii=False) + "\n", encoding="utf-8")


def _current_unowned(store, output_root, favorite_db, memory_root) -> dict:
    return {
        "jobs": sorted(row[0] for row in store._query("SELECT id FROM jobs WHERE owner_id IS NULL")),
        "experiments": sorted(path.name for path in _unowned_experiments(output_root)),
        "favorites": sorted(_unowned_favorite_ids(favorite_db)),
        "memory_files": [name for name in LEGACY_FILES if (memory_root / name).is_file()],
    }


def _unowned_experiments(output_root: Path) -> list[Path]:
    if not output_root.is_dir():
        return []
    found = []
    for directory in output_root.iterdir():
        if not directory.is_dir() or directory.name.startswith(".") or directory.is_symlink():
            continue
        summary_path = directory / "run_summary.json"
        if not summary_path.is_file():
            continue
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(summary, dict) and not summary.get("owner_id"):
            found.append(directory)
    return found


def _unowned_favorite_ids(favorite_db: Path) -> list[str]:
    if not favorite_db.is_file():
        return []
    with sqlite3.connect(favorite_db) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(favorite_points)")}
        if "user_id" not in columns:
            return [row[0] for row in connection.execute("SELECT id FROM favorite_points")]
        return [row[0] for row in connection.execute("SELECT id FROM favorite_points WHERE user_id IS NULL")]


def _require_admin(store: AccountStore, admin_id: str) -> None:
    user = store.get_user(admin_id)
    if user is None or user.role != "admin":
        raise ValueError("legacy migration requires an admin user")


def _require_writers_stopped(output_root: Path) -> None:
    try:
        with file_lock(output_root / "user-state/worker.lock"):
            return
    except SceneBusyError as exc:
        raise RuntimeError("API 或 Worker 仍在运行。停止写入后再冻结清单或执行迁移。") from exc


def _verify_manifest(manifest: dict) -> None:
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        raise ValueError("历史清单不可用")
    digest = manifest.get("sha256")
    body = {key: value for key, value in manifest.items() if key != "sha256"}
    if not isinstance(digest, str) or _digest(body) != digest:
        raise ValueError("历史清单校验失败，拒绝按它认领数据")
    for key in ("jobs", "experiments", "favorites", "memory_files", "batch_id"):
        if key not in manifest:
            raise ValueError("历史清单缺少字段")


def _digest(body: dict) -> str:
    payload = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _empty_sets() -> dict[str, list]:
    return {"jobs": [], "experiments": [], "favorites": [], "memory_files": []}


def _load_state(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _copy_sqlite(source: Path, destination: Path) -> None:
    """Consistent snapshot. A plain file copy would miss rows still sitting in the WAL."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".copying")
    if temporary.exists():
        temporary.unlink()
    with sqlite3.connect(source) as src, sqlite3.connect(temporary) as dst:
        src.backup(dst)
    temporary.replace(destination)


def _restore_sqlite(snapshot: Path, target: Path) -> None:
    for suffix in ("-wal", "-shm"):
        Path(str(target) + suffix).unlink(missing_ok=True)
    _copy_sqlite(snapshot, target)
    for suffix in ("-wal", "-shm"):
        Path(str(target) + suffix).unlink(missing_ok=True)


def _refuse_live_tree(paths: list[Path]) -> None:
    protected = [( _REPO / name).resolve() for name in ("outputs", "scenes", "memory")]
    for path in paths:
        resolved = path.resolve()
        if any(resolved == root or root in resolved.parents for root in protected):
            raise SystemExit(f"拒绝操作仓库里的真实数据：{resolved}。请改用停机后的副本。")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="按冻结清单迁移升级前的无主数据。")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--freeze", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--status", action="store_true")
    mode.add_argument("--restore", action="store_true")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--favorite-db", type=Path, required=True)
    parser.add_argument("--memory-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--admin-id")
    args = parser.parse_args(argv)
    _refuse_live_tree([args.output_root, args.favorite_db, args.memory_root, args.manifest])
    if args.database_url.startswith("sqlite:///"):
        _refuse_live_tree([Path(args.database_url.removeprefix("sqlite:///"))])
    from backend.app.infrastructure.repository import create_job_repository

    store = AccountStore(args.database_url, create_job_repository(args.database_url))
    state_path = args.state or args.manifest.with_name(args.manifest.stem + "-state.json")
    if args.freeze:
        save_manifest(args.manifest, freeze_manifest(store, args.output_root, args.favorite_db, args.memory_root))
        print(json.dumps({"froze": str(args.manifest), "batch_id": load_manifest(args.manifest)["batch_id"]}, ensure_ascii=False))
        return 0
    manifest = load_manifest(args.manifest) if args.manifest.is_file() else None
    if args.dry_run:
        print(json.dumps(dry_run(store, args.output_root, args.favorite_db, args.memory_root, manifest), ensure_ascii=False, indent=2))
        return 0
    if manifest is None:
        raise SystemExit("没有冻结的历史清单。先在写入停止后执行 --freeze。")
    if args.status:
        print(json.dumps(migration_status(manifest, state_path), ensure_ascii=False, indent=2))
        return 0
    if args.restore:
        if args.backup_dir is None:
            raise SystemExit("恢复需要 --backup-dir")
        if not args.admin_id:
            raise SystemExit("恢复需要 --admin-id，只删除该管理员目录下与备份字节相同的副本")
        restore_backup(store, args.output_root, args.favorite_db, args.memory_root, args.backup_dir, args.admin_id)
        print(json.dumps({"restored": str(args.backup_dir)}, ensure_ascii=False))
        return 0
    if not args.admin_id or args.backup_dir is None:
        raise SystemExit("执行迁移需要 --admin-id 和 --backup-dir")
    report = migrate_legacy(
        store, args.admin_id, args.output_root, args.favorite_db, args.memory_root, manifest, state_path, args.backup_dir,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
