from __future__ import annotations

import argparse
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import QObject, QLockFile, QThread, Signal, Slot
from PySide6.QtGui import QAction, QCloseEvent, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFormLayout,
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

from cta_client.credentials import CredentialStore
from cta_client.desktop import autostart
from cta_client.paths import client_config_dir, client_log_dir, default_player_log_path, load_client_config, save_client_config
from cta_client.queue import UploadQueue
from cta_client.service import TelemetryService, diagnostics, machine_payload
from cta_client.uploader import AuthenticationRequired, TelemetryClient


DEFAULT_SERVER_URL = os.environ.get("CTA_DEFAULT_SERVER_URL", "")


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


class MainWindow(QMainWindow):
    def __init__(self, *, background: bool = False) -> None:
        super().__init__()
        self.setWindowTitle("MTGA Constructed Testing")
        self.resize(520, 390)
        self.credentials = CredentialStore()
        self.credentials.migrate_legacy_token()
        self.client: TelemetryClient | None = None
        self.service: TelemetryService | None = None
        self.thread: QThread | None = None
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.login_page = self._build_login()
        self.status_page = self._build_status()
        self.stack.addWidget(self.login_page)
        self.stack.addWidget(self.status_page)
        self._build_tray()
        self._restore_session()
        if background and self.service is not None:
            self.hide()

    def _build_login(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("<h1>Connect to your testing group</h1><p>Enter the account issued by your tournament administrator.</p>"))
        form = QFormLayout()
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Username", self.username)
        form.addRow("Password", self.password)
        layout.addLayout(form)
        advanced = QGroupBox("Advanced")
        advanced.setCheckable(True)
        advanced.setChecked(not bool(DEFAULT_SERVER_URL))
        advanced_layout = QFormLayout(advanced)
        self.server = QLineEdit(DEFAULT_SERVER_URL)
        self.log_path = QLineEdit(str(default_player_log_path()))
        advanced_layout.addRow("Server URL", self.server)
        advanced_layout.addRow("Arena log", self.log_path)
        layout.addWidget(advanced)
        connect = QPushButton("Sign in and start uploading")
        connect.clicked.connect(self._login)
        layout.addWidget(connect)
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
        sign_out = QPushButton("Sign out")
        sign_out.clicked.connect(self._sign_out)
        layout.addWidget(sign_out)
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
        self.tray.activated.connect(lambda reason: self._show() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        self.tray.show()

    def _restore_session(self) -> None:
        config = load_client_config()
        self.server.setText(config.get("server", DEFAULT_SERVER_URL))
        self.username.setText(config.get("username", ""))
        self.log_path.setText(config.get("log_path", str(default_player_log_path())))
        server, username = self.server.text().strip(), self.username.text().strip()
        token = self.credentials.get_token(server, username) if server and username else None
        if token:
            self._start(server, username, token)

    @Slot()
    def _login(self) -> None:
        server, username, password = self.server.text().strip(), self.username.text().strip(), self.password.text()
        if not server or not username or not password:
            QMessageBox.warning(self, "Missing information", "Enter server URL, username, and password.")
            return
        client = TelemetryClient(server)
        try:
            client.login(username, password, machine_payload())
        except AuthenticationRequired:
            QMessageBox.warning(self, "Sign-in failed", "The username or password was rejected.")
            client.close()
            return
        self.credentials.set_token(server, username, client.token or "")
        client.close()
        save_client_config({"server": server, "username": username, "log_path": self.log_path.text()})
        self.password.clear()
        self._start(server, username, self.credentials.get_token(server, username) or "")
        if not autostart.enabled():
            self.autostart.setChecked(True)

    def _start(self, server: str, username: str, token: str) -> None:
        self._stop_service()
        self.client = TelemetryClient(server, token)
        self.service = TelemetryService(
            self.client,
            __import__("pathlib").Path(self.log_path.text()),
            UploadQueue(client_config_dir() / "uploads.jsonl"),
            lambda *_: None,
        )
        worker = ServiceWorker(self.service)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.status.connect(self._status)
        worker.finished.connect(thread.quit)
        worker.finished.connect(self._authentication_ended)
        thread.finished.connect(worker.deleteLater)
        self._worker = worker
        self.thread = thread
        thread.start()
        self.stack.setCurrentWidget(self.status_page)

    @Slot(str, str)
    def _status(self, state: str, message: str) -> None:
        labels = {
            "uploading": "Uploading",
            "waiting": "Waiting for Arena",
            "reconnecting": "Reconnecting",
            "paused": "Paused",
            "authentication": "Sign-in required",
        }
        self.state.setText(labels.get(state, state.title()))
        self.detail.setText(message)

    @Slot()
    def _authentication_ended(self) -> None:
        if self.state.text() == "Sign-in required":
            self.stack.setCurrentWidget(self.login_page)
            self.show()

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

    @Slot()
    def _sign_out(self) -> None:
        config = load_client_config()
        if config.get("server") and config.get("username"):
            self.credentials.delete_token(config["server"], config["username"])
        self._stop_service()
        self.stack.setCurrentWidget(self.login_page)
        self.show()

    def _stop_service(self) -> None:
        if self.service:
            self.service.stop()
        if self.thread:
            self.thread.quit()
            self.thread.wait(3000)
        if self.client:
            self.client.close()
        self.service = self.client = self.thread = None

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
