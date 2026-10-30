"""Phase 9a test: ngrok tunnel detection + URL parsing.

Run manually:  python3 tests/test_ngrok.py
"""

import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core.ngrok import detect_tunnel, parse_ngrok_url  # noqa: E402


class _MockNgrokHandler(BaseHTTPRequestHandler):
    """Serves a fake ngrok admin API response."""
    _payload = b""
    _status = 200

    def do_GET(self):
        if self.path != "/api/tunnels":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(self._status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(self._payload)

    def log_message(self, *args):
        pass  # silence


def _run_server(payload, status=200):
    _MockNgrokHandler._payload = payload
    _MockNgrokHandler._status = status
    srv = HTTPServer(("127.0.0.1", 0), _MockNgrokHandler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, port


def main():
    # 1. No ngrok running (real port 4040 likely closed) → (None, None)
    host, port = detect_tunnel()
    # If ngrok happens to be running on this machine, skip that check
    if host is None:
        print(f"[1] ngrok not running → (None, None) OK")
    else:
        print(f"[1] ngrok IS running → detected {host}:{port} (skip negative test)")

    # 2. Mock: single TCP tunnel
    import json
    payload = json.dumps({
        "tunnels": [
            {"public_url": "tcp://2.tcp.eu.ngrok.io:12345", "proto": "tcp"},
        ]
    }).encode()
    srv, port_num = _run_server(payload)
    try:
        h, p = detect_tunnel(admin_url=f"http://127.0.0.1:{port_num}/api/tunnels")
        assert h == "2.tcp.eu.ngrok.io", f"host: {h}"
        assert p == 12345, f"port: {p}"
        print(f"[2] single TCP tunnel detected OK → {h}:{p}")
    finally:
        srv.shutdown()

    # 3. Mock: no tunnels → (None, None)
    srv, port_num = _run_server(b'{"tunnels": []}')
    try:
        h, p = detect_tunnel(admin_url=f"http://127.0.0.1:{port_num}/api/tunnels")
        assert h is None and p is None, f"expected (None, None), got {(h, p)}"
        print(f"[3] empty tunnels → (None, None) OK")
    finally:
        srv.shutdown()

    # 4. Mock: HTTP-only tunnel → skipped, returns None
    payload = json.dumps({
        "tunnels": [
            {"public_url": "https://abc.ngrok.io", "proto": "https"},
        ]
    }).encode()
    srv, port_num = _run_server(payload)
    try:
        h, p = detect_tunnel(admin_url=f"http://127.0.0.1:{port_num}/api/tunnels")
        assert h is None and p is None, f"http tunnel should be skipped: {(h, p)}"
        print(f"[4] HTTP-only tunnel ignored OK")
    finally:
        srv.shutdown()

    # 5. Mock: mixed HTTP + TCP → picks TCP
    payload = json.dumps({
        "tunnels": [
            {"public_url": "https://abc.ngrok.io", "proto": "https"},
            {"public_url": "tcp://5.tcp.us.ngrok.io:54321", "proto": "tcp"},
        ]
    }).encode()
    srv, port_num = _run_server(payload)
    try:
        h, p = detect_tunnel(admin_url=f"http://127.0.0.1:{port_num}/api/tunnels")
        assert h == "5.tcp.us.ngrok.io" and p == 54321, f"got {(h, p)}"
        print(f"[5] mixed tunnels → picks TCP OK → {h}:{p}")
    finally:
        srv.shutdown()

    # 6. Admin API unreachable → (None, None), no crash
    h, p = detect_tunnel(admin_url="http://127.0.0.1:1/api/tunnels", timeout=0.5)
    assert h is None and p is None
    print(f"[6] unreachable admin API → (None, None) OK")

    # 7. parse_ngrok_url: various forms
    assert parse_ngrok_url("2.tcp.eu.ngrok.io:12345") == ("2.tcp.eu.ngrok.io", 12345)
    assert parse_ngrok_url("tcp://2.tcp.eu.ngrok.io:12345") == ("2.tcp.eu.ngrok.io", 12345)
    assert parse_ngrok_url("no-colon") == (None, None)
    assert parse_ngrok_url("bad:port") == (None, None)
    assert parse_ngrok_url("") == (None, None)
    assert parse_ngrok_url(None) == (None, None)
    print(f"[7] parse_ngrok_url edge cases OK")

    print("\n[PASS] ngrok detection works")
    return 0


if __name__ == "__main__":
    sys.exit(main())
