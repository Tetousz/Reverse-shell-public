"""Phase 7.5 test: integrity + decoys present in every launcher format.

Verifies for py, sh, bat, js, exe:
1. Three distinct base64 blobs present
2. Launcher sets _RSC_LAUNCHED + _RSC_UUID
3. Extracted ACTUAL blob runs standalone -> silent exit(1)
4. bat/js/exe: inner Python program compiles
5. Decoy2 fires tripwire on a live server

Run manually:  python3 tests/test_backfill.py
"""

import base64
import re
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
from exporter.formats.bat_exporter import BatExporter # noqa: E402
from exporter.formats.exe_exporter import ExeExporter # noqa: E402
from exporter.formats.js_exporter import JsExporter   # noqa: E402
from exporter.formats.py_exporter import PyExporter   # noqa: E402
from exporter.formats.sh_exporter import ShExporter   # noqa: E402
from modules.server import Server                     # noqa: E402


TEST_PORT = 4577


def _extract_blobs_from_py(content: str) -> dict:
    """Extract _<NAME>_B64 = (...) from a plain Python source string."""
    out = {}
    for m in re.finditer(
        r"^_(\w+)_B64 = \(\n(.*?)\n\)", content, re.MULTILINE | re.DOTALL,
    ):
        name, body = m.group(1), m.group(2)
        ns = {}
        exec(f"B = ({body})", ns)
        out[name] = obfuscator.decode(ns["B"])
    return out


def _extract_blobs_from_oneline(content: str, marker_name: str) -> str:
    """Extract _<NAME>_B64 = '...' single-line form (bat/js)."""
    m = re.search(rf"_{marker_name}_B64 = '([^']+)'", content)
    assert m, f"single-line {marker_name}_B64 not found"
    return obfuscator.decode(m.group(1))


def _check_common(label: str, content: str):
    """Assertions that apply to every format's full output."""
    assert "_RSC_LAUNCHED" in content, f"{label}: launcher missing _RSC_LAUNCHED"
    assert "_RSC_UUID" in content, f"{label}: launcher missing _RSC_UUID"
    print(f"  [{label}] _RSC_LAUNCHED + _RSC_UUID present OK")


def _run_actual_standalone(actual_src: str, tmp: Path, label: str):
    path = tmp / f"extracted_{label}_actual.py"
    path.write_text(actual_src)
    r = subprocess.run(
        [sys.executable, str(path), "--host", "127.0.0.1", "--port", "1"],
        capture_output=True, timeout=5,
    )
    assert r.returncode == 1, f"{label} ACTUAL: exit {r.returncode} (want 1)"
    print(f"  [{label}] ACTUAL standalone exits 1 silently OK")


