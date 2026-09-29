"""Named lock plus local IPC so a newer client can replace an older one.

The lock file is the same ``client.lock`` previous builds already took.
Those builds just exited when it was held, which is why extracting 0.3.5
left a 0.3.2 tray reporting in. This process asks the holder to quit when
we are newer, and kills that pid if it ignores us. An older challenger
exits instead of fighting.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import signal
import socket
import sys
import time

from PySide6.QtCore import QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from cta_client.instance import (
    ACTION_FOCUS,
    ACTION_TAKEOVER,
    decode_message,
    encode_message,
    takeover_action,
)
from cta_client.paths import APP_ID, client_config_dir

PROBE_MS = 400
QUIT_WAIT_MS = 4_000
KILL_WAIT_S = 4.0


class InstanceClaim(QObject):
    show_requested = Signal()
    quit_requested = Signal()

    def __init__(self, lock: QLockFile, version: str) -> None:
        super().__init__()
        self.lock = lock
        self.version = version
        self._buffers: dict[int, bytes] = {}
        self._sockets: list[QLocalSocket] = []
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._accept)
        QLocalServer.removeServer(_socket_name())
        if not self.server.listen(_socket_name()):
            logging.warning("Could not listen for other client instances")

    def release(self) -> None:
        self.server.close()
        QLocalServer.removeServer(_socket_name())
        self.lock.unlock()

    def _accept(self) -> None:
        sock = self.server.nextPendingConnection()
        if sock is None:
            return
        self._sockets.append(sock)
        sock.readyRead.connect(lambda: self._read(sock))
        sock.disconnected.connect(lambda: self._drop(sock))

    def _read(self, sock: QLocalSocket) -> None:
        key = id(sock)
        self._buffers[key] = self._buffers.get(key, b"") + bytes(sock.readAll().data())
        while b"\n" in self._buffers[key]:
            line, self._buffers[key] = self._buffers[key].split(b"\n", 1)
            if not line.strip():
                continue
            if not line.lstrip().startswith(b"{"):
                continue
            try:
                payload = decode_message(line)
            except (ValueError, json.JSONDecodeError):
                continue
            reply = self._handle(payload)
            sock.write(encode_message(reply))
            sock.flush()

    def _handle(self, payload: dict) -> dict:
        cmd = str(payload.get("cmd") or "")
        if cmd == "probe":
            return {"version": self.version}
        if cmd == "show":
            self.show_requested.emit()
            return {"ok": True}
        if cmd == "quit":
            incoming = str(payload.get("version") or "")
            if takeover_action(incoming, self.version) == ACTION_TAKEOVER:
                self.quit_requested.emit()
                return {"ok": True}
            return {"ok": False, "version": self.version}
        return {"ok": False}

    def _drop(self, sock: QLocalSocket) -> None:
        self._buffers.pop(id(sock), None)
        if sock in self._sockets:
            self._sockets.remove(sock)
        sock.deleteLater()


def claim_instance(version: str) -> InstanceClaim | None:
    """Take the single-instance lock, or step aside / take over as needed.

    Returns a claim this process must hold until exit, or None when this
    process should not keep running.
    """
    lock_path = client_config_dir() / "client.lock"
    lock = QLockFile(str(lock_path))
    lock.setStaleLockTime(10_000)
    if lock.tryLock(100):
        return InstanceClaim(lock, version)
    their_version = _probe_peer()
    action = takeover_action(version, their_version)
    if action == ACTION_FOCUS:
        _send_peer({"cmd": "show"})
        return None
    if action != ACTION_TAKEOVER:
        return None
    logging.info(
        "Taking over from %s",
        their_version or "a client with no instance protocol",
    )
    if their_version is not None:
        _send_peer({"cmd": "quit", "version": version})
        if lock.tryLock(QUIT_WAIT_MS):
            return InstanceClaim(lock, version)
    pid, hostname, _app = lock.getLockInfo()
    if pid and pid != os.getpid() and _local_holder(hostname):
        _terminate_pid(int(pid))
    lock.removeStaleLockFile()
    if lock.tryLock(2_000):
        return InstanceClaim(lock, version)
    logging.error("Could not take client.lock after stopping the previous instance")
    return None


def _socket_name() -> str:
    digest = hashlib.sha1(str(client_config_dir()).encode("utf-8")).hexdigest()[:12]
    return f"{APP_ID}-{digest}"


def _probe_peer() -> str | None:
    payload = _send_peer({"cmd": "probe"})
    if payload is None:
        return None
    version = str(payload.get("version") or "").strip()
    return version or None


def _send_peer(payload: dict) -> dict | None:
    sock = QLocalSocket()
    sock.connectToServer(_socket_name())
    if not sock.waitForConnected(PROBE_MS):
        return None
    sock.write(encode_message(payload))
    sock.flush()
    if not sock.waitForReadyRead(PROBE_MS):
        sock.disconnectFromServer()
        return None
    line = bytes(sock.readLine().data()).strip()
    sock.disconnectFromServer()
    if not line:
        return None
    try:
        return decode_message(line)
    except (ValueError, json.JSONDecodeError):
        return None


def _local_holder(hostname: str) -> bool:
    if not hostname:
        return True
    return hostname.split(".")[0] == socket.gethostname().split(".")[0]


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _terminate_pid(pid: int) -> None:
    """Ask the lock holder to exit, then kill it if it ignores us.

    The pid comes from our own lock file, not from matching command lines,
    so this will not sweep up unrelated Python processes.
    """
    if pid == os.getpid() or not _pid_alive(pid):
        return
    logging.info("Stopping leftover client pid %s", pid)
    if sys.platform == "win32":
        import subprocess

        subprocess.run(["taskkill", "/PID", str(pid)], check=False, capture_output=True)
        _wait_until_dead(pid)
        if _pid_alive(pid):
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                check=False,
                capture_output=True,
            )
        return
    os.kill(pid, signal.SIGTERM)
    _wait_until_dead(pid)
    if _pid_alive(pid):
        os.kill(pid, signal.SIGKILL)
        _wait_until_dead(pid)


def _wait_until_dead(pid: int, timeout: float = KILL_WAIT_S) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and _pid_alive(pid):
        time.sleep(0.1)
