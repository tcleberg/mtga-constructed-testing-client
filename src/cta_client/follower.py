from __future__ import annotations

import argparse
from pathlib import Path

from cta_client.credentials import CredentialStore
from cta_client.paths import resolve_player_log_path
from cta_client.profiles import load_config, normalize_server_url, save_config
from cta_client.service import TelemetryService
from cta_client.session import restore_connections, sign_in


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Upload Arena logs to your testing group servers")
    parser.add_argument("--server", help="add or sign in to this server")
    parser.add_argument("--username")
    parser.add_argument("--password", default=None)
    parser.add_argument("--log-path", type=Path, default=None)
    args = parser.parse_args(argv)

    credentials = CredentialStore()
    credentials.migrate_legacy_token()
    config = load_config()

    if args.password:
        if not args.server or not args.username:
            parser.error("--server and --username are required with --password")
        connection = sign_in(args.server, args.username, args.password, credentials)
        config.upsert(connection.profile)
        save_config(config)
    elif args.server and args.username:
        # Naming a server without a password means "use the saved token",
        # which lets a scripted run target one group out of several.
        config.servers = [
            server
            for server in config.servers
            if server.url == normalize_server_url(args.server) and server.username == args.username
        ]
        if not config.servers:
            parser.error("that server and username have not been signed in; pass --password")

    connections = restore_connections(config, credentials)
    if not connections:
        parser.error("no servers signed in; pass --server, --username, and --password")

    service = TelemetryService(
        connections,
        Path(args.log_path).expanduser()
        if args.log_path
        else resolve_player_log_path(config.log_path),
        lambda state, message: print(f"{state}: {message}"),
    )
    try:
        service.run()
    except KeyboardInterrupt:
        service.stop()
    finally:
        for connection in connections:
            connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
