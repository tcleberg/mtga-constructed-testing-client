"""Single-instance takeover, without Qt.

The desktop shell already uses a named lock. This module is the version
comparison that lock consults so a newer extract can replace a leftover
tray, and an older one will not kill a newer process that already won.
"""

from __future__ import annotations

import json

from cta_client.update import is_newer

ACTION_TAKEOVER = "takeover"
ACTION_YIELD = "yield"
ACTION_FOCUS = "focus"


def takeover_action(our_version: str, their_version: str | None) -> str:
    """What this process should do about another instance of the app.

    Versions are the same string the client POSTs as ``client_version``.
    ``their_version`` is None when the peer does not speak this protocol,
    which is every build from before takeover existed. Those leftover
    trays are older by definition, so a 0.3.5 extract can replace 0.3.2
    instead of exiting and leaving the old process reporting in.
    """
    theirs = (their_version or "").strip() or None
    if theirs is None or is_newer(our_version, theirs):
        return ACTION_TAKEOVER
    if is_newer(theirs, our_version):
        return ACTION_YIELD
    return ACTION_FOCUS


def encode_message(payload: dict) -> bytes:
    return (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")


def decode_message(line: bytes | str) -> dict:
    text = line.decode("utf-8") if isinstance(line, bytes) else line
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("instance message must be an object")
    return payload
