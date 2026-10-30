from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class FavoritePoint:
    id: str
    scene_id: str
    longitude: float
    latitude: float
    width_m: float
    height_m: float
    bearing_deg: float
    created_at: str
    updated_at: str


class FavoritePointRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = ":memory:" if str(path) == ":memory:" else str(Path(path).expanduser().resolve())
        if self.path != ":memory:":
            Path(self.path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            if self.path != ":memory:":
                connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS favorite_points (
                    id TEXT PRIMARY KEY,
                    scene_id TEXT NOT NULL,
                    longitude REAL NOT NULL,
                    latitude REAL NOT NULL,
                    width_m REAL NOT NULL,
                    height_m REAL NOT NULL,
                    bearing_deg REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS favorite_points_scene_id "
                "ON favorite_points(scene_id, created_at, id)"
            )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _point(row: sqlite3.Row) -> FavoritePoint:
        return FavoritePoint(
            id=row["id"],
            scene_id=row["scene_id"],
            longitude=float(row["longitude"]),
            latitude=float(row["latitude"]),
            width_m=float(row["width_m"]),
            height_m=float(row["height_m"]),
            bearing_deg=float(row["bearing_deg"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def list_for_scene(self, scene_id: str) -> list[FavoritePoint]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM favorite_points WHERE scene_id = ? "
                "ORDER BY created_at, id",
                (scene_id,),
            ).fetchall()
        return [self._point(row) for row in rows]

    def copy_to_scene(self, source_scene_id: str, target_scene_id: str) -> int:
        """Copy geographic favorites once; preserve originals and already edited target copies."""
        if source_scene_id == target_scene_id:
            raise ValueError("favorite migration requires distinct scenes")
        copied = 0
        with self._connection() as connection:
            rows = connection.execute("SELECT * FROM favorite_points WHERE scene_id = ?", (source_scene_id,)).fetchall()
            for row in rows:
                identity = str(uuid.uuid5(uuid.NAMESPACE_URL, f"favorite:{row['id']}:scene:{target_scene_id}"))
                cursor = connection.execute(
                    "INSERT OR IGNORE INTO favorite_points "
                    "(id,scene_id,longitude,latitude,width_m,height_m,bearing_deg,created_at,updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (identity, target_scene_id, row["longitude"], row["latitude"], row["width_m"],
                     row["height_m"], row["bearing_deg"], row["created_at"], row["updated_at"]),
                )
                copied += cursor.rowcount
        return copied

    def create(
        self,
        scene_id: str,
        longitude: float,
        latitude: float,
        width_m: float,
        height_m: float,
        bearing_deg: float,
    ) -> FavoritePoint:
        now = self._now()
        favorite_id = str(uuid.uuid4())
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO favorite_points
                (id, scene_id, longitude, latitude, width_m, height_m,
                 bearing_deg, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    favorite_id,
                    scene_id,
                    longitude,
                    latitude,
                    width_m,
                    height_m,
                    bearing_deg,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM favorite_points WHERE id = ?", (favorite_id,)
            ).fetchone()
        if row is None:
            raise RuntimeError("created favorite point could not be read back")
        return self._point(row)

    def update(
        self,
        scene_id: str,
        favorite_id: str,
        longitude: float,
        latitude: float,
        bearing_deg: float,
    ) -> FavoritePoint | None:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE favorite_points
                SET longitude = ?, latitude = ?, bearing_deg = ?, updated_at = ?
                WHERE id = ? AND scene_id = ?
                """,
                (
                    longitude,
                    latitude,
                    bearing_deg,
                    self._now(),
                    favorite_id,
                    scene_id,
                ),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                "SELECT * FROM favorite_points WHERE id = ?", (favorite_id,)
            ).fetchone()
        if row is None:
            raise RuntimeError("updated favorite point could not be read back")
        return self._point(row)

    def delete(self, scene_id: str, favorite_id: str) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM favorite_points WHERE id = ? AND scene_id = ?",
                (favorite_id, scene_id),
            )
            return cursor.rowcount > 0

    def delete_for_scene(self, scene_id: str) -> int:
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM favorite_points WHERE scene_id = ?",
                (scene_id,),
            )
            return cursor.rowcount
