"""Canonical constructed formats, mapped from Arena's declared Format field.

Arena names the queue separately (EventName / InternalEventName /
gameRoomConfig.eventId). Format lives on the deck/course Attributes list
as {"name":"Format","value":"Standard"}. Traditional_Ladder is a queue.
"""

from __future__ import annotations

from typing import Any

FORMAT_SLUGS: tuple[str, ...] = (
    "standard",
    "legacy",
    "modern",
    "vintage",
    "historic",
    "pioneer",
    "premodern",
    "timeless",
)

# Arena Format attribute values that name one of the eight constructed
# formats. Explorer is Arena's name for Pioneer-legal constructed.
_ALIASES = {
    "standard": "standard",
    "traditionalstandard": "standard",
    "legacy": "legacy",
    "modern": "modern",
    "vintage": "vintage",
    "historic": "historic",
    "traditionalhistoric": "historic",
    "pioneer": "pioneer",
    "explorer": "pioneer",
    "traditionalexplorer": "pioneer",
    "premodern": "premodern",
    "timeless": "timeless",
    "traditionaltimeless": "timeless",
}

# Longer tokens first so premodern does not become modern.
_EVENT_FORMAT_TOKENS: tuple[tuple[str, str], ...] = (
    ("premodern", "premodern"),
    ("traditionaltimeless", "timeless"),
    ("traditionalhistoric", "historic"),
    ("traditionalexplorer", "pioneer"),
    ("traditionalstandard", "standard"),
    ("timeless", "timeless"),
    ("historic", "historic"),
    ("explorer", "pioneer"),
    ("pioneer", "pioneer"),
    ("vintage", "vintage"),
    ("modern", "modern"),
    ("legacy", "legacy"),
    ("standard", "standard"),
)
_NOT_CONSTRUCTED = ("brawl", "alchemy", "draft", "sealed")


def canonical_format(value: str | None) -> str | None:
    if value is None:
        return None
    compact = value.strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    if not compact:
        return None
    return _ALIASES.get(compact)


def format_from_event_name(event_name: str | None) -> str | None:
    """Read a constructed format token out of an event id, if one is there."""
    if not event_name or not str(event_name).strip():
        return None
    compact = event_name.strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    if any(token in compact for token in _NOT_CONSTRUCTED):
        return None
    for token, slug in _EVENT_FORMAT_TOKENS:
        if token in compact:
            return slug
    return None


def best_of_from_win_condition(value: str | None) -> int | None:
    """Arena gameInfo.matchWinCondition. Preferred over the queue name."""
    if not value:
        return None
    text = value.lower().replace(" ", "").replace("_", "")
    if "best2of3" in text or "bestof3" in text:
        return 3
    if "singleelimination" in text or "best1of1" in text or "bestof1" in text:
        return 1
    return None


def best_of_from_event_name(event_name: str | None) -> int | None:
    """Traditional / Bo3 names are Bo3. Any other named queue is Bo1."""
    if not event_name or not str(event_name).strip():
        return None
    compact = event_name.lower().replace(" ", "").replace("_", "").replace("-", "")
    if "traditional" in compact or "bestof3" in compact or "bo3" in compact:
        return 3
    if "bestof1" in compact or "bo1" in compact or "b01" in compact:
        return 1
    return 1


def format_from_attributes(container: Any) -> str | None:
    """Read Attributes[{"name":"Format","value":...}] from a deck or course."""
    if not isinstance(container, dict):
        return None
    for candidate in (
        container.get("Summary"),
        container.get("CourseDeckSummary"),
        container.get("DeckSummary"),
        container,
    ):
        if not isinstance(candidate, dict):
            continue
        attrs = candidate.get("Attributes") or candidate.get("attributes")
        if not isinstance(attrs, list):
            continue
        for item in attrs:
            if isinstance(item, dict) and item.get("name") == "Format":
                found = canonical_format(item.get("value") if isinstance(item.get("value"), str) else None)
                if found is not None:
                    return found
    return None
