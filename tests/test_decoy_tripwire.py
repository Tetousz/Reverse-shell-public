"""Phase 7b test: decoys + tripwire.

Verifies:
1. Payload contains three distinct blobs
2. Decoy1 runs standalone → prints plausible output, exits 0
3. Decoy2 extracted + run → server logs TRIPWIRE
4. Decoys are referenced (so they look used) but don't fire during normal run

Run manually:  python3 tests/test_decoy_tripwire.py
"""

import subprocess
import sys
import tempfile
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core.config import Config                        # noqa: E402
from core.session_manager import SessionManager       # noqa: E402
from exporter import obfuscator                       # noqa: E402
from exporter.formats.py_exporter import PyExporter   # noqa: E402
from modules.server import Server                     # noqa: E402


TEST_PORT = 4566


def _extract_blob(content: str, name: str) -> str:
    marker = f"_{name}_B64 = ("
    start = content.index(marker) + len(marker)
    end = content.index(")\n\n", start)
    ns = {}
    exec("BLOB = (" + content[start:end] + ")", ns)
    return obfuscator.decode(ns["BLOB"])


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

    tripwires = []
    server.on_log = lambda msg, tag: (
        tripwires.append(msg) if "TRIPWIRE" in msg else None
    )

    if not server.start():
        print("FAIL: server did not start")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="rsc_decoy_"))
    exporter = PyExporter(beacon_host="127.0.0.1", beacon_port=TEST_PORT)
    payload = exporter.export("print('dummy client')\n")
    (tmp / "payload_py.py").write_text(payload)
    print(f"[setup] payload: {len(payload)} bytes, server on :{TEST_PORT}")

    # --- 1. three distinct blobs ---
    actual = _extract_blob(payload, "ACTUAL")
    decoy1 = _extract_blob(payload, "DECOY1")
    decoy2 = _extract_blob(payload, "DECOY2")
    assert actual != decoy1 and actual != decoy2 and decoy1 != decoy2
    print(
        f"[1] 3 distinct blobs OK "
        f"(actual={len(actual)}, decoy1={len(decoy1)}, decoy2={len(decoy2)})"
    )

    # --- 2. decoy1 runs standalone, prints plausible output ---
    d1 = tmp / "_rsc_loader.py"
    d1.write_text(decoy1)
    r = subprocess.run(
        [sys.executable, str(d1)], capture_output=True, timeout=5,
    )
    assert r.returncode == 0, f"decoy1 exit {r.returncode}: {r.stderr[:200]}"
    assert b"runtime module loaded" in r.stdout, f"decoy1 stdout: {r.stdout[:200]}"
    print(f"[2] decoy1 standalone runs OK, prints plausible output")

    # --- 3. decoy2 standalone → tripwire fires ---
    d2 = tmp / "_rsc_verify.py"
    d2.write_text(decoy2)
    subprocess.run(
        [sys.executable, str(d2)], capture_output=True, timeout=10,
    )
    deadline = time.time() + 3
    while time.time() < deadline and not tripwires:
        time.sleep(0.1)
    assert tripwires, "tripwire did not fire"
    print(f"[3] decoy2 fires tripwire OK: {tripwires[0][:90]}")

    # --- 4. decoys are referenced in launcher ---
    assert "_RSC_LOADER = _b64.b64decode(_DECOY1_B64)" in payload
    assert "_RSC_DIAG = _b64.b64decode(_DECOY2_B64)" in payload
    print(f"[4] decoys referenced in launcher OK")

    server.stop()
    print("\n[PASS] decoys + tripwire work")
    return 0


if __name__ == "__main__":
    sys.exit(main())
