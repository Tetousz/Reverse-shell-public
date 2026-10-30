"""Detect the current ngrok TCP tunnel via its local admin API.

Usage:
    host, port = detect_tunnel()       # (str, int) or (None, None)

Ngrok exposes a local admin API on http://127.0.0.1:4040 when running.
Calling it is cheap and requires no extra dependency — pure stdlib.
"""

import json
import urllib.error
import urllib.request


ADMIN_URL = "http://127.0.0.1:4040/api/tunnels"
DEFAULT_TIMEOUT = 1.5


def detect_tunnel(admin_url=ADMIN_URL, timeout=DEFAULT_TIMEOUT):
    """Return (host, port) of the first TCP tunnel, or (None, None).

    Picks the first entry whose public_url starts with ``tcp://``.
    If multiple exist, first-wins (order chosen by ngrok).
    """
    try:
        with urllib.request.urlopen(admin_url, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        return None, None

    tunnels = data.get("tunnels") or []
    for tunnel in tunnels:
        url = tunnel.get("public_url", "")
        if url.startswith("tcp://"):
            rest = url[len("tcp://"):]
            if ":" not in rest:
                continue
            host, port_s = rest.rsplit(":", 1)
            try:
                return host, int(port_s)
            except ValueError:
                continue

    return None, None


def parse_ngrok_url(url):
    """Parse 'host:port' or 'tcp://host:port' into (host, port).

    Returns (None, None) on malformed input.
    """
    if not url:
        return None, None
    s = url.strip()
    if s.startswith("tcp://"):
        s = s[len("tcp://"):]
    if ":" not in s:
        return None, None
    host, port_s = s.rsplit(":", 1)
    try:
        return host, int(port_s)
    except ValueError:
        return None, None
