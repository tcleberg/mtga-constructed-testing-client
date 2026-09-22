from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

import httpx

from cta_client import __version__


# Bumped by the server only when the ingest contract changes in a way an
# older client cannot satisfy.
SUPPORTED_API_VERSION = 1


class AuthenticationRequired(RuntimeError):
    pass


class IncompatibleServer(RuntimeError):
    """A server speaking a contract this client build does not know."""


class TelemetryClient:
    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        *,
        timeout: float = 15.0,
        http: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.http = http or httpx.Client(timeout=timeout)
        self._owns_http = http is None

    def close(self) -> None:
        if self._owns_http:
            self.http.close()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def server_info(self) -> dict[str, Any]:
        """Ask an address what it is before asking anyone to trust it.

        Unauthenticated on purpose, so the add-server flow can show which
        group a URL belongs to before the tester types a password.
        """
        response = self.http.get(f"{self.base_url}/api/server-info")
        response.raise_for_status()
        info = response.json()
        version = int(info.get("api_version", 0))
        if version > SUPPORTED_API_VERSION:
            raise IncompatibleServer(
                f"{info.get('group_name') or self.base_url} needs a newer client"
            )
        return info

    def web_handoff_url(self) -> str:
        """Trade this session for a one-shot link that signs the browser in.

        Lets a tester reach their dashboard without typing the password
        again. The link is single use and expires in about a minute, so it
        is fetched immediately before opening a browser and never stored.
        """
        response = self.http.post(f"{self.base_url}/api/web-handoff", headers=self._headers())
        self._raise(response)
        return f"{self.base_url}{response.json()['path']}"

    def login(self, username: str, password: str, machine: dict[str, Any]) -> dict[str, Any]:
        response = self.http.post(
            f"{self.base_url}/api/login",
            json={
                "username": username,
                "password": password,
                "client_version": __version__,
                **machine,
            },
        )
        self._raise(response)
        payload = response.json()
        self.token = payload["token"]
        return payload

    def heartbeat(self, machine: dict[str, Any]) -> dict[str, Any]:
        response = self.http.post(
            f"{self.base_url}/api/heartbeat",
            headers=self._headers(),
            json={"client_version": __version__, **machine},
        )
        self._raise(response)
        return response.json()

    def upload_identity(self, identity: Any) -> None:
        self.post("/api/ingest/identity", asdict(identity))

    def upload_game(self, game: Any) -> None:
        self.post("/api/ingest/game", asdict(game))

    def upload_match(self, match: Any) -> None:
        self.post("/api/ingest/match", asdict(match) if is_dataclass(match) else match)

    def post(self, path: str, payload: dict[str, Any]) -> None:
        response = self.http.post(
            f"{self.base_url}{path}",
            headers=self._headers(),
            json=payload,
        )
        self._raise(response)

    @staticmethod
    def _raise(response: httpx.Response) -> None:
        if response.status_code in {401, 403}:
            raise AuthenticationRequired("Sign-in is required")
        response.raise_for_status()
