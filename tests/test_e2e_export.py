"""End-to-end test: exported *bundled* payload connects back to a live Server.

The bundle is extracted to a temp dir outside the project tree to prove
it's genuinely portable (no PYTHONPATH, no cwd tricks).

Run manually:  python3 tests/test_e2e_export.py
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

from core.config import Config                       # noqa: E402
from core.session_manager import SessionManager      # noqa: E402
from exporter.export_manager import ExportManager    # noqa: E402
from modules.server import Server                    # noqa: E402


TEST_PORT = 4555


def _dump_client(proc, label):
    """Print whatever the client has written so far."""
    if not proc.stdout:
        print(f"[{label}] no stdout pipe")
        return
    try:
        import fcntl, os
        fl = fcntl.fcntl(proc.stdout, fcntl.F_GETFL)
        fcntl.fcntl(proc.stdout, fcntl.F_SETFL, fl | os.O_NONBLOCK)
        try:
            data = proc.stdout.read()
        finally:
            fcntl.fcntl(proc.stdout, fcntl.F_SETFL, fl)
    except Exception:
        data = b""
    if data:
        print(f"[{label}] client output:\n{data.decode(errors='replace')[:2000]}")
    else:
        print(f"[{label}] client output: (empty)")
    if proc.poll() is not None:
        print(f"[{label}] client exited with code {proc.returncode}")


def _wait_until(predicate, timeout=10.0, interval=0.1):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def main():
    cfg = Config()
    sessions = SessionManager()
    server = Server(
        host="127.0.0.1",
        port=TEST_PORT,
        auth_secret=cfg.auth_secret,
        rotation_seconds=cfg.rotation_seconds,
        grace_windows=cfg.grace_windows,
        session_manager=sessions,
    )
    if not server.start():
        print("FAIL: server did not start")
        return 1

    token = server.get_current_token()
    print(f"[setup] server on 127.0.0.1:{TEST_PORT} | token {token[:8]}...")

    # Export + bundle, then extract to a *portable* temp dir.
    zip_tmp = Path(tempfile.mkdtemp(prefix="rsc_zip_"))
    zip_path = ExportManager().export_bundle("py", output_dir=str(zip_tmp))
    print(f"[bundle] {zip_path.name} ({zip_path.stat().st_size} bytes)")

    extract_dir = Path(tempfile.mkdtemp(prefix="rsc_extracted_"))
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_dir)
    payload_path = extract_dir / "payload_py.py"
    assert payload_path.is_file(), f"missing {payload_path}"
    assert (extract_dir / "core" / "auth.py").is_file(), "missing core/auth.py in bundle"
    print(f"[extracted] {extract_dir}")

    proc = subprocess.Popen(
        [sys.executable, str(payload_path),
         "--host", "127.0.0.1",
         "--port", str(TEST_PORT),
         ],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        start_new_session=True,
        cwd=str(extract_dir),
    )

    try:
        if not _wait_until(lambda: sessions.count_active() >= 1, timeout=15):
            print("FAIL: no session connected within 15s")
            if proc.stdout:
                try:
                    out = proc.stdout.read(4096).decode(errors='replace')
                    print("client output:\n" + out[:2000])
                except Exception:
                    pass
            return 1
        sess = sessions.active()[0]
        print(f"[connected] session #{sess.id:04d} from {sess.address}")

        ok, output = server.send_command(sess.id, "echo RSC_E2E_OK", timeout=10)
        if not ok or "RSC_E2E_OK" not in output:
            print(f"FAIL: command round-trip | ok={ok} | output={output!r}")
            _dump_client(proc, "cmd-fail")
            return 1
        print(f"[command] echo → {output.strip()!r}")

        ok, output = server.send_command(sess.id, "echo SECOND_CMD", timeout=10)
        if not ok or "SECOND_CMD" not in output:
            print(f"FAIL: second command | ok={ok} | output={output!r}")
            return 1
        print(f"[command] second → {output.strip()!r}")

        server.send_command(sess.id, "exit", timeout=3)
        if not _wait_until(lambda: sessions.count_active() == 0, timeout=10):
            print("FAIL: session did not disconnect after 'exit'")
            return 1
        print("[disconnect] session closed cleanly")

    finally:
        if proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
        server.stop()
        for d in (zip_tmp, extract_dir):
            for f in d.rglob("*"):
                if f.is_file():
                    f.unlink()
            for sub in sorted(d.rglob("*"), reverse=True):
                if sub.is_dir():
                    sub.rmdir()
            d.rmdir()

    print("\n[PASS] portable bundle → connect → command → disconnect")
    return 0


if __name__ == "__main__":
    sys.exit(main())
