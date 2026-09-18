from __future__ import annotations

from typing import Protocol

import keyring

from cta_client.paths import load_client_config, save_client_config


SERVICE_NAME = "mtga-constructed-testing-client"


class Keyring(Protocol):
    def get_password(self, service: str, username: str) -> str | None: ...
    def set_password(self, service: str, username: str, password: str) -> None: ...
    def delete_password(self, service: str, username: str) -> None: ...


def credential_key(server: str, username: str) -> str:
    return f"{server.rstrip('/')}|{username}"


class CredentialStore:
    def __init__(self, backend: Keyring = keyring) -> None:
        self.backend = backend

    def get_token(self, server: str, username: str) -> str | None:
        return self.backend.get_password(SERVICE_NAME, credential_key(server, username))

    def set_token(self, server: str, username: str, token: str) -> None:
        self.backend.set_password(SERVICE_NAME, credential_key(server, username), token)

    def delete_token(self, server: str, username: str) -> None:
        token = self.get_token(server, username)
        if token is not None:
            self.backend.delete_password(SERVICE_NAME, credential_key(server, username))

    def migrate_legacy_token(self) -> bool:
        config = load_client_config()
        token = config.pop("token", None)
        server = config.get("server")
        username = config.get("username")
        if not token or not server or not username:
            return False
        self.set_token(server, username, token)
        save_client_config(config)
        return True
