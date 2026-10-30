"""Phase 8e-5 test: web revoke endpoint.

Starts a Flask app on a temp port with a temp ServerState home.

Run manually:  python3 tests/test_web_revoke.py
"""

import json
import sys
import tempfile
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# Patch ServerState to use temp dir BEFORE importing web modules
import core.server_state as _ss
_TMP_HOME = Path(tempfile.mkdtemp(prefix="rsc_web_revoke_"))
_ss.DEFAULT_HOME = _TMP_HOME


def _post(url, data=None):
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode() if data else b"",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def main():
    from web.app import create_app
    from web.state import get_state

    app = create_app()
    port = 4677

    def _run():
        app.run(host="127.0.0.1", port=port,
                debug=False, threaded=True, use_reloader=False)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    time.sleep(0.8)

    base = f"http://127.0.0.1:{port}"

    state = get_state()
    fake_uuid = "cccc1111cccc2222cccc3333cccc4444"
    state.server_state.register_payload(fake_uuid)

    sid = state.sessions.add(socket=None, addr=("127.0.0.1", 9999))
    sess = state.sessions.get(sid)
    sess.payload_uuid = fake_uuid

    with urllib.request.urlopen(base + "/api/sessions", timeout=5) as r:
        sessions = json.loads(r.read())
    assert any(s["id"] == sid and s["payload_uuid"] == fake_uuid for s in sessions), \
        f"payload_uuid not in sessions: {sessions}"
    print(f"[1] /api/sessions returns payload_uuid OK")

    code, data = _post(base + f"/api/sessions/{sid}/revoke")
    assert code == 200, f"revoke returned {code}: {data}"
    assert data.get("ok") is True, f"revoke not ok: {data}"
    assert data.get("payload_uuid") == fake_uuid
    print(f"[2] POST revoke returns ok=True OK")

    assert not state.server_state.has_payload(fake_uuid), \
        "payload still in registry after revoke"
    print(f"[3] payload removed from registry OK")

    code, data = _post(base + f"/api/sessions/9999/revoke")
    assert code == 400, f"expected 400, got {code}"
    assert data.get("ok") is False
    print(f"[4] revoke unknown session returns 400 OK")

    sid2 = state.sessions.add(socket=None, addr=("127.0.0.1", 9998))
    code, data = _post(base + f"/api/sessions/{sid2}/revoke")
    assert code == 400, f"expected 400, got {code}"
    assert "legacy" in (data.get("reason") or "").lower(), \
        f"expected legacy reason: {data}"
    print(f"[5] revoke legacy session returns 400 with 'legacy' reason OK")

    print("\n[PASS] web revoke endpoint works")
    return 0


if __name__ == "__main__":
    sys.exit(main())
