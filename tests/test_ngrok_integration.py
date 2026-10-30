"""Phase 9b-e test: ngrok end-to-end integration.

1. Config exposes ngrok_url
2. Export with ngrok_url set → prelude has _RSC_NGROK_HOST/_RSC_NGROK_PORT
3. Export without ngrok → no ngrok globals
4. Client prefers embedded ngrok over discovery (functional e2e)

Run manually:  python3 tests/test_ngrok_integration.py
"""

import os
import signal
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core.config import Config                          # noqa: E402
from core.session_manager import SessionManager         # noqa: E402
from core.server_state import ServerState               # noqa: E402
from exporter import obfuscator                         # noqa: E402
from exporter.export_manager import ExportManager       # noqa: E402
from modules.server import Server                       # noqa: E402

TEST_PORT = 4622


def _extract_blob(content):
    start = content.index("_ACTUAL_B64 = (") + len("_ACTUAL_B64 = (")
    end = content.index("_DECOY1_B64 = (")
    literal = content[start:end].strip()
    if literal.endswith(")"):
        literal = literal[:-1].rstrip()
    ns = {}
    exec("_B64 = (" + literal + ")", ns)
    return obfuscator.decode(ns["_B64"])


def _wait_until(pred, timeout=10.0, interval=0.1):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(interval)
    return False


def _dump_client_output(proc, label):
    """Non-blocking dump of client stdout for diagnostics."""
    import fcntl
    if not proc.stdout:
        print(f"[{label}] no stdout")
        return
    try:
        fl = fcntl.fcntl(proc.stdout, fcntl.F_GETFL)
        fcntl.fcntl(proc.stdout, fcntl.F_SETFL, fl | os.O_NONBLOCK)
        try:
            data = proc.stdout.read()
        finally:
            fcntl.fcntl(proc.stdout, fcntl.F_SETFL, fl)
    except Exception:
        data = b""
    if data:
        print(f"[{label}] client output:\n{data.decode(errors='replace')[:1500]}")
    else:
        print(f"[{label}] client output: (empty)")
    if proc.poll() is not None:
        print(f"[{label}] client exited with code {proc.returncode}")


def main():
    # ── 1. Config exposes ngrok_url ────────────────────────────
    cfg = Config()
    val = cfg.get("server", "ngrok_url")
    assert val is None or isinstance(val, str), f"unexpected: {val!r}"
    print(f"[1] Config.ngrok_url accessible (current value: {val!r}) OK")

    tmp = Path(tempfile.mkdtemp(prefix="rsc_ngrok_int_"))

    # ── 2. Export with explicit ngrok_url → prelude has globals ─
    os.environ["RSC_NGROK_TEST"] = "1"  # marker, in case we want opt-in later
    state = ServerState(home=tmp)
    mgr = ExportManager(server_state=state)

    # Monkey-patch Config to return our fake ngrok URL
    _orig_get = cfg.get
    def _patched_get(section, key, *args, **kwargs):
        if section == "server" and key == "ngrok_url":
            return "my.ngrok.io:12345"
        return _orig_get(section, key, *args, **kwargs)
    cfg.get = _patched_get

    # Monkey-patch to make exporter use our patched Config
    import exporter.export_manager as _em
    _orig_init = _em.ExportManager.__init__
    def _patched_init(self, client_path="client/client.py", server_state=None):
        _orig_init(self, client_path=client_path, server_state=server_state)
        self._cfg_override = cfg
    # Actually simpler: patch Config reference inside export_manager
    # The exporter does `from core.config import Config` then `Config()`.
    # We can patch core.config.Config.get instead.

    import core.config as _cc
    _real_get = _cc.Config.get
    def _fake_get(self, section, key, *a, **kw):
        if section == "server" and key == "ngrok_url":
            return "my.ngrok.io:12345"
        return _real_get(self, section, key, *a, **kw)
    _cc.Config.get = _fake_get
    try:
        payload_path = mgr.export("py", output_dir=str(tmp))
    finally:
        _cc.Config.get = _real_get

    content = payload_path.read_text()
    decoded = _extract_blob(content)
    assert "_RSC_NGROK_HOST = 'my.ngrok.io'" in decoded, \
        f"missing ngrok host in prelude. First 500 chars:\n{decoded[:500]}"
    assert "_RSC_NGROK_PORT = 12345" in decoded, \
        "missing ngrok port in prelude"
    print(f"[2] Export with ngrok_url → prelude has ngrok globals OK")

    # ── 3. Export without ngrok → no ngrok globals ─────────────
    payload2 = mgr.export("py", output_dir=str(tmp))
    decoded2 = _extract_blob(payload2.read_text())
    # ngrok_url is None in config, and detect_tunnel likely returns (None, None)
    # since ngrok isn't running
    has_ngrok = "_RSC_NGROK_HOST" in decoded2
    if has_ngrok:
        print(f"[3] SKIP — real ngrok detected on this machine, can't test negative case")
    else:
        print(f"[3] Export without ngrok → no ngrok globals OK")

    # ── 4. Functional: client prefers embedded ngrok host ──────
    sessions = SessionManager()
    server = Server(
        host="127.0.0.1", port=TEST_PORT,
        server_state=state,
        session_manager=sessions,
    )
    server.on_log = lambda m, t: None
    assert server.start()

    try:
        # Patch Config so export uses 127.0.0.1:TEST_PORT as ngrok target
        _real_get2 = _cc.Config.get
        def _fake_get2(self, section, key, *a, **kw):
            if section == "server" and key == "ngrok_url":
                return f"127.0.0.1:{TEST_PORT}"
            return _real_get2(self, section, key, *a, **kw)

        # Bundle must be exported WITH the Config patch active, since
        # export_bundle internally calls export() which reads Config.
        bundle_tmp = tmp / "bundle"
        bundle_tmp.mkdir()
        _cc.Config.get = _fake_get2
        try:
            bundle_zip = mgr.export_bundle("py", output_dir=str(bundle_tmp))
        finally:
            _cc.Config.get = _real_get2

        extract = tmp / "extracted"
        extract.mkdir()
        with zipfile.ZipFile(bundle_zip) as zf:
            zf.extractall(extract)

        payload_script = extract / "payload_py.py"
        assert payload_script.is_file()

        # Run WITHOUT --host (should use embedded ngrok globals)
        proc = subprocess.Popen(
            [sys.executable, str(payload_script)],  # no --host
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            cwd=str(extract),
            start_new_session=True,
        )

        try:
            connected = _wait_until(lambda: sessions.count_active() >= 1, timeout=10)
            if not connected:
                _dump_client_output(proc, "ngrok-fail")
                raise AssertionError("client did not connect via embedded ngrok host")
            print(f"[4] Client connected via embedded ngrok host OK "
                  f"({sessions.count_active()} session)")
        finally:
            if proc.poll() is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except Exception:
                    pass
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except Exception:
                        pass
    finally:
        server.stop()

    print("\n[PASS] ngrok integration works")
    return 0


if __name__ == "__main__":
    sys.exit(main())
