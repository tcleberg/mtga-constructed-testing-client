from __future__ import annotations

import argparse
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QObject, QLockFile, QThread, Signal, Slot
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStyle,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from cta_client.connection import ServerConnection
from cta_client.credentials import CredentialStore
from cta_client.desktop import autostart
from cta_client.paths import client_config_dir, client_log_dir, default_player_log_path
from cta_client.profiles import load_config, save_config
from cta_client.service import ConnectionStatus, TelemetryService, diagnostics
from cta_client.session import (
    open_dashboard,
    plant_dashboard_cookie,
    restore_connections,
    sign_in,
)
from cta_client.uploader import AuthenticationRequired, IncompatibleServer

DEFAULT_SERVER_URL = os.environ.get("CTA_DEFAULT_SERVER_URL", "")

STATE_LABELS = {
    "uploading": "Uploading",
    "waiting": "Waiting for Arena",
    "reconnecting": "Reconnecting",
    "degraded": "Uploading",
    "authentication": "Sign-in required",
    "paused": "Paused",
    "idle": "No groups connected",
    "starting": "Starting…",
}


class ServiceWorker(QObject):
    status = Signal(str, str)
    finished = Signal()

    def __init__(self, service: TelemetryService) -> None:
        super().__init__()
        self.service = service

    @Slot()
    def run(self) -> None:
        self.service.status = self.status.emit
        self.service.run()
        self.finished.emit()


class SignInWorker(QObject):
    """Signing in off the GUI thread.

    A server can take several seconds to answer, and a window that stops
    repainting while it does looks like a crash.
    """

    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, url: str, username: str, password: str, credentials: CredentialStore) -> None:
        super().__init__()
        self.url = url
        self.username = username
        self.password = password
        self.credentials = credentials

    @Slot()
    def run(self) -> None:
        try:
            connection = sign_in(self.url, self.username, self.password, self.credentials)
        except AuthenticationRequired:
            self.failed.emit("The username or password was rejected.")
        except IncompatibleServer as error:
            self.failed.emit(str(error))
        except Exception as error:  # noqa: BLE001 - the message is the whole point
            self.failed.emit(f"Could not reach that server.\n\n{type(error).__name__}: {error}")
        else:
            self.succeeded.emit(connection)


class ServerRow(QFrame):
    """One group's line in the status list."""

    def __init__(self, url: str, window: MainWindow) -> None:
        super().__init__()
        self.url = url
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        self.title = QLabel()
        self.title.setStyleSheet("font-weight: 600")
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet("color: palette(mid)")
        layout.addWidget(self.title)
        layout.addWidget(self.detail)
        buttons = QHBoxLayout()
        self.dashboard = QPushButton("Open dashboard")
        self.dashboard.clicked.connect(lambda: window.open_dashboard(url))
        self.resign = QPushButton("Sign in")
        self.resign.clicked.connect(lambda: window.prompt_sign_in(url))
        remove = QPushButton("Remove")
        remove.clicked.connect(lambda: window.remove_server(url))
        buttons.addWidget(self.dashboard)
        buttons.addWidget(self.resign)
        buttons.addWidget(remove)
        buttons.addStretch()
        layout.addLayout(buttons)

    def update_status(self, status: ConnectionStatus) -> None:
        self.title.setText(f"{status.label} — {status.username}")
        self.detail.setText(status.detail or STATE_LABELS.get(status.state, status.state))
        self.resign.setVisible(status.state == "authentication")
        self.dashboard.setEnabled(status.state != "authentication")


