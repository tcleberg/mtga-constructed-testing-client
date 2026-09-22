from dataclasses import dataclass

import httpx

import cta_client.credentials as credentials_module
from cta_client import __version__
from cta_client.credentials import CredentialStore
from cta_client.queue import UploadQueue
from cta_client.uploader import TelemetryClient


class MemoryKeyring:
    def __init__(self):
        self.values = {}

    def get_password(self, service, username):
        return self.values.get((service, username))

    def set_password(self, service, username, password):
        self.values[(service, username)] = password

    def delete_password(self, service, username):
        del self.values[(service, username)]


def test_migrates_plaintext_token_to_keyring(monkeypatch):
    written = {}
    monkeypatch.setattr(
        credentials_module,
        "load_client_config",
        lambda: {"server": "https://example.test", "username": "alice", "token": "secret"},
    )
    monkeypatch.setattr(credentials_module, "save_client_config", written.update)
    store = CredentialStore(MemoryKeyring())

    assert store.migrate_legacy_token()
    assert store.get_token("https://example.test", "alice") == "secret"
    assert written == {"server": "https://example.test", "username": "alice"}


def test_upload_queue_round_trip(tmp_path):
    queue = UploadQueue(tmp_path / "queue.jsonl")
    queue.append("/api/ingest/game", {"match_id": "m1"})
    item = queue.items()[0]
    assert item.path == "/api/ingest/game"
    queue.replace([])
    assert queue.items() == []


def test_login_and_heartbeat_report_client_version():
    requests = []

    def handler(request: httpx.Request):
        requests.append(request)
        if request.url.path == "/api/login":
            return httpx.Response(200, json={"token": "token", "session_id": "s"})
        return httpx.Response(200, json={"ok": True})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = TelemetryClient("https://example.test", http=http)
        client.login("alice", "password", {"machine_id": "machine"})
        client.heartbeat({"machine_id": "machine"})

    # Against __version__ rather than a literal: the point is that the
    # server is told which build is talking to it, not which build it is.
    expected = f'"client_version":"{__version__}"'.encode()
    assert expected in requests[0].content
    assert expected in requests[1].content
    assert requests[1].headers["authorization"] == "Bearer token"
