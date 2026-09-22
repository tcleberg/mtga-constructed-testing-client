"""One server this install uploads to.

Each server owns its queue, its token, and its own failure state. That
isolation is the point: a group whose server is down, or whose account has
been revoked, must not stop uploads to any other group. The Arena log is
read once and handed to every connection, and from there they are
independent.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from cta_client.profiles import ServerProfile
from cta_client.queue import QueuedUpload, UploadQueue
from cta_client.uploader import AuthenticationRequired, TelemetryClient

HEARTBEAT_INTERVAL = 20.0
MAX_BACKOFF = 60.0


class ServerConnection:
    def __init__(
        self,
        profile: ServerProfile,
        client: TelemetryClient,
        queue: UploadQueue,
    ) -> None:
        self.profile = profile
        self.client = client
        self.queue = queue
        self.state = "starting"
        self.detail = ""
        self.backoff = 1.0
        self.retry_after = 0.0
        self.last_heartbeat = 0.0

    @property
    def needs_sign_in(self) -> bool:
        return self.state == "authentication"

    @property
    def pending(self) -> int:
        return len(self.queue.items())

    def enqueue(self, path: str, payload: dict[str, Any]) -> None:
        """Record an upload owed to this server.

        Written even while the server is unreachable or the account is
        signed out, so evidence gathered during an outage is delivered
        once the problem is fixed rather than lost.
        """
        self.queue.append(path, payload)

    def deliver(self, machine: dict[str, Any]) -> None:
        """Send whatever is owed, and note what happened.

        Never raises. A connection reports its own trouble through its
        state so the service can carry on with the others.
        """
        if self.needs_sign_in or time.monotonic() < self.retry_after:
            return
        try:
            self._drain()
            self._heartbeat(machine)
        except AuthenticationRequired:
            # Nothing to retry: this needs a person. The queue is kept so
            # the backlog survives signing back in.
            self.state = "authentication"
            self.detail = f"{self.profile.label} needs you to sign in again"
            return
        except (httpx.TransportError, httpx.HTTPStatusError, OSError) as error:
            logging.warning("%s retry in %.0fs: %s", self.profile.url, self.backoff, error)
            self.state = "reconnecting"
            self.detail = f"{self.profile.label} unreachable; retrying in {self.backoff:.0f}s"
            self.retry_after = time.monotonic() + self.backoff
            self.backoff = min(MAX_BACKOFF, self.backoff * 2)
            return
        self.backoff = 1.0
        self.retry_after = 0.0
        self.state = "uploading"
        pending = self.pending
        self.detail = f"{self.profile.label} up to date" if not pending else (
            f"{self.profile.label} · {pending} queued"
        )

    def _drain(self) -> None:
        pending = self.queue.items()
        remaining: list[QueuedUpload] = []
        for index, item in enumerate(pending):
            try:
                self.client.post(item.path, item.payload)
            except (AuthenticationRequired, httpx.TransportError, httpx.HTTPStatusError):
                # Stop at the first failure rather than skipping past it,
                # so uploads keep their order and nothing is dropped.
                remaining = pending[index:]
                self.queue.replace(remaining)
                raise
        self.queue.replace(remaining)

    def _heartbeat(self, machine: dict[str, Any]) -> None:
        now = time.monotonic()
        if now - self.last_heartbeat < HEARTBEAT_INTERVAL:
            return
        self.client.heartbeat(machine)
        self.last_heartbeat = now

    def close(self) -> None:
        self.client.close()