class MainWindow(QMainWindow):
    def __init__(self, *, background: bool = False) -> None:
        super().__init__()
        self.setWindowTitle("MTGA Constructed Testing")
        self.resize(560, 480)
        self.credentials = CredentialStore()
        self.credentials.migrate_legacy_token()
        self.config = load_config()
        self.service: TelemetryService | None = None
        self.thread: QThread | None = None
        self.rows: dict[str, ServerRow] = {}
        self.sign_in_thread: QThread | None = None
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.add_page = self._build_add_page()
        self.status_page = self._build_status()
        self.stack.addWidget(self.add_page)
        self.stack.addWidget(self.status_page)
        self._build_tray()
        self._restore()
        if background and self.service is not None:
            self.hide()

    # Pages -----------------------------------------------------------

    def _build_add_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.add_heading = QLabel(
            "<h1>Connect to your testing group</h1>"
            "<p>Enter the account issued by your tournament administrator.</p>"
        )
        self.add_heading.setWordWrap(True)
        layout.addWidget(self.add_heading)
        form = QFormLayout()
        self.server = QLineEdit(DEFAULT_SERVER_URL)
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.returnPressed.connect(self._submit_sign_in)
        form.addRow("Group server", self.server)
        form.addRow("Username", self.username)
        form.addRow("Password", self.password)
        layout.addLayout(form)
        advanced = QGroupBox("Advanced")
        advanced.setCheckable(True)
        advanced.setChecked(False)
        advanced_layout = QFormLayout(advanced)
        self.log_path = QLineEdit(self.config.log_path or str(default_player_log_path()))
        advanced_layout.addRow("Arena log", self.log_path)
        layout.addWidget(advanced)
        self.add_error = QLabel()
        self.add_error.setWordWrap(True)
        self.add_error.setStyleSheet("color: #b3261e")
        layout.addWidget(self.add_error)
        actions = QHBoxLayout()
        self.connect_button = QPushButton("Sign in and start uploading")
        self.connect_button.clicked.connect(self._submit_sign_in)
        self.cancel_add = QPushButton("Cancel")
        self.cancel_add.clicked.connect(lambda: self.stack.setCurrentWidget(self.status_page))
        actions.addWidget(self.connect_button)
        actions.addWidget(self.cancel_add)
        layout.addLayout(actions)
        layout.addStretch()
        return page

    def _build_status(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("<h1>MTGA Constructed Testing</h1>"))
        self.state = QLabel("Starting…")
        self.state.setStyleSheet("font-size: 20px; font-weight: 600")
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        layout.addWidget(self.state)
        layout.addWidget(self.detail)
        self.server_list = QVBoxLayout()
        layout.addLayout(self.server_list)
        add = QPushButton("Add another group")
        add.clicked.connect(lambda: self.prompt_sign_in(None))
        layout.addWidget(add)
        self.autostart = QCheckBox("Start automatically when I sign in")
        self.autostart.setChecked(autostart.enabled())
        self.autostart.toggled.connect(autostart.set_enabled)
        layout.addWidget(self.autostart)
        buttons = QHBoxLayout()
        self.pause = QPushButton("Pause")
        self.pause.setCheckable(True)
        self.pause.toggled.connect(self._pause)
        diagnostics_button = QPushButton("Copy diagnostics")
        diagnostics_button.clicked.connect(self._copy_diagnostics)
        buttons.addWidget(self.pause)
        buttons.addWidget(diagnostics_button)
        layout.addLayout(buttons)
        layout.addStretch()
        return page

    def _build_tray(self) -> None:
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self.setWindowIcon(icon)
        self.tray = QSystemTrayIcon(icon, self)
        menu = QMenu()
        show = QAction("Open status", self)
        show.triggered.connect(self._show)
        self.tray_pause = QAction("Pause uploading", self)
        self.tray_pause.setCheckable(True)
        self.tray_pause.toggled.connect(self._pause)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(show)
        menu.addAction(self.tray_pause)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self._show()
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick
            else None
        )
        self.tray.show()

    # Lifecycle -------------------------------------------------------

    def _restore(self) -> None:
        connections = restore_connections(self.config, self.credentials)
        if not connections:
            self.cancel_add.setVisible(False)
            self.stack.setCurrentWidget(self.add_page)
            return
        self._start(connections)
        for connection in connections:
            # Catches installs that predate the handoff, and any group
            # added before the browser was ever signed in.
            if plant_dashboard_cookie(connection, self.config):
                save_config(self.config)

    def _start(self, connections: list[ServerConnection]) -> None:
        self.service = TelemetryService(
            connections,
            Path(self.config.log_path or str(default_player_log_path())),
            lambda *_: None,
        )
        worker = ServiceWorker(self.service)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.status.connect(self._status)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        self._worker = worker
        self.thread = thread
        thread.start()
        self._refresh_rows()
        self.stack.setCurrentWidget(self.status_page)

    # Sign-in ---------------------------------------------------------

    @Slot()
    def prompt_sign_in(self, url: str | None = None) -> None:
        """Show the add page, either blank or aimed at a known group."""
        profile = self.config.find(url) if url else None
        self.add_heading.setText(
            f"<h1>Sign in to {profile.label}</h1><p>Your session expired or was ended.</p>"
            if profile
            else "<h1>Connect to a testing group</h1>"
            "<p>Enter the account issued by that group's administrator.</p>"
        )
        self.server.setText(profile.url if profile else DEFAULT_SERVER_URL)
        self.username.setText(profile.username if profile else "")
        self.password.clear()
        self.add_error.clear()
        self.cancel_add.setVisible(bool(self.config.servers))
        self.stack.setCurrentWidget(self.add_page)
        self.password.setFocus() if profile else self.server.setFocus()

    @Slot()
    def _submit_sign_in(self) -> None:
        url, username, password = (
            self.server.text().strip(),
            self.username.text().strip(),
            self.password.text(),
        )
        if not url or not username or not password:
            self.add_error.setText("Enter the group server, username, and password.")
            return
        self.config.log_path = self.log_path.text().strip() or str(default_player_log_path())
        self.connect_button.setEnabled(False)
        self.connect_button.setText("Connecting…")
        self.add_error.clear()
        worker = SignInWorker(url, username, password, self.credentials)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._sign_in_succeeded)
        worker.failed.connect(self._sign_in_failed)
        worker.succeeded.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        self._sign_in_worker = worker
        self.sign_in_thread = thread
        thread.start()

    @Slot(object)
    def _sign_in_succeeded(self, connection: ServerConnection) -> None:
        self._reset_sign_in_button()
        self.password.clear()
        replaced = self.service.remove_connection(connection.profile.url) if self.service else None
        if replaced is not None:
            replaced.close()
        self.config.upsert(connection.profile)
        save_config(self.config)
        if self.service is None:
            self._start([connection])
        else:
            self.service.add_connection(connection)
            self._refresh_rows()
            self.stack.setCurrentWidget(self.status_page)
        if plant_dashboard_cookie(connection, self.config):
            save_config(self.config)
        if not autostart.enabled():
            self.autostart.setChecked(True)

    @Slot(str)
    def _sign_in_failed(self, message: str) -> None:
        self._reset_sign_in_button()
        self.add_error.setText(message)

    def _reset_sign_in_button(self) -> None:
        self.connect_button.setEnabled(True)
        self.connect_button.setText("Sign in and start uploading")

    # Per-server actions ----------------------------------------------

    @Slot()
    def open_dashboard(self, url: str) -> None:
        connection = self._connection(url)
        if connection is None:
            return
        if not open_dashboard(connection):
            self.detail.setText(f"Could not open the dashboard for {connection.profile.label}.")

    @Slot()
    def remove_server(self, url: str) -> None:
        profile = self.config.find(url)
        if profile is None:
            return
        if QMessageBox.question(
            self,
            "Remove group",
            f"Stop uploading to {profile.label}?\n\n"
            "Matches already uploaded stay with that group.",
        ) != QMessageBox.StandardButton.Yes:
            return
        connection = self.service.remove_connection(url) if self.service else None
        if connection is not None:
            connection.close()
            connection.queue.path.unlink(missing_ok=True)
        self.credentials.delete_token(profile.url, profile.username)
        self.config.remove(url)
        save_config(self.config)
        self._refresh_rows()
        if not self.config.servers:
            self._stop_service()
            self.prompt_sign_in(None)

    def _connection(self, url: str) -> ServerConnection | None:
        if self.service is None:
            return None
        return next((c for c in self.service.connections if c.profile.url == url), None)

    # Status ----------------------------------------------------------

    @Slot(str, str)
    def _status(self, state: str, message: str) -> None:
        self.state.setText(STATE_LABELS.get(state, state.title()))
        self.detail.setText(message)
        self._refresh_rows()

    def _refresh_rows(self) -> None:
        """Keep one row per group, updating in place.

        Rebuilding the list on every status tick would destroy whichever
        button the tester was reaching for, so widgets are only created
        and removed when the set of groups actually changes.
        """
        statuses = self.service.snapshot() if self.service else []
        seen = {status.url for status in statuses}
        for url in list(self.rows):
            if url not in seen:
                row = self.rows.pop(url)
                self.server_list.removeWidget(row)
                row.deleteLater()
        for status in statuses:
            row = self.rows.get(status.url)
            if row is None:
                row = ServerRow(status.url, self)
                self.rows[status.url] = row
                self.server_list.addWidget(row)
            row.update_status(status)

    @Slot(bool)
    def _pause(self, paused: bool) -> None:
        if self.service:
            self.service.set_paused(paused)
        self.pause.setChecked(paused)
        self.tray_pause.setChecked(paused)

    @Slot()
    def _copy_diagnostics(self) -> None:
        if self.service:
            QApplication.clipboard().setText(diagnostics(self.service))
            self.detail.setText("Diagnostics copied to clipboard.")

    def _stop_service(self) -> None:
        if self.service:
            self.service.stop()
            for connection in self.service.connections:
                connection.close()
        if self.thread:
            self.thread.quit()
            self.thread.wait(3000)
        self.service = self.thread = None

    def _show(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event: QCloseEvent) -> None:
        event.ignore()
        self.hide()
        self.tray.showMessage("MTGA Constructed Testing", "Still uploading in the background.")


def configure_logging() -> None:
    handler = RotatingFileHandler(client_log_dir() / "client.log", maxBytes=2_000_000, backupCount=5)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--background", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        client_config_dir()
        default_player_log_path()
        return 0
    configure_logging()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("MTGA Constructed Testing")
    app.setQuitOnLastWindowClosed(False)
    lock = QLockFile(str(client_config_dir() / "client.lock"))
    lock.setStaleLockTime(10_000)
    if not lock.tryLock(100):
        return 0
    window = MainWindow(background=args.background)
    if not args.background or window.service is None:
        window.show()
    result = app.exec()
    window._stop_service()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
