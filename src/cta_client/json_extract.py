from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any


HEADER_RE = re.compile(r"^\[(UnityCrossThreadLogger|Client GRE)\]")
REQUEST_RE = re.compile(r"(?:^\[(?:UnityCrossThreadLogger|Client GRE)\].*)?==>\s+(\S+)")
RESPONSE_RE = re.compile(r"^<==\s+(\S+)")
TIMESTAMP_RE = re.compile(
    r"^\[(?:UnityCrossThreadLogger|Client GRE)\](\d{1,2}/\d{1,2}/\d{4} "
    r"\d{1,2}:\d{2}:\d{2}(?:\.\d+)? [AP]M)"
)


@dataclass(frozen=True)
class LogEntry:
    raw: str
    json_objects: tuple[dict[str, Any], ...]
    api_name: str | None = None
    direction: str | None = None
    timestamp: datetime | None = None


def extract_json_objects(text: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    i = 0
    while i < len(text):
        if text[i] != "{":
            i += 1
            continue
        depth = 0
        in_string = False
        escape = False
        start = i
        while i < len(text):
            ch = text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
            else:
                if ch == '"':
                    in_string = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        blob = text[start : i + 1]
                        try:
                            parsed = json.loads(blob)
                        except json.JSONDecodeError:
                            break
                        if isinstance(parsed, dict):
                            objects.append(_maybe_unescape_nested(parsed))
                        i += 1
                        break
            i += 1
        else:
            break
    return objects


def _maybe_unescape_nested(obj: dict[str, Any]) -> dict[str, Any]:
    for key in ("request", "Payload", "payload"):
        value = obj.get(key)
        if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
            try:
                obj[key] = json.loads(value)
            except json.JSONDecodeError:
                pass
    return obj


def iter_log_entries(text: str) -> Iterator[LogEntry]:
    buffer: list[str] = []
    api_name: str | None = None
    direction: str | None = None

    def flush() -> LogEntry | None:
        nonlocal api_name, direction
        if not buffer:
            return None
        raw = "\n".join(buffer)
        timestamp = None
        match = TIMESTAMP_RE.match(buffer[0])
        if match:
            timestamp = datetime.strptime(match.group(1).split(".")[0], "%m/%d/%Y %I:%M:%S %p")
        entry = LogEntry(raw, tuple(extract_json_objects(raw)), api_name, direction, timestamp)
        buffer.clear()
        api_name = None
        direction = None
        return entry

    for line in text.splitlines():
        if HEADER_RE.match(line) or line.startswith("<=="):
            finished = flush()
            if finished:
                yield finished
            buffer.append(line)
            request = REQUEST_RE.search(line)
            response = RESPONSE_RE.search(line)
            if request:
                api_name, direction = request.group(1), "request"
            elif response:
                api_name, direction = response.group(1).split("(")[0], "response"
        elif buffer:
            buffer.append(line)
            request = REQUEST_RE.search(line)
            if request:
                api_name, direction = request.group(1), "request"
    finished = flush()
    if finished:
        yield finished
from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

HEADER_RE = re.compile(r"^\[(UnityCrossThreadLogger|Client GRE)\]")
REQUEST_RE = re.compile(r"(?:^\[(?:UnityCrossThreadLogger|Client GRE)\].*)?==>\s+(\S+)")
RESPONSE_RE = re.compile(r"^<==\s+(\S+)")
TIMESTAMP_RE = re.compile(
    r"^\[(?:UnityCrossThreadLogger|Client GRE)\](\d{1,2}/\d{1,2}/\d{4} "
    r"\d{1,2}:\d{2}:\d{2}(?:\.\d+)? [AP]M)"
)


@dataclass(frozen=True)
class LogEntry:
    raw: str
    json_objects: tuple[dict[str, Any], ...]
    api_name: str | None = None
    direction: str | None = None
    timestamp: datetime | None = None


def extract_json_objects(text: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        depth = 0
        in_string = False
        escape = False
        start = i
        while i < n:
            ch = text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
            else:
                if ch == '"':
                    in_string = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        blob = text[start : i + 1]
                        try:
                            parsed = json.loads(blob)
                        except json.JSONDecodeError:
                            break
                        if isinstance(parsed, dict):
                            objects.append(_maybe_unescape_nested(parsed))
                        i += 1
                        break
            i += 1
        else:
            break
    return objects


def _maybe_unescape_nested(obj: dict[str, Any]) -> dict[str, Any]:
    for key in ("request", "Payload", "payload"):
        value = obj.get(key)
        if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
            try:
                obj[key] = json.loads(value)
            except json.JSONDecodeError:
                pass
    return obj


def iter_log_entries(text: str) -> Iterator[LogEntry]:
    buffer: list[str] = []
    api_name: str | None = None
    direction: str | None = None

    def flush() -> LogEntry | None:
        nonlocal api_name, direction
        if not buffer:
            return None
        raw = "\n".join(buffer)
        timestamp = None
        match = TIMESTAMP_RE.match(buffer[0])
        if match:
            timestamp = datetime.strptime(
                match.group(1).split(".")[0],
                "%m/%d/%Y %I:%M:%S %p",
            )
        entry = LogEntry(
            raw=raw,
            json_objects=tuple(extract_json_objects(raw)),
            api_name=api_name,
            direction=direction,
            timestamp=timestamp,
        )
        buffer.clear()
        api_name = None
        direction = None
        return entry

    for line in text.splitlines():
        if HEADER_RE.match(line) or line.startswith("<=="):
            finished = flush()
            if finished:
                yield finished
            buffer.append(line)
            request = REQUEST_RE.search(line)
            response = RESPONSE_RE.search(line)
            if request:
                api_name = request.group(1)
                direction = "request"
            elif response:
                api_name = response.group(1).split("(")[0]
                direction = "response"
        else:
            if buffer:
                buffer.append(line)
                request = REQUEST_RE.search(line)
                if request:
                    api_name = request.group(1)
                    direction = "request"
    finished = flush()
    if finished:
        yield finished
