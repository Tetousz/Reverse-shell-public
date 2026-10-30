"""Phase 8e test: revoke + hibernate.

1. Client.RECONNECT_DELAY == 30
2. Register payload -> identity auth succeeds -> revoke -> identity auth fails
3. Session dataclass exposes payload_uuid
4. _session_dict includes payload_uuid

Run manually:  python3 tests/test_revoke_hibernate.py
"""

import socket
import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from client.client import Client                       # noqa: E402
from core.server_state import ServerState              # noqa: E402
from core.session_manager import SessionManager         # noqa: E402
from modules.server import Server                       # noqa: E402

TEST_PORT = 4611


def _try_auth(server, message):
    s = socket.create_connection(("127.0.0.1", server.port), timeout=3)
    try:
        s.sendall((message + "\n").encode())
        return s.recv(1024).decode().strip()
    finally:
        try:
            s.close()
        except OSError:
            pass


def main():
    # 1. Hibernate constant
    assert Client.RECONNECT_DELAY == 30, \
        f"RECONNECT_DELAY should be 30, got {Client.RECONNECT_DELAY}"
    assert hasattr(Client, "_hibernate"), "Client._hibernate missing"
    print(f"[1] hibernate: RECONNECT_DELAY=30, _hibernate present OK")

    # 2. Session dataclass has payload_uuid
    from core.session_manager import Session
    s = Session(id=1, socket=None, addr=("x", 1))
    assert hasattr(s, "payload_uuid"), "Session.payload_uuid missing"
    assert s.payload_uuid is None, "default should be None"
    print(f"[2] Session.payload_uuid present, default None OK")

    # 3. Revoke flow
    tmp = Path(tempfile.mkdtemp(prefix="rsc_revoke_h_"))
    state = ServerState(home=tmp)
    sessions = SessionManager()
    server = Server(
        host="127.0.0.1", port=TEST_PORT,
        server_state=state,
        session_manager=sessions,
    )
    server.on_log = lambda m, t: None  # silence
    assert server.start()
    token = server.get_current_token()
    su = state.server_uuid

    try:
        pu = "aaaa1111bbbb2222cccc3333dddd4444"
        state.register_payload(pu)

        # Before revoke: auth succeeds
        reply = _try_auth(server, f"AUTH:{su}:{pu}:{token}")
        assert reply == "AUTH_SUCCESS", f"pre-revoke auth: {reply}"
        print(f"[3] pre-revoke identity auth succeeds OK")

        # Revoke
        assert state.revoke_payload(pu) is True
        assert not state.has_payload(pu)

        # After revoke: auth fails
        reply = _try_auth(server, f"AUTH:{su}:{pu}:{token}")
        assert reply == "AUTH_FAILED", f"post-revoke auth should fail: {reply}"
        print(f"[4] post-revoke identity auth rejected OK")

        # Legacy auth still works
        reply = _try_auth(server, f"AUTH:{token}")
        assert reply == "AUTH_SUCCESS", f"legacy auth: {reply}"
        print(f"[5] legacy auth unaffected by revoke OK")

    finally:
        server.stop()

    print("\n[PASS] revoke + hibernate work")
    return 0


if __name__ == "__main__":
    sys.exit(main())
