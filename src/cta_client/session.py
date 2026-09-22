"""Turning saved profiles into live connections.

Shared by the desktop app and the command line so both sign in, store
tokens, and open dashboards the same way.
"""

from __future__ import annotations

import logging
import webbrowser
from dataclasses import replace

from cta_client.connection import ServerConnection
from cta_client.credentials import CredentialStore
from cta_client.paths import client_config_dir
from cta_client.profiles import ClientConfig, ServerProfile, normalize_server_url
from cta_client.queue import UploadQueue
from cta_client.service import machine_payload
from cta_client.uploader import TelemetryClient


def connection_for(profile: ServerProfile, token: str) -> ServerConnection:
    return ServerConnection(
        profile,
        TelemetryClient(profile.url, token),
        UploadQueue(client_config_dir() / profile.queue_filename),
    )


def restore_connections(
    config: ClientConfig,
    credentials: CredentialStore,
) -> list[ServerConnection]:
    """Reconnect to every server whose token is still in the keyring.

    A profile without a token is skipped rather than dropped: the keyring
    can be locked or unavailable at startup, and forgetting the server
    because of that would be worse than reporting it as signed out.
    """
    connections = []
    for profile in config.servers:
        token = credentials.get_token(profile.url, profile.username)
        if token:
            connections.append(connection_for(profile, token))
        else:
            logging.info("No stored token for %s; sign-in required", profile.url)
    return connections


def sign_in(
    url: str,
    username: str,
    password: str,
    credentials: CredentialStore,
) -> ServerConnection:
    """Register this machine with a server and keep the token.

    Asks the server what group it is first, so the profile can be labelled
    with the group's own name rather than a URL.
    """
    url = normalize_server_url(url)
    client = TelemetryClient(url)
    try:
        info = client.server_info()
        client.login(username, password, machine_payload())
        token = client.token or ""
    finally:
        client.close()
    credentials.set_token(url, username, token)
    profile = ServerProfile(url=url, username=username, group_name=info.get("group_name", ""))
    return connection_for(profile, token)


def open_dashboard(connection: ServerConnection) -> bool:
    """Sign the tester's browser in to this server and show the dashboard.

    Fetched fresh every time because the ticket is single use and expires
    within the minute, which is what makes it safe to hand to a browser.
    """
    try:
        url = connection.client.web_handoff_url()
    except Exception as error:  # noqa: BLE001 - a dashboard is never worth a crash
        # The upload path is the client's actual job; failing to open a
        # browser tab must not take it down or interrupt a session.
        logging.warning("Could not open dashboard for %s: %s", connection.profile.url, error)
        return False
    return webbrowser.open(url)


def plant_dashboard_cookie(connection: ServerConnection, config: ClientConfig) -> bool:
    """Open the dashboard once per server, the first time we sign in.

    After this the server's sliding cookie keeps the browser signed in on
    its own, so the tester visits their dashboard normally and is simply
    already authenticated. Doing it again on every launch would mean an
    unexplained browser tab at every login, which is exactly the kind of
    thing this client is supposed to avoid.
    """
    if connection.profile.dashboard_opened:
        return False
    if not open_dashboard(connection):
        return False
    config.mark_dashboard_opened(connection.profile.url)
    connection.profile = replace(connection.profile, dashboard_opened=True)
    return True
