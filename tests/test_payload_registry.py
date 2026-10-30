"""Phase 8c test: exporters register payloads + embed identity.

Verifies:
1. Export with ServerState → payload embeds _RSC_SERVER_UUID + _RSC_PAYLOAD_UUID
2. Registry contains the payload_uuid
3. Master secret in payload matches ServerState's secret (not Config's)
4. Export without ServerState → no UUID globals (backward compat)
5. Two exports get distinct payload_uuids
6. All 5 formats benefit (single ExportManager change)

Run manually:  python3 tests/test_payload_registry.py
"""

import re
import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core.config import Config               # noqa: E402
from core.server_state import ServerState    # noqa: E402
from exporter import obfuscator              # noqa: E402
from exporter.export_manager import ExportManager  # noqa: E402


def _extract_globals_from_py(content: str) -> dict:
    """Extract _RSC_*_UUID globals from the decoded ACTUAL blob.

    The prelude (with _RSC_SERVER_UUID etc.) is prepended to the client
    source, which is then base64-encoded into _ACTUAL_B64. So we must
    decode the blob before searching.
    """
    out = {}

    # Multiline form:  _ACTUAL_B64 = (\n    "chunk1"\n    "chunk2"\n)
    m = re.search(r"_ACTUAL_B64 = \(\n(.*?)\n\)", content, re.DOTALL)
    if m:
        ns = {}
        exec(f"_B = ({m.group(1)})", ns)
        decoded = obfuscator.decode(ns["_B"])
    else:
        # Single-line form: _ACTUAL_B64 = 'AAAA...'
        m2 = re.search(r"_ACTUAL_B64 = '([A-Za-z0-9+/=]+)'", content)
        assert m2, "could not find _ACTUAL_B64 in either form"
        decoded = obfuscator.decode(m2.group(1))

    for name in ("SERVER_UUID", "PAYLOAD_UUID", "MASTER_SECRET"):
        mm = re.search(rf"_RSC_{name} = '([^']+)'", decoded)
        if mm:
            out[name] = mm.group(1)
    return out
def main():
    cfg = Config()
    tmp = Path(tempfile.mkdtemp(prefix="rsc_registry_"))
    state = ServerState(home=tmp)

    # ── 1. Export with ServerState embeds identity ─────────────
    mgr = ExportManager(server_state=state)
    payload_path = mgr.export("py", output_dir=str(tmp))
    content = payload_path.read_text()
    globals_found = _extract_globals_from_py(content)

    assert "SERVER_UUID" in globals_found, "missing _RSC_SERVER_UUID"
    assert "PAYLOAD_UUID" in globals_found, "missing _RSC_PAYLOAD_UUID"
    assert globals_found["SERVER_UUID"] == "default", \
        f"server_uuid should be 'default', got {globals_found['SERVER_UUID']!r}"
    print(f"[1] payload embeds identity OK "
          f"(server={globals_found['SERVER_UUID']}, "
          f"payload={globals_found['PAYLOAD_UUID'][:8]}...)")

    # ── 2. Registry contains the payload_uuid ──────────────────
    payload_uuid = globals_found["PAYLOAD_UUID"]
    assert state.has_payload(payload_uuid), \
        f"payload_uuid not in registry: {payload_uuid}"
    print(f"[2] payload_uuid registered OK")

    # ── 3. Master secret matches ServerState's secret ──────────
    assert globals_found["MASTER_SECRET"] == state.get_secret(), \
        "embedded master secret != ServerState secret"
    print(f"[3] master secret matches ServerState OK")

    # ── 4. Export without ServerState → no UUID globals ────────
    payload_no_state = ExportManager().export("py", output_dir=str(tmp))
    content_no_state = payload_no_state.read_text()
    globals_no_state = _extract_globals_from_py(content_no_state)
    assert "SERVER_UUID" not in globals_no_state, \
        "should not embed SERVER_UUID when no state provided"
    assert "PAYLOAD_UUID" not in globals_no_state, \
        "should not embed PAYLOAD_UUID when no state provided"
    assert "MASTER_SECRET" in globals_no_state, \
        "should still embed MASTER_SECRET for auto-auth (from config)"
    print(f"[4] export without ServerState → no identity, secret still present OK")

    # ── 5. Two exports get distinct payload_uuids ──────────────
    payload2 = mgr.export("py", output_dir=str(tmp))
    content2 = payload2.read_text()
    g2 = _extract_globals_from_py(content2)
    assert g2["PAYLOAD_UUID"] != payload_uuid, \
        f"payload_uuids should differ: {g2['PAYLOAD_UUID']} == {payload_uuid}"
    assert state.has_payload(g2["PAYLOAD_UUID"]), \
        "second payload not registered"
    print(f"[5] distinct payload_uuids across exports OK "
          f"({payload_uuid[:8]}... != {g2['PAYLOAD_UUID'][:8]}...)")

    # ── 6. All 5 formats get the identity ──────────────────────
    #    Each format wraps the python source in a different layer
    #    (bash heredoc / UTF-16LE base64 / JS template literal /
    #    plain py / spec + launcher). Unwrap first, then inspect.
    import base64 as _b64mod

    def _unwrap_python_source(fmt, exported_path):
        """Return the raw python source string for this format."""
        text = exported_path.read_text()
        if fmt == "py":
            return text
        if fmt == "exe":
            return (tmp / "payload_launcher.py").read_text()
        if fmt == "sh":
            return text.split("<< 'PYEOF'\n", 1)[1].rsplit("\nPYEOF", 1)[0]
        if fmt == "bat":
            enc = text.rsplit("-EncodedCommand ", 1)[1].strip()
            ps = _b64mod.b64decode(enc).decode("utf-16-le")
            return ps.split("@'\n", 1)[1].split("'@", 1)[0]
        if fmt == "js":
            m = re.search(r"const PROGRAM = `(.*?)`;", text, re.DOTALL)
            assert m, "js: PROGRAM template literal not found"
            return (m.group(1)
                    .replace("\\`", "`")
                    .replace("\\${", "${")
                    .replace("\\\\", "\\"))
        raise AssertionError(f"unknown format {fmt}")

    formats = ["py", "sh", "bat", "js", "exe"]
    format_uuids = {}

    for fmt in formats:
        exported = mgr.export(fmt, output_dir=str(tmp))
        py_source = _unwrap_python_source(fmt, exported)
        g = _extract_globals_from_py(py_source)
        assert "PAYLOAD_UUID" in g, f"{fmt}: PAYLOAD_UUID not found in blob"
        format_uuids[fmt] = g["PAYLOAD_UUID"]
        assert state.has_payload(g["PAYLOAD_UUID"]), \
            f"{fmt}: payload_uuid not in registry"

        assert "SERVER_UUID" in g, f"{fmt}: SERVER_UUID missing"
        assert g["SERVER_UUID"] == "default", \
            f"{fmt}: SERVER_UUID should be 'default', got {g['SERVER_UUID']!r}"

    print(f"[6] all 5 formats embed identity OK "
          f"({len(set(format_uuids.values()))} distinct uuids)")

    # ── 7. Total registry size matches exports (2 py from above + 5) ─
    reg_count = len(state.get_registry()["payloads"])
    assert reg_count == 7, f"expected 7 payloads, got {reg_count}"
    print(f"[7] registry has {reg_count} entries OK (matches export count)")

    print("\n[PASS] payload registration + identity embedding works")
    return 0


if __name__ == "__main__":
    sys.exit(main())
