from __future__ import annotations

import json
import platform
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Event, Lock
from typing import Callable

from cta_client.connection import ServerConnection
from cta_client.json_extract import iter_log_entries
from cta_client.paths import machine_id
from cta_client.tracker import CompletedGame, CompletedMatch, Identity, MatchTracker

StatusCallback = Callable[[str, str], None]


def machine_payload(arena_user_id: str | None = None, arena_screen_name: str | None = None) -> dict:
    return {
        "machine_id": machine_id(),
        "hostname": platform.node(),
        "platform": platform.platform(),
        "arena_user_id": arena_user_id,
        "arena_screen_name": arena_screen_name,
    }


@dataclass(frozen=True)
class ConnectionStatus:
    """A copy of one connection's state, safe to read from the GUI thread."""

    url: str
    label: str
    username: str
    state: str
    detail: str
    pending: int


class TelemetryService:
    """Reads the Arena log once and feeds every server the tester belongs to."""

    def __init__(
        self,
        connections: list[ServerConnection],
        log_path: Path,
        status: StatusCallback,
    ) -> None:
        self.connections = connections
        self.log_path = log_path
        self.status = status
        self.tracker = MatchTracker()
        self.stop_event = Event()
        self.paused = Event()
        self.offset = 0
        self.inode: int | None = None
        self.leftover = ""
        # Held whenever connections are read or replaced, because the GUI
        # thread reads them to draw the per-server list.
        self.lock = Lock()

    def stop(self) -> None:
        self.stop_event.set()

    def set_paused(self, paused: bool) -> None:
        self.paused.set() if paused else self.paused.clear()

    def snapshot(self) -> list[ConnectionStatus]:
        with self.lock:
            return [
                ConnectionStatus(
                    url=connection.profile.url,
                    label=connection.profile.label,
                    username=connection.profile.username,
                    state=connection.state,
                    detail=connection.detail,
                    pending=connection.pending,
                )
                for connection in self.connections
            ]

    def add_connection(self, connection: ServerConnection) -> None:
        """Attach a server while the service is already running.

        Adding a group should not interrupt uploads to the others, so the
        running loop picks it up rather than being torn down and rebuilt.
        """
        with self.lock:
            self.connections.append(connection)

    def remove_connection(self, url: str) -> ServerConnection | None:
        with self.lock:
            found = next((c for c in self.connections if c.profile.url == url), None)
            if found is not None:
                self.connections.remove(found)
        return found

    def run(self) -> None:
        while not self.stop_event.wait(0.5):
            if self.paused.is_set():
                self.status("paused", "Uploading is paused")
                continue
            if not self.log_path.exists():
                # Still check in. The group's admin should see a tester is
                # online before Arena is launched, and the tester should
                # find out now if a group is unreachable rather than
                # discovering it after playing a match.
                self._deliver()
                self.status("waiting", f"Waiting for Arena log at {self.log_path}")
                continue
            self._tick()
            self._report()

    def _tick(self) -> None:
        self._read_log()
        self._deliver()

    def _deliver(self) -> None:
        machine = machine_payload(
            self.tracker.identity.arena_user_id, self.tracker.identity.screen_name
        )
        with self.lock:
            connections = list(self.connections)
        # Each connection swallows and records its own failures, so one
        # unreachable server cannot stop the others from being served.
        for connection in connections:
            connection.deliver(machine)

    def _read_log(self) -> None:
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
        payload = asdict(event)
        with self.lock:
            connections = list(self.connections)
        # Every group gets its own copy, queued separately, so a server
        # that is down still receives this once it comes back.
        for connection in connections:
            connection.enqueue(path, payload)

    def _report(self) -> None:
        statuses = self.snapshot()
        if not statuses:
            self.status("idle", "No servers configured")
            return
        if all(status.state == "authentication" for status in statuses):
            self.status("authentication", "Sign in again")
            return
        troubled = [s for s in statuses if s.state in {"authentication", "reconnecting"}]
        pending = sum(status.pending for status in statuses)
        if troubled:
            # Degraded rather than broken: the healthy servers are still
            # being served, and saying so avoids a false alarm.
            self.status(
                "degraded",
                f"{len(statuses) - len(troubled)} of {len(statuses)} servers up · "
                f"{troubled[0].detail}",
            )
            return
        served = f"{len(statuses)} server{'' if len(statuses) == 1 else 's'}"
        self.status("uploading", f"Uploading to {served} · {pending} queued")


def diagnostics(service: TelemetryService) -> str:
    return json.dumps(
        {
            "log_path": str(service.log_path),
            "log_exists": service.log_path.exists(),
            "paused": service.paused.is_set(),
            "servers": [
                {
                    "url": status.url,
                    "group": status.label,
                    "username": status.username,
                    "state": status.state,
                    "queued": status.pending,
                }
                for status in service.snapshot()
            ],
        },
        indent=2,
    )
