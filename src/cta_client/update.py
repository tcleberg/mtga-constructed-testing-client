"""Whether the running build is behind the cut a server is advertising."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from cta_client import __version__


def parse_version(value: str) -> tuple[int, ...]:
    value = value.strip().lstrip("vV")
    parts: list[int] = []
    for piece in value.split("."):
        digits = ""
        for char in piece:
            if char.isdigit():
                digits += char
            else:
                break
        parts.append(int(digits) if digits else 0)
    return tuple(parts) if parts else (0,)


def is_newer(candidate: str, current: str) -> bool:
    left = parse_version(candidate)
    right = parse_version(current)
    width = max(len(left), len(right))
    left += (0,) * (width - len(left))
    right += (0,) * (width - len(right))
    return left > right


def advertised_update(
    payload: dict[str, Any], current: str | None = None
) -> tuple[str, str] | None:
    """Return (version, url) when the payload names a cut ahead of this build."""
    running = __version__ if current is None else current
    latest = str(payload.get("latest_client_version") or "").strip()
    url = str(payload.get("client_release_url") or "").strip()
    if not latest or not url:
        return None
    if not is_newer(latest, running):
        return None
    return latest, url


def pending_update(
    advertised: Iterable[tuple[str, str]],
    current: str,
    dismissed: str = "",
) -> tuple[str, str] | None:
    """Newest advertised cut that is ahead of both this build and a dismissal."""
    best: tuple[str, str] | None = None
    for version, url in advertised:
        if not version or not url:
            continue
        if not is_newer(version, current):
            continue
        if dismissed and not is_newer(version, dismissed):
            continue
        if best is None or is_newer(version, best[0]):
            best = (version, url)
    return best
