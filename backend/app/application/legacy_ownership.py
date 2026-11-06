"""One-shot assignment of pre-upgrade rows. New rows without an owner stay invalid."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from backend.app.infrastructure.account_store import AccountStore


def precheck(store: AccountStore, output_root: Path, favorite_db: Path, memory_root: Path) -> dict:
    jobs = store._query("SELECT COUNT(*) FROM jobs WHERE owner_id IS NULL")[0][0]
    experiments = _unowned_experiments(output_root)
    favorites = 0
    if favorite_db.is_file():
        import sqlite3

        with sqlite3.connect(favorite_db) as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(favorite_points)")}
            if "user_id" in columns:
                favorites = connection.execute(
                    "SELECT COUNT(*) FROM favorite_points WHERE user_id IS NULL"
                ).fetchone()[0]
    legacy_memory = (memory_root / "MEMORY.md").is_file()
    return {
        "unowned_jobs": int(jobs),
        "unowned_experiments": len(experiments),
        "unowned_favorites": int(favorites),
        "legacy_memory_file": legacy_memory,
    }


def migrate_legacy(
    store: AccountStore,
    admin_id: str,
    output_root: Path,
    favorite_db: Path,
    memory_root: Path,
) -> dict:
    """Stamp existing unowned records. Does not delete experiments or rewrite scenes."""
    if store.get_user(admin_id) is None or store.get_user(admin_id).role != "admin":
        raise ValueError("legacy migration requires an admin user")
    before = precheck(store, output_root, favorite_db, memory_root)
    jobs = store.assign_unowned_jobs(admin_id)
    experiments = 0
    for directory in _unowned_experiments(output_root):
        path = directory / "run_summary.json"
        summary = json.loads(path.read_text(encoding="utf-8"))
        summary["owner_id"] = admin_id
        summary["owner_origin"] = "legacy"
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        experiments += 1
    favorites = _assign_favorites(favorite_db, admin_id)
    memory = _copy_legacy_memory(memory_root, admin_id)
    return {"before": before, "jobs": jobs, "experiments": experiments, "favorites": favorites, "memory_copied": memory}


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


def _assign_favorites(favorite_db: Path, admin_id: str) -> int:
    if not favorite_db.is_file():
        return 0
    import sqlite3

    with sqlite3.connect(favorite_db) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(favorite_points)")}
        if "user_id" not in columns:
            connection.execute("ALTER TABLE favorite_points ADD COLUMN user_id TEXT")
        cursor = connection.execute(
            "UPDATE favorite_points SET user_id = ? WHERE user_id IS NULL",
            (admin_id,),
        )
        connection.commit()
        return cursor.rowcount


def _copy_legacy_memory(memory_root: Path, admin_id: str) -> bool:
    source = memory_root / "MEMORY.md"
    if not source.is_file():
        return False
    target_dir = memory_root / "users" / admin_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "MEMORY.md"
    if not target.exists():
        shutil.copy2(source, target)
    for name in ("PREFERENCE_CHOICES.jsonl", "PREFERENCE_DEFAULTS.json"):
        legacy = memory_root / name
        if legacy.is_file() and not (target_dir / name).exists():
            shutil.copy2(legacy, target_dir / name)
    return True
