from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any


@dataclass(frozen=True)
class QueuedUpload:
    path: str
    payload: dict[str, Any]


class UploadQueue:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = Lock()

    def append(self, path: str, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"path": path, "payload": payload}, separators=(",", ":")) + "\n")

    def items(self) -> list[QueuedUpload]:
        if not self.path.exists():
            return []
        with self.lock:
            return [
                QueuedUpload(**json.loads(line))
                for line in self.path.read_text(encoding="utf-8").splitlines()
                if line
            ]

    def replace(self, items: list[QueuedUpload]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        content = "".join(
            json.dumps({"path": item.path, "payload": item.payload}, separators=(",", ":")) + "\n"
            for item in items
        )
        temporary = self.path.with_suffix(".tmp")
        with self.lock:
            temporary.write_text(content, encoding="utf-8")
            temporary.replace(self.path)
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from cta_client.paths import queue_dir


class DurableUploadQueue:
    def __init__(self, directory: Path | None = None, max_items: int = 1000) -> None:
        self.directory = directory or queue_dir()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.max_items = max_items

    def enqueue(self, endpoint: str, payload: dict[str, Any]) -> Path:
        if len(self) >= self.max_items:
            raise OverflowError("upload queue is full")
        name = f"{time.time_ns():020d}-{uuid.uuid4().hex}.json"
        target = self.directory / name
        temporary = target.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"endpoint": endpoint, "payload": payload}, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(target)
        return target

    def items(self) -> list[Path]:
        return sorted(self.directory.glob("*.json"))

    def read(self, item: Path) -> tuple[str, dict[str, Any]]:
        value = json.loads(item.read_text(encoding="utf-8"))
        return value["endpoint"], value["payload"]

    def remove(self, item: Path) -> None:
        item.unlink(missing_ok=True)

    def __len__(self) -> int:
        return sum(1 for _ in self.directory.glob("*.json"))


class QueuedUploader:
    def __init__(self, client: Any, queue: DurableUploadQueue) -> None:
        self.client = client
        self.queue = queue

    def submit(self, endpoint: str, payload: dict[str, Any]) -> None:
        item = self.queue.enqueue(endpoint, payload)
        self.client._post(endpoint, payload)
        self.queue.remove(item)

    def flush(self) -> int:
        sent = 0
        for item in self.queue.items():
            endpoint, payload = self.queue.read(item)
            self.client._post(endpoint, payload)
            self.queue.remove(item)
            sent += 1
        return sent
