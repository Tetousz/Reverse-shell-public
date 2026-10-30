"""Singleton AppState — owns Server, SessionManager, ExportManager.

Wires the Server's callbacks to the event bus so the browser gets
pushed updates (session list, logs, token rotations) without polling.
"""

import threading
from pathlib import Path

from web.stream import get_bus

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class AppState:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._init()
                cls._instance = inst
            return cls._instance

    def _init(self):
        from core.config import Config
        from core.server_state import ServerState
        from core.session_manager import SessionManager
        from modules.server import Server
        from exporter.export_manager import ExportManager

        self.config = Config()
        self.server_state = ServerState(migration_secret=self.config.auth_secret)
        self.sessions = SessionManager()
        self.server = Server(
            host=self.config.host,
            port=self.config.port,
            server_state=self.server_state,
            rotation_seconds=self.config.rotation_seconds,
            grace_windows=self.config.grace_windows,
            session_manager=self.sessions,
        )
        self.exporter = ExportManager()
        self._wire_server()

    # ---- callback wiring ------------------------------------------------

    def _wire_server(self):
        bus = get_bus()

        def on_log(msg, tag):
            bus.publish("log", {"msg": msg, "tag": tag or "info"})

        def on_connected(session):
            bus.publish("session_add", self._session_dict(session))
            bus.publish("log", {
                "msg": f"[+] Session #{session.id:04d} connected: {session.address}",
                "tag": "success",
            })

        def on_disconnected(session):
            bus.publish("session_remove", {"id": session.id})
            bus.publish("log", {
                "msg": f"[-] Session #{session.id:04d} disconnected: {session.address}",
                "tag": "warning",
            })

        def on_message(session, msg):
            bus.publish("log", {"msg": f"[{session.id:04d}] {msg}", "tag": "info"})

        def on_token_rotated(token):
            bus.publish("token_rotated", {"token": token})

        self.server.on_log = on_log
        self.server.on_client_connected = on_connected
        self.server.on_client_disconnected = on_disconnected
        self.server.on_client_message = on_message
        self.server.on_token_rotated = on_token_rotated

    # ---- helpers --------------------------------------------------------

    def _session_dict(self, session):
        return {
            "id": session.id,
            "address": session.address,
            "active": session.active,
            "created": session.created.isoformat(),
            "last_seen": session.last_seen,
            "payload_uuid": getattr(session, "payload_uuid", None),
        }

    # ---- operations -----------------------------------------------------

    def list_sessions(self):
        return [self._session_dict(s) for s in self.sessions.all()]

    def run_command(self, session_id, command, timeout=10.0):
        return self.server.send_command(session_id, command, timeout=timeout)

    def toggle_server(self):
        if self.server.running:
            self.server.stop()
            return {"running": False}
        ok = self.server.start()
        return {
            "running": ok,
            "host": self.server.host,
            "port": self.server.port,
        }

    def server_status(self):
        stats = (
            self.server_state.get_registry_stats()
            if self.server_state is not None
            else {"total": 0, "stale": 0}
        )
        if not self.server.running:
            return {"running": False, "registry": stats}
        info = self.server.get_token_info()
        return {
            "running": True,
            "host": self.server.host,
            "port": self.server.port,
            "token": self.server.get_current_token(),
            "expires_in": info.get("expires_in", 0),
            "registry": stats,
        }

    def revoke_session(self, session_id):
        """Revoke the session's payload and disconnect the session.

        Returns dict: {ok, reason, payload_uuid}.
        """
        session = self.sessions.get(session_id)
        if not session:
            return {"ok": False, "reason": "session not found"}

        uuid = getattr(session, "payload_uuid", None)
        if not uuid:
            return {"ok": False, "reason": "legacy session (no payload)"}

        revoked = self.server_state.revoke_payload(uuid)
        if not revoked:
            return {"ok": False, "reason": "payload not in registry",
                    "payload_uuid": uuid}

        # Disconnect the session
        self.sessions.set_active(session.id, False)
        try:
            session.socket.close()
        except Exception:
            pass

        return {"ok": True, "payload_uuid": uuid}

    def export(self, fmt):
        path = self.exporter.export_bundle(fmt, output_dir="builds/")
        p = Path(path)
        return {
            "path": str(p),
            "name": p.name,
            "size": p.stat().st_size,
        }


def get_state() -> AppState:
    return AppState()