def main():
    cfg = Config()
    tmp = Path(tempfile.mkdtemp(prefix="rsc_backfill_"))
    first_decoy2 = None

    # ── py ──────────────────────────────────────────────────────
    print("[py]")
    py_content = PyExporter(beacon_host="127.0.0.1", beacon_port=TEST_PORT
                            ).export("print('dummy py')\n")
    py_blobs = _extract_blobs_from_py(py_content)
    assert len({py_blobs["ACTUAL"], py_blobs["DECOY1"], py_blobs["DECOY2"]}) == 3
    _check_common("py", py_content)
    assert "globals().get('_RSC_LAUNCHED')" in py_blobs["ACTUAL"]
    _run_actual_standalone(py_blobs["ACTUAL"], tmp, "py")
    first_decoy2 = py_blobs["DECOY2"]

    # ── sh ──────────────────────────────────────────────────────
    print("[sh]")
    sh_content = ShExporter(beacon_host="127.0.0.1", beacon_port=TEST_PORT
                            ).export("print('dummy sh')\n")
    sh_blobs = _extract_blobs_from_py(sh_content)
    assert len({sh_blobs["ACTUAL"], sh_blobs["DECOY1"], sh_blobs["DECOY2"]}) == 3
    _check_common("sh", sh_content)
    sh_path = tmp / "payload.sh"
    sh_path.write_text(sh_content)
    assert subprocess.run(["bash", "-n", str(sh_path)]).returncode == 0
    py_block = sh_content.split("<< 'PYEOF'\n", 1)[1].rsplit("\nPYEOF", 1)[0]
    compile(py_block, "<sh embedded>", "exec")
    _run_actual_standalone(sh_blobs["ACTUAL"], tmp, "sh")

    # ── bat ─────────────────────────────────────────────────────
    print("[bat]")
    bat_content = BatExporter(beacon_host="127.0.0.1", beacon_port=TEST_PORT
                              ).export("print('dummy bat')\n")
    assert "powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand" in bat_content
    # Unwrap: -EncodedCommand -> UTF-16LE b64 -> PS script -> here-string -> py
    enc = bat_content.rsplit("-EncodedCommand ", 1)[1].strip()
    ps = base64.b64decode(enc).decode("utf-16-le")
    py_src = ps.split("@'\n", 1)[1].split("'@", 1)[0]
    compile(py_src, "<bat inner>", "exec")
    print("  [bat] inner python compiles OK")
    # Check symbols on the DECODED py source, not the .bat wrapper
    _check_common("bat", py_src)
    # Extract ACTUAL from the single-line form
    actual_src = _extract_blobs_from_oneline(py_src, "ACTUAL")
    _run_actual_standalone(actual_src, tmp, "bat")
    # Verify _RSC_UUID + 3 distinct blobs present
    uuid_m = re.search(r"_RSC_UUID = '([0-9a-f]+)'", py_src)
    assert uuid_m, "bat: uuid missing"
    a = _extract_blobs_from_oneline(py_src, "ACTUAL")
    d1 = _extract_blobs_from_oneline(py_src, "DECOY1")
    d2 = _extract_blobs_from_oneline(py_src, "DECOY2")
    assert len({a, d1, d2}) == 3, "bat: 3 blobs not distinct"
    print("  [bat] 3 distinct blobs OK")

    # ── js ──────────────────────────────────────────────────────
    print("[js]")
    js_content = JsExporter(beacon_host="127.0.0.1", beacon_port=TEST_PORT
                            ).export("print('dummy js')\n")
    assert "const PROGRAM = `" in js_content
    assert "spawn('python'" in js_content
    # Unwrap the JS template literal
    m = re.search(r"const PROGRAM = `(.*?)`;", js_content, re.DOTALL)
    assert m, "js: PROGRAM template literal not found"
    py_src = m.group(1).replace("\\`", "`").replace("\\${", "${").replace("\\\\", "\\")
    compile(py_src, "<js inner>", "exec")
    print("  [js] inner python compiles OK")
    # Check symbols on the DECODED py source, not the .js wrapper
    _check_common("js", py_src)
    actual_src = _extract_blobs_from_oneline(py_src, "ACTUAL")
    _run_actual_standalone(actual_src, tmp, "js")
    a = _extract_blobs_from_oneline(py_src, "ACTUAL")
    d1 = _extract_blobs_from_oneline(py_src, "DECOY1")
    d2 = _extract_blobs_from_oneline(py_src, "DECOY2")
    assert len({a, d1, d2}) == 3, "js: 3 blobs not distinct"
    print("  [js] 3 distinct blobs OK")

    # ── exe ─────────────────────────────────────────────────────
    print("[exe]")
    ex = ExeExporter(beacon_host="127.0.0.1", beacon_port=TEST_PORT)
    spec = ex.export("print('dummy exe')\n")
    companions = ex.companion_files("print('dummy exe')\n")
    compile(spec, "<spec>", "exec")
    launcher_src = companions["payload_launcher.py"]
    compile(launcher_src, "<launcher>", "exec")
    _check_common("exe", launcher_src)
    assert "if __name__ == '__main__':" in launcher_src
    exe_blobs = _extract_blobs_from_py(launcher_src)
    assert len({exe_blobs["ACTUAL"], exe_blobs["DECOY1"], exe_blobs["DECOY2"]}) == 3
    _run_actual_standalone(exe_blobs["ACTUAL"], tmp, "exe")

    # ── tripwire (decoy2 from py) ───────────────────────────────
    print("[tripwire]")
    sessions = SessionManager()
    server = Server(
        host="127.0.0.1", port=TEST_PORT,
        auth_secret=cfg.auth_secret,
        rotation_seconds=cfg.rotation_seconds,
        grace_windows=cfg.grace_windows,
        session_manager=sessions,
    )
    tripwires = []
    server.on_log = lambda msg, tag: (
        tripwires.append(msg) if "TRIPWIRE" in msg else None
    )
    assert server.start()

    decoy2_path = tmp / "_rsc_verify.py"
    decoy2_path.write_text(first_decoy2)
    subprocess.run([sys.executable, str(decoy2_path)], capture_output=True, timeout=10)
    deadline = time.time() + 3
    while time.time() < deadline and not tripwires:
        time.sleep(0.1)
    server.stop()
    assert tripwires, "tripwire did not fire"
    print(f"  TRIPWIRE fired OK: {tripwires[0][:90]}")

    print("\n[PASS] all formats (py/sh/bat/js/exe) backfilled")
    return 0


if __name__ == "__main__":
    sys.exit(main())
