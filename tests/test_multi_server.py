from pathlib import Path

import httpx
import pytest

import cta_client.paths as paths_module
import cta_client.profiles as profiles_module
import cta_client.session as session_module
from cta_client.connection import ServerConnection
from cta_client.credentials import CredentialStore
from cta_client.profiles import (
    ClientConfig,
    ServerProfile,
    load_config,
    normalize_server_url,
    save_config,
)
from cta_client.queue import UploadQueue
from cta_client.service import TelemetryService, diagnostics
from cta_client.session import plant_dashboard_cookie, restore_connections, sign_in
from cta_client.tracker import Identity
from cta_client.uploader import IncompatibleServer, TelemetryClient

from tests.test_client_services import MemoryKeyring


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    """Point every config read and write at a throwaway directory."""
    monkeypatch.setattr(paths_module, "client_config_dir", lambda: tmp_path)
    monkeypatch.setattr(profiles_module, "load_client_config", lambda: _stored[0])
    monkeypatch.setattr(profiles_module, "save_client_config", lambda data: _stored.__setitem__(0, data))
    monkeypatch.setattr(session_module, "client_config_dir", lambda: tmp_path)
    return tmp_path


_stored: list[dict] = [{}]


@pytest.fixture(autouse=True)
def clear_stored():
    _stored[0] = {}
    yield
    _stored[0] = {}


def connection(url, tmp_path, handler, *, username="alice", group_name=""):
    http = httpx.Client(transport=httpx.MockTransport(handler))
    profile = ServerProfile(url=url, username=username, group_name=group_name)
    return ServerConnection(
        profile,
        TelemetryClient(url, "token", http=http),
        UploadQueue(tmp_path / profile.queue_filename),
    )


def ok(request):
    return httpx.Response(200, json={"ok": True})


def unreachable(request):
    raise httpx.ConnectError("refused", request=request)


def rejected(request):
    return httpx.Response(401, json={"detail": "no"})


# Profiles ------------------------------------------------------------


def test_an_address_typed_any_of_the_usual_ways_is_one_server(config_dir):
    assert (
        normalize_server_url("omaha.mtgtest.com/")
        == normalize_server_url("https://omaha.mtgtest.com")
        == "https://omaha.mtgtest.com"
    )


def test_each_server_gets_its_own_queue_file():
    omaha = ServerProfile(url="https://omaha.mtgtest.com", username="alice")
    tic = ServerProfile(url="https://tic.mtgtest.com", username="alice")
    assert omaha.queue_filename != tic.queue_filename
    # Stable across runs, or a restart would orphan the backlog.
    assert omaha.queue_filename == ServerProfile(url=omaha.url, username="bob").queue_filename


def test_an_install_from_before_multi_server_keeps_its_server(config_dir):
    _stored[0] = {"server": "https://omaha.mtgtest.com/", "username": "alice", "log_path": "/logs/P.log"}

    config = load_config()

    assert [(s.url, s.username) for s in config.servers] == [("https://omaha.mtgtest.com", "alice")]
    assert Path(config.log_path) == Path("/logs/P.log")


def test_the_migrated_token_is_still_found_because_the_url_matches(config_dir):
    _stored[0] = {"server": "https://omaha.mtgtest.com/", "username": "alice"}
    credentials = CredentialStore(MemoryKeyring())
    # Stored by the old client against the address as it typed it.
    credentials.set_token("https://omaha.mtgtest.com", "alice", "kept")

    connections = restore_connections(load_config(), credentials)

    assert [c.client.token for c in connections] == ["kept"]


def test_servers_survive_a_save_and_reload(config_dir):
    config = ClientConfig(servers=[], log_path="/logs/P.log")
    config.upsert(ServerProfile(url="https://omaha.mtgtest.com", username="alice", group_name="Omaha"))
    config.upsert(ServerProfile(url="https://tic.mtgtest.com", username="alice", group_name="TIC"))
    save_config(config)

    reloaded = load_config()

    assert [s.group_name for s in reloaded.servers] == ["Omaha", "TIC"]


def test_signing_in_again_updates_the_server_rather_than_duplicating_it(config_dir):
    config = ClientConfig()
    config.upsert(ServerProfile(url="https://omaha.mtgtest.com", username="alice"))
    config.upsert(ServerProfile(url="https://omaha.mtgtest.com", username="alice", group_name="Omaha"))

    assert len(config.servers) == 1
    assert config.servers[0].group_name == "Omaha"


