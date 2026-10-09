from __future__ import annotations

import json
import queue
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class QueueMessage:
    job_id: str


class TaskQueue(Protocol):
    def enqueue(self, job_id: str) -> None: ...

    def dequeue(self, timeout: int = 5) -> QueueMessage | None: ...


class InMemoryTaskQueue:
    def __init__(self) -> None:
        self._queue: queue.Queue[QueueMessage] = queue.Queue()

    def enqueue(self, job_id: str) -> None:
        self._queue.put(QueueMessage(job_id))

    def dequeue(self, timeout: int = 5) -> QueueMessage | None:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None


class RedisTaskQueue:
    key = "site-modeling:v0:jobs"

    def __init__(self, url: str) -> None:
        try:
            import redis
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Redis requires the redis package") from exc
        self._client = redis.Redis.from_url(url, decode_responses=True)

    def enqueue(self, job_id: str) -> None:
        self._client.lpush(self.key, json.dumps({"job_id": job_id}))

    def dequeue(self, timeout: int = 5) -> QueueMessage | None:
        result = self._client.brpop(self.key, timeout=timeout)
        if result is None:
            return None
        return QueueMessage(json.loads(result[1])["job_id"])


def create_task_queue(redis_url: str | None) -> TaskQueue:
    if not redis_url:
        return InMemoryTaskQueue()
    if not redis_url.startswith("redis://"):
        raise ValueError(f"unsupported REDIS_URL: {redis_url!r}")
    return RedisTaskQueue(redis_url)
