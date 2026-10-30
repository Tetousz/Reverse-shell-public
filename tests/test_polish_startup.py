"""Polish batch 2 test: startup QoL.

Verifies:
1. ServerState.get_registry_stats returns {total, stale}
2. Stats are correct with fresh + stale entries
3. web/main.py imports and has webbrowser wiring
4. /api/server/status includes registry
5. Dashboard imports cleanly

Run manually:  python3 tests/test_polish_startup.py
"""

import importlib
import sys
import tempfile
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core.server_state import ServerState  # noqa: E402


def main():
    # 1. Empty state → total=0, stale=0
    tmp = Path(tempfile.mkdtemp(prefix="rsc_polish2_"))
    state = ServerState(home=tmp)
    stats = state.get_registry_stats()
    assert stats == {"total": 0, "stale": 0}, f"empty state: {stats}"
    print(f"[1] empty registry stats OK {stats}")

    # 2. Fresh entries → total>0, stale=0
    state.register_payload("u1")
    state.register_payload("u2")
    state.touch_payload("u1")
    state.touch_payload("u2")
    stats = state.get_registry_stats()
    assert stats == {"total": 2, "stale": 0}, f"fresh: {stats}"
    print(f"[2] fresh registry stats OK {stats}")

    # 3. Backdate one entry → stale=1
    reg = state.get_registry()
    reg["payloads"]["u2"]["last_auth"] = time.time() - 60 * 86400
    state._write_registry(reg)
    stats = state.get_registry_stats()
    assert stats == {"total": 2, "stale": 1}, f"backdated: {stats}"
    print(f"[3] stale counted correctly OK {stats}")

    # 4. Non-destructive — entry still there after get_registry_stats
    assert state.has_payload("u2"), "get_registry_stats shouldn't delete"
    print(f"[4] get_registry_stats is non-destructive OK")

    # 5. web/main.py imports (don't call main, that runs a server)
    web_main = importlib.import_module("web.main")
    assert hasattr(web_main, "main"), "web.main.main missing"
    assert hasattr(web_main, "_open_browser_later"), "browser helper missing"
    print(f"[5] web.main imports + browser helper OK")

    # 6. web/state server_status includes registry
    # Patch DEFAULT_HOME before importing web.state to avoid touching ~/.config
    import core.server_state as _ss
    _orig = _ss.DEFAULT_HOME
    _ss.DEFAULT_HOME = tmp
    try:
        from web.state import get_state
        st = get_state()
        status = st.server_status()
        assert "registry" in status, f"registry missing from status: {status}"
        assert status["registry"]["total"] == 2, \
            f"registry total: {status['registry']}"
        print(f"[6] /api/server/status includes registry OK {status['registry']}")
    finally:
        _ss.DEFAULT_HOME = _orig
        # Reset singleton for other tests
        try:
            from web.state import AppState
            AppState._instance = None
        except Exception:
            pass

    # 7. Dashboard imports cleanly (don't launch Tk)
    import importlib as _il
    dash = _il.import_module("dashboard.dashboard")
    assert hasattr(dash, "Dashboard"), "Dashboard class missing"
    print(f"[7] dashboard imports cleanly OK")

    print("\n[PASS] polish batch 2 works")
    return 0


if __name__ == "__main__":
    sys.exit(main())