def test_a_profile_without_a_token_is_reported_not_forgotten(config_dir):
    config = ClientConfig(servers=[ServerProfile(url="https://tic.mtgtest.com", username="alice")])

    assert restore_connections(config, CredentialStore(MemoryKeyring())) == []
    assert len(config.servers) == 1


# Fan-out -------------------------------------------------------------


def test_every_group_receives_a_copy_of_the_same_game(config_dir, tmp_path):
    omaha = connection("https://omaha.test", tmp_path, ok)
    tic = connection("https://tic.test", tmp_path, ok)
    service = TelemetryService([omaha, tic], tmp_path / "Player.log", lambda *_: None)

    service._enqueue(Identity(arena_user_id="u1", screen_name="Alice#1"))

    assert [i.path for i in omaha.queue.items()] == ["/api/ingest/identity"]
    assert omaha.queue.items()[0].payload == tic.queue.items()[0].payload


def test_one_unreachable_group_does_not_hold_up_the_other(config_dir, tmp_path):
    sent = []

    def recording(request):
        sent.append(str(request.url))
        return httpx.Response(200, json={"ok": True})

    omaha = connection("https://omaha.test", tmp_path, recording)
    tic = connection("https://tic.test", tmp_path, unreachable)
    for conn in (omaha, tic):
        conn.enqueue("/api/ingest/game", {"match_id": "m1"})

    for conn in (omaha, tic):
        conn.deliver({"machine_id": "m"})

    assert omaha.state == "uploading" and omaha.pending == 0
    assert tic.state == "reconnecting" and tic.pending == 1
    assert "https://omaha.test/api/ingest/game" in sent


def test_a_revoked_account_on_one_group_leaves_the_other_uploading(config_dir, tmp_path):
    omaha = connection("https://omaha.test", tmp_path, ok)
    tic = connection("https://tic.test", tmp_path, rejected)
    service = TelemetryService([omaha, tic], tmp_path / "Player.log", lambda *_: None)
    reported = []
    service.status = lambda state, message: reported.append((state, message))
    for conn in (omaha, tic):
        conn.enqueue("/api/ingest/game", {"match_id": "m1"})
        conn.deliver({"machine_id": "m"})

    service._report()

    assert omaha.state == "uploading"
    assert tic.needs_sign_in
    # The backlog is kept so signing back in delivers it.
    assert tic.pending == 1
    assert reported[0][0] == "degraded"


def test_the_service_only_calls_for_a_sign_in_when_every_group_needs_one(config_dir, tmp_path):
    omaha = connection("https://omaha.test", tmp_path, rejected)
    tic = connection("https://tic.test", tmp_path, rejected)
    service = TelemetryService([omaha, tic], tmp_path / "Player.log", lambda *_: None)
    reported = []
    service.status = lambda state, message: reported.append((state, message))
    for conn in (omaha, tic):
        conn.enqueue("/api/ingest/game", {"match_id": "m1"})
        conn.deliver({"machine_id": "m"})

    service._report()

    assert reported[0][0] == "authentication"


def test_a_failed_upload_stops_the_queue_rather_than_skipping_past_it(config_dir, tmp_path):
    attempts = []

    def second_one_fails(request):
        attempts.append(request.content)
        if len(attempts) == 2:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json={"ok": True})

    conn = connection("https://omaha.test", tmp_path, second_one_fails)
    for index in range(3):
        conn.enqueue("/api/ingest/game", {"match_id": f"m{index}"})

    conn.deliver({"machine_id": "m"})

    # The one that failed is still first in line, and the third was not
    # sent ahead of it.
    assert [i.payload["match_id"] for i in conn.queue.items()] == ["m1", "m2"]


def test_a_group_added_while_running_starts_receiving_without_a_restart(config_dir, tmp_path):
    omaha = connection("https://omaha.test", tmp_path, ok)
    service = TelemetryService([omaha], tmp_path / "Player.log", lambda *_: None)

    tic = connection("https://tic.test", tmp_path, ok)
    service.add_connection(tic)
    service._enqueue(Identity(arena_user_id="u1", screen_name="Alice#1"))

    assert len(service.snapshot()) == 2
    assert omaha.pending == 1 and tic.pending == 1


