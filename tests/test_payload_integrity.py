"""Phase 7a test: payload integrity check.

Verifies:
1. Payload file has _RSC_UUID and _RSC_LAUNCHED at module level
2. Embedded blob decodes to client source with the integrity check at top
3. Extracted blob standalone → exit 1, fast, no server connection
4. Full bundle payload → still connects (relies on test_e2e_export.py)

Run manually:  python3 tests/test_payload_integrity.py
"""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from exporter.export_manager import ExportManager  # noqa: E402
from exporter import obfuscator  # noqa: E402


def _extract_blob(payload_path: Path) -> str:
    """Decode the _ACTUAL_B64 blob back to source text."""
    content = payload_path.read_text()
    start = content.index("_ACTUAL_B64 = (") + len("_ACTUAL_B64 = (")
    end = content.index("_DECOY1_B64 = (")
    literal = content[start:end].strip()
    if literal.endswith(")"):
        literal = literal[:-1].rstrip()
    ns = {}
    exec("_B64 = (" + literal + ")", ns)
    return obfuscator.decode(ns["_B64"])


def main():
    tmp = Path(tempfile.mkdtemp(prefix="rsc_integrity_"))
    payload = ExportManager().export("py", output_dir=str(tmp))
    print(f"[export] {payload.name} ({payload.stat().st_size} bytes)")

    content = payload.read_text()

    # 1. Payload sets the required globals
    assert "_RSC_LAUNCHED = True" in content, "missing _RSC_LAUNCHED"
    assert "_RSC_UUID = " in content, "missing _RSC_UUID"
    print("[1] payload sets _RSC_LAUNCHED + _RSC_UUID OK")

    # 2. Blob has the integrity check at the top
    decoded = _extract_blob(payload)
    assert decoded.startswith("# --- payload integrity check ---"), \
        f"blob does not start with check, starts: {decoded[:60]!r}"
    assert "globals().get('_RSC_LAUNCHED')" in decoded, "check missing launched"
    assert "globals().get('_RSC_UUID')" in decoded, "check missing uuid"
    print(f"[2] blob starts with integrity check OK ({len(decoded)} bytes)")

    # 3. Extracted blob runs standalone → must exit(1), fast, no connection
    extracted = tmp / "extracted.py"
    extracted.write_text(decoded)
    start = time.time()
    result = subprocess.run(
        [sys.executable, str(extracted),
         "--host", "127.0.0.1", "--port", "1"],
        capture_output=True, timeout=5,
    )
    elapsed = time.time() - start
    assert result.returncode == 1, \
        f"extracted blob should exit(1), got {result.returncode}"
    assert elapsed < 2.0, f"exit should be immediate, took {elapsed:.2f}s"
    assert b"_RSC" not in result.stderr, \
        f"should not leak internal names to stderr: {result.stderr!r}"
    assert b"_RSC" not in result.stdout, \
        f"should not leak internal names to stdout: {result.stdout!r}"
    print(f"[3] extracted blob exits 1 immediately ({elapsed:.3f}s), silent OK")

    # 4. Different exports get different UUIDs (uniqueness)
    payload2 = ExportManager().export("py", output_dir=str(tmp))
    content2 = payload2.read_text()

    def get_uuid(text):
        for ln in text.splitlines():
            if ln.startswith("_RSC_UUID = "):
                return ln.split("=", 1)[1].strip()
        return None

    uuid1 = get_uuid(content)
    uuid2 = get_uuid(content2)
    assert uuid1 and uuid2, "could not parse UUIDs"
    assert uuid1 != uuid2, f"UUIDs should differ across exports: {uuid1}"
    print(f"[4] UUIDs unique across exports OK ({uuid1} != {uuid2})")

    print("\n[PASS] payload integrity check works")
    return 0


if __name__ == "__main__":
    sys.exit(main())
