"""Phase 8d test: two-stage auth protocol.

Covers 6 scenarios:
1. Identity auth succeeds when registered + token valid
2. Identity auth fails when server_uuid wrong
3. Identity auth fails when payload_uuid not in registry
4. Identity auth fails when token invalid
5. Legacy auth still works (backward compat)
6. Successful identity auth updates registry's last_auth

Run manually:  python3 tests/test_two_stage_auth.py
"""

import socket
import sys
import tempfile
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core.server_state import ServerState                # noqa: E402
from core.session_manager import SessionManager          # noqa: E402
from modules.server import Server                        # noqa: E402

TEST_PORT = 4599


def _try_auth(server, message):
    """Open a fresh socket, send auth message, read reply."""
    s = socket.create_connection(("127.0.0.1", server.port), timeout=3)
    try:
        s.sendall((message + "\n").encode())
        reply = s.recv(1024).decode().strip()
        return reply
    finally:
        try:
            s.close()
        except OSError:
            pass


def main():
    tmp = Path(tempfile.mkdtemp(prefix="rsc_2stage_"))
    state = ServerState(home=tmp)
    sessions = SessionManager()

    server = Server(
        host="127.0.0.1", port=TEST_PORT,
        server_state=state,
        session_manager=sessions,
    )

    # Silence server logs for cleanliness
    logs = []
    server.on_log = lambda msg, tag: logs.append((msg, tag))

    assert server.start(), "server failed to start"
    token = server.get_current_token()
    server_uuid = state.server_uuid  # "default"

    try:
        # ── 1. Valid identity auth ─────────────────────────────
        payload_uuid = "aaaa1111bbbb2222cccc3333dddd4444"
        state.register_payload(payload_uuid)

        reply = _try_auth(
            server,
            f"AUTH:{server_uuid}:{payload_uuid}:{token}",
        )
        assert reply == "AUTH_SUCCESS", f"expected SUCCESS, got {reply}"
        print(f"[1] valid identity auth succeeds OK")

        # ── 2. Wrong server_uuid ───────────────────────────────
        reply = _try_auth(
            server,
            f"AUTH:wrong-server:{payload_uuid}:{token}",
        )
        assert reply == "AUTH_FAILED", f"expected FAILED, got {reply}"
        print(f"[2] wrong server_uuid rejected OK")

        # ── 3. Unregistered payload_uuid ───────────────────────
        reply = _try_auth(
            server,
            f"AUTH:{server_uuid}:deadbeefdeadbeefdeadbeefdeadbeef:{token}",
        )
        assert reply == "AUTH_FAILED", f"expected FAILED, got {reply}"
        print(f"[3] unregistered payload_uuid rejected OK")

        # ── 4. Invalid token ───────────────────────────────────
        reply = _try_auth(
            server,
            f"AUTH:{server_uuid}:{payload_uuid}:DEADBEEFDEADBEEFDEADBEEFDEADBEEF",
        )
        assert reply == "AUTH_FAILED", f"expected FAILED, got {reply}"
        print(f"[4] invalid token rejected OK")

        # ── 5. Legacy AUTH:<token> still works ─────────────────
        reply = _try_auth(server, f"AUTH:{token}")
        assert reply == "AUTH_SUCCESS", f"legacy should succeed, got {reply}"
        print(f"[5] legacy AUTH:<token> accepted OK (backward compat)")

        # ── 6. Successful identity auth touches registry ───────
        #    last_auth should be set after auth #1
        reg = state.get_registry()["payloads"]
        assert payload_uuid in reg, "payload not in registry"
        assert reg[payload_uuid]["last_auth"] is not None, \
            "last_auth should be set after successful auth"
        print(f"[6] successful auth updates last_auth OK")

        # ── Verify server logs mention both paths ──────────────
        #    Server thread emits logs asynchronously — poll briefly.
        deadline = time.time() + 2.0
        success_logs, failed_logs = [], []
        while time.time() < deadline:
            success_logs = [m for m, t in logs if "Auth OK" in m]
            failed_logs = [m for m, t in logs if "Auth FAILED" in m]
            if len(success_logs) >= 2 and len(failed_logs) >= 3:
                break
            time.sleep(0.05)

        assert any("payload" in m for m in success_logs), \
            f"no identity-auth log (got {success_logs})"
        assert any("legacy" in m for m in success_logs), \
            f"no legacy-auth log (got {success_logs})"
        assert len(failed_logs) == 3, f"expected 3 failures, got {len(failed_logs)}"
        print(f"[+] logs contain 1 identity + 1 legacy success + 3 failures")

    finally:
        server.stop()

    print("\n[PASS] two-stage auth works (all 6 scenarios)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
