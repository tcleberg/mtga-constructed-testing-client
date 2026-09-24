"""Which servers this install uploads to.

A tester can belong to more than one testing group, and the groups are run
independently: separate deployments, separate databases, separate accounts.
So each server carries its own credentials and its own upload queue, and
the only thing they share is the Arena log being read.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, replace

from cta_client.paths import load_client_config, resolve_player_log_path, save_client_config


def normalize_server_url(url: str) -> str:
    """Put a hand-typed address into the one form used as a key everywhere.

    The URL identifies the profile, names the queue file, and keys the
    keyring entry, so "omaha.mtgtest.com/" and "https://omaha.mtgtest.com"
    have to resolve to the same string or a tester ends up with two of
    everything.
    """
    url = url.strip().rstrip("/")
    if url and "://" not in url:
        url = f"https://{url}"
    return url


@dataclass(frozen=True)
class ServerProfile:
    url: str
    username: str
    # Shown instead of the URL once the server has told us what it calls
    # itself, which is the only reason the client knows the group name.
    group_name: str = ""
    # Whether this browser has been signed in to the server's dashboard.
    # One tab on first sign-in is enough; the cookie slides from there.
    dashboard_opened: bool = False

    @property
    def label(self) -> str:
        return self.group_name or self.url

    @property
    def queue_filename(self) -> str:
        """A readable, collision-free queue filename for this server.

        The digest is what actually guarantees uniqueness; the readable
        part is there so the config directory can be understood at a
        glance when someone is debugging an install.
        """
        digest = hashlib.sha256(self.url.encode("utf-8")).hexdigest()[:8]
        readable = re.sub(r"[^a-z0-9]+", "-", self.url.lower()).strip("-")[:40]
        return f"uploads-{readable}-{digest}.jsonl"


@dataclass
class ClientConfig:
    servers: list[ServerProfile] = field(default_factory=list)
    log_path: str = ""

    def find(self, url: str) -> ServerProfile | None:
        url = normalize_server_url(url)
        return next((server for server in self.servers if server.url == url), None)

    def upsert(self, profile: ServerProfile) -> None:
        """Add a server, or update the one already registered at that URL."""
        for index, existing in enumerate(self.servers):
            if existing.url == profile.url:
                self.servers[index] = profile
                return
        self.servers.append(profile)

    def remove(self, url: str) -> ServerProfile | None:
        profile = self.find(url)
        if profile is not None:
            self.servers.remove(profile)
        return profile

    def mark_dashboard_opened(self, url: str) -> None:
        profile = self.find(url)
        if profile is not None and not profile.dashboard_opened:
            self.upsert(replace(profile, dashboard_opened=True))


def load_config() -> ClientConfig:
    raw = load_client_config()
    servers = [
        ServerProfile(
            url=normalize_server_url(entry.get("url", "")),
            username=entry.get("username", ""),
            group_name=entry.get("group_name", ""),
            dashboard_opened=bool(entry.get("dashboard_opened")),
        )
        for entry in raw.get("servers", [])
        if entry.get("url") and entry.get("username")
    ]
    # Installs from before multi-server support stored one server inline.
    # Carrying it over keeps their keyring token valid, since the token is
    # keyed by the same normalized URL and username.
    if not servers and raw.get("server") and raw.get("username"):
        servers = [
            ServerProfile(
                url=normalize_server_url(raw["server"]),
                username=raw["username"],
            )
        ]
    return ClientConfig(
        servers=servers,
        log_path=str(resolve_player_log_path(raw.get("log_path") or "")),
    )


def save_config(config: ClientConfig) -> None:
    save_client_config(
        {
            "servers": [
                {
                    "url": server.url,
                    "username": server.username,
                    "group_name": server.group_name,
                    "dashboard_opened": server.dashboard_opened,
                }
                for server in config.servers
            ],
            "log_path": config.log_path,
        }
    )
