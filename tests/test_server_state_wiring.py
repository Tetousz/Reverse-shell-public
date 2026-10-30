"""Phase 8b test: Server uses ServerState's persistent secret.

Verifies:
1. Server with server_state uses the state's secret (not auth_secret arg)
2. Token is stable across server restarts with same ServerState
3. Server without server_state still works (backward compat)
4. Server exposes server_state for downstream wiring

Run manually:  python3 tests/test_server_state_wiring.py
"""

import sys
import tempfile
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core.server_state import ServerState                # noqa: E402
from core.session_manager import SessionManager          # noqa: E402
from modules.server import Server                        # noqa: E402

TEST_PORT = 4588


def _start(server):
    assert server.start(), "server failed to start"
    return server


def main():
    tmp = Path(tempfile.mkdtemp(prefix="rsc_wiring_"))

    # ── 1. Server with ServerState uses state's secret ─────────
    state = ServerState(home=tmp)
    state_secret = state.get_secret()

    sessions = SessionManager()
    server = Server(
        host="127.0.0.1", port=TEST_PORT,
        auth_secret="IGNORED_BECAUSE_STATE_IS_SET",
        server_state=state,
        session_manager=sessions,
    )
    _start(server)
    token1 = server.get_current_token()
    print(f"[1] server uses state secret OK (token1={token1[:8]}...)")

    # Verify token matches what state secret would produce
    from core.auth import Auth
    expected_token = Auth(
        master_secret=state_secret,
        rotation_seconds=server.auth.rotation_seconds,
    ).token
    assert token1 == expected_token, \
        f"token mismatch: {token1} != {expected_token}"
    print(f"    token matches HMAC(state_secret) OK")

    # ── 2. Server exposes server_state ────────────────────────
    assert server.server_state is state
    print(f"[2] server.server_state is the injected state OK")

    # ── 3. Fresh ServerState (same disk) → same secret → same token ──
    #    No socket restart needed — just verify the token derivation is
    #    deterministic from persisted state.
    server.stop()
    time.sleep(0.1)

    state_reloaded = ServerState(home=tmp)
    assert state_reloaded.get_secret() == state_secret, \
        "secret did not persist"

    fresh_auth = Auth(
        master_secret=state_reloaded.get_secret(),
        rotation_seconds=server.auth.rotation_seconds,
    )
    assert fresh_auth.token == token1, \
        f"token not deterministic from persisted state: {fresh_auth.token} != {token1}"
    print(f"[3] token stable from persisted state OK ({token1[:8]}...)")

    # ── 4. Server without server_state → legacy path (own port) ─────
    sessions3 = SessionManager()
    server3 = Server(
        host="127.0.0.1", port=TEST_PORT + 1,
        auth_secret="LEGACY_TEST_SECRET",
        session_manager=sessions3,
    )
    _start(server3)
    assert server3.server_state is None, "server_state should be None"
    legacy_token = server3.get_current_token()
    expected_legacy = Auth(
        master_secret="LEGACY_TEST_SECRET",
        rotation_seconds=server3.auth.rotation_seconds,
    ).token
    assert legacy_token == expected_legacy
    print(f"[4] legacy auth_secret path still works OK")
    server3.stop()

    # ── 5. Registry is exposed via server_state ───────────────
    state.register_payload("test-uuid-123")
    assert server.server_state.has_payload("test-uuid-123")
    print(f"[5] registry accessible via server.server_state OK")

    print("\n[PASS] server state wiring works")
    return 0


if __name__ == "__main__":
    sys.exit(main())
