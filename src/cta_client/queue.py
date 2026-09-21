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
