from __future__ import annotations

import json
import logging
import platform
import time
from dataclasses import asdict
from pathlib import Path
from threading import Event
from typing import Callable

import httpx

from cta_client.json_extract import iter_log_entries
from cta_client.paths import machine_id
from cta_client.queue import QueuedUpload, UploadQueue
from cta_client.tracker import CompletedGame, CompletedMatch, Identity, MatchTracker
from cta_client.uploader import AuthenticationRequired, TelemetryClient


StatusCallback = Callable[[str, str], None]


def machine_payload(arena_user_id: str | None = None, arena_screen_name: str | None = None) -> dict:
    return {
        "machine_id": machine_id(),
        "hostname": platform.node(),
        "platform": platform.platform(),
        "arena_user_id": arena_user_id,
        "arena_screen_name": arena_screen_name,
    }


class TelemetryService:
    def __init__(
        self,
        client: TelemetryClient,
        log_path: Path,
        queue: UploadQueue,
        status: StatusCallback,
    ) -> None:
        self.client = client
        self.log_path = log_path
        self.queue = queue
        self.status = status
        self.tracker = MatchTracker()
        self.stop_event = Event()
        self.paused = Event()
        self.offset = 0
        self.inode: int | None = None
        self.leftover = ""
        self.last_heartbeat = 0.0
        self.backoff = 1.0

    def stop(self) -> None:
        self.stop_event.set()

    def set_paused(self, paused: bool) -> None:
        self.paused.set() if paused else self.paused.clear()

    def run(self) -> None:
        while not self.stop_event.wait(0.5):
            if self.paused.is_set():
                self.status("paused", "Uploading is paused")
                continue
            if not self.log_path.exists():
                self.status("waiting", f"Waiting for Arena log at {self.log_path}")
                continue
            try:
                self._tick()
                self.backoff = 1.0
            except AuthenticationRequired:
                self.status("authentication", "Sign in again")
                return
            except (httpx.TransportError, httpx.HTTPStatusError, OSError) as error:
                logging.warning("Telemetry retry in %.0fs: %s", self.backoff, error)
                self.status("reconnecting", f"Connection interrupted; retrying in {self.backoff:.0f}s")
                self.stop_event.wait(self.backoff)
                self.backoff = min(60.0, self.backoff * 2)

    def _tick(self) -> None:
        stat = self.log_path.stat()
        current_inode = getattr(stat, "st_ino", None)
        if self.inode is not None and current_inode != self.inode or stat.st_size < self.offset:
            self.offset, self.leftover = 0, ""
        self.inode = current_inode
        with self.log_path.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(self.offset)
            chunk = handle.read()
            self.offset = handle.tell()
        self._consume(self.leftover + chunk)
        self._drain_queue()
        now = time.monotonic()
        if now - self.last_heartbeat >= 20:
            self.client.heartbeat(
                machine_payload(self.tracker.identity.arena_user_id, self.tracker.identity.screen_name)
            )
            self.last_heartbeat = now
        self.status("uploading", f"Uploading · {len(self.queue.items())} queued")

    def _consume(self, text: str) -> None:
        if not text:
            return
        last_header = max(text.rfind("[UnityCrossThreadLogger]"), text.rfind("<=="))
        if last_header > 0 and not text.endswith("\n"):
            self.leftover, text = text[last_header:], text[:last_header]
        else:
            self.leftover = ""
        for entry in iter_log_entries(text):
            for obj in entry.json_objects:
                for event in self.tracker.consume(obj, entry.api_name, entry.timestamp):
                    self._enqueue(event)

    def _enqueue(self, event: CompletedGame | CompletedMatch | Identity) -> None:
        if isinstance(event, Identity):
            path = "/api/ingest/identity"
        elif isinstance(event, CompletedGame):
            path = "/api/ingest/game"
        else:
            path = "/api/ingest/match"
        self.queue.append(path, asdict(event))

    def _drain_queue(self) -> None:
        pending = self.queue.items()
        remaining: list[QueuedUpload] = []
        for index, item in enumerate(pending):
            try:
                self.client.post(item.path, item.payload)
            except AuthenticationRequired:
                raise
            except (httpx.TransportError, httpx.HTTPStatusError):
                remaining = pending[index:]
                break
        self.queue.replace(remaining)


def diagnostics(service: TelemetryService) -> str:
    return json.dumps(
        {
            "log_path": str(service.log_path),
            "log_exists": service.log_path.exists(),
            "queued_uploads": len(service.queue.items()),
            "paused": service.paused.is_set(),
        },
        indent=2,
    )
