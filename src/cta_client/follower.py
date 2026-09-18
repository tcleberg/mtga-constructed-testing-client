from __future__ import annotations

import argparse
from pathlib import Path

from cta_client.credentials import CredentialStore
from cta_client.paths import client_config_dir, default_player_log_path, load_client_config, save_client_config
from cta_client.queue import UploadQueue
from cta_client.service import TelemetryService, machine_payload
from cta_client.uploader import TelemetryClient


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Upload Arena logs to the tournament server")
    parser.add_argument("--server")
    parser.add_argument("--username")
    parser.add_argument("--password", default=None)
    parser.add_argument("--log-path", type=Path, default=None)
    args = parser.parse_args(argv)
    config = load_client_config()
    server = args.server or config.get("server")
    username = args.username or config.get("username")
    if not server or not username:
        parser.error("--server and --username are required on first run")
    credentials = CredentialStore()
    credentials.migrate_legacy_token()
    client = TelemetryClient(server, credentials.get_token(server, username))
    if args.password:
        client.login(username, args.password, machine_payload())
        credentials.set_token(server, username, client.token or "")
        save_client_config({"server": server, "username": username})
    service = TelemetryService(
        client,
        args.log_path or default_player_log_path(),
        UploadQueue(client_config_dir() / "uploads.jsonl"),
        lambda state, message: print(f"{state}: {message}"),
    )
    try:
        service.run()
    except KeyboardInterrupt:
        service.stop()
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