def test_groups_are_contacted_before_arena_is_ever_launched(config_dir, tmp_path):
    beats = []

    def recording(request):
        beats.append(request.url.path)
        return httpx.Response(200, json={"ok": True})

    omaha = connection("https://omaha.test", tmp_path, recording)
    # No Player.log: the tester has the client running but Arena closed.
    service = TelemetryService([omaha], tmp_path / "missing.log", lambda *_: None)
    service.stop_event.set()
    service._deliver()

    assert beats == ["/api/heartbeat"]
    assert omaha.state == "uploading"


def test_removing_a_group_stops_its_uploads(config_dir, tmp_path):
    omaha = connection("https://omaha.test", tmp_path, ok)
    tic = connection("https://tic.test", tmp_path, ok)
    service = TelemetryService([omaha, tic], tmp_path / "Player.log", lambda *_: None)

    removed = service.remove_connection("https://tic.test")

    assert removed is tic
    assert [s.url for s in service.snapshot()] == ["https://omaha.test"]


def test_diagnostics_name_every_group_and_its_backlog(config_dir, tmp_path):
    omaha = connection("https://omaha.test", tmp_path, ok, group_name="Omaha Testing Group")
    omaha.enqueue("/api/ingest/game", {"match_id": "m1"})
    service = TelemetryService([omaha], tmp_path / "Player.log", lambda *_: None)

    report = diagnostics(service)

    assert "Omaha Testing Group" in report
    assert '"queued": 1' in report


# Sign-in and handoff -------------------------------------------------


def test_signing_in_names_the_group_and_keeps_the_token(config_dir, monkeypatch):
    def handler(request):
        if request.url.path == "/api/server-info":
            return httpx.Response(200, json={"group_name": "Omaha Testing Group", "api_version": 1})
        return httpx.Response(200, json={"token": "granted", "session_id": "s"})

    monkeypatch.setattr(
        session_module,
        "TelemetryClient",
        lambda url, token=None: TelemetryClient(
            url, token, http=httpx.Client(transport=httpx.MockTransport(handler))
        ),
    )
    credentials = CredentialStore(MemoryKeyring())

    conn = sign_in("omaha.mtgtest.com", "alice", "password", credentials)

    assert conn.profile.group_name == "Omaha Testing Group"
    assert conn.profile.url == "https://omaha.mtgtest.com"
    assert credentials.get_token("https://omaha.mtgtest.com", "alice") == "granted"


def test_a_server_newer_than_this_build_is_refused_before_a_password_is_sent():
    def handler(request):
        return httpx.Response(200, json={"group_name": "Future", "api_version": 99})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = TelemetryClient("https://future.test", http=http)
        with pytest.raises(IncompatibleServer, match="newer client"):
            client.server_info()


def test_the_handoff_link_is_built_against_the_server_that_issued_it():
    def handler(request):
        assert request.headers["authorization"] == "Bearer token"
        return httpx.Response(200, json={"path": "/auth/handoff?ticket=abc", "expires_at": "x"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = TelemetryClient("https://omaha.test", "token", http=http)
        assert client.web_handoff_url() == "https://omaha.test/auth/handoff?ticket=abc"


def test_the_browser_is_signed_in_once_per_group_not_once_per_launch(config_dir, tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(session_module.webbrowser, "open", lambda url: opened.append(url) or True)

    def handler(request):
        return httpx.Response(200, json={"path": "/auth/handoff?ticket=abc", "expires_at": "x"})

    conn = connection("https://omaha.test", tmp_path, handler)
    config = ClientConfig(servers=[conn.profile])

    assert plant_dashboard_cookie(conn, config)
    assert not plant_dashboard_cookie(conn, config)
    assert opened == ["https://omaha.test/auth/handoff?ticket=abc"]
    assert config.servers[0].dashboard_opened


def test_a_dashboard_that_will_not_open_does_not_take_uploading_down(config_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(session_module.webbrowser, "open", lambda url: True)
    conn = connection("https://omaha.test", tmp_path, unreachable)
    config = ClientConfig(servers=[conn.profile])

    assert plant_dashboard_cookie(conn, config) is False
    # Unmarked, so a later launch tries again rather than silently never
    # signing the browser in.
    assert not config.servers[0].dashboard_opened


def test_a_group_the_browser_already_knows_is_not_reopened_after_a_restart(config_dir):
    config = ClientConfig()
    config.upsert(ServerProfile(url="https://omaha.test", username="alice", dashboard_opened=True))
    save_config(config)

    assert load_config().servers[0].dashboard_opened
