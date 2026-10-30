"""Phase 8a test: persistent server state (secret + registry + meta).

Run manually:  python3 tests/test_server_state.py
"""

import json
import sys
import tempfile
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core.server_state import ServerState  # noqa: E402


def main():
    tmp = Path(tempfile.mkdtemp(prefix="rsc_state_"))

    # 1. Fresh state creates all three files
    state = ServerState(home=tmp)
    assert state.secret_path.is_file(), "secret not created"
    assert state.registry_path.is_file(), "registry not created"
    assert state.meta_path.is_file(), "meta not created"
    print("[1] fresh state creates secret + registry + meta OK")

    # 2. Secret is 64 hex chars (32 bytes) and persistent across instances
    secret1 = state.get_secret()
    assert len(secret1) == 64, f"expected 64-char secret, got {len(secret1)}"
    int(secret1, 16)  # validates hex
    state2 = ServerState(home=tmp)
    assert state2.get_secret() == secret1, "secret not persistent"
    print(f"[2] secret persists across instances OK ({secret1[:8]}...)")

    # 3. Secret file has 0600 perms
    mode = state.secret_path.stat().st_mode & 0o777
    assert mode == 0o600, f"expected 0600 perms, got {oct(mode)}"
    print(f"[3] secret file perms = 0600 OK")

    # 4. Migration: caller-supplied secret wins on first run
    tmp2 = Path(tempfile.mkdtemp(prefix="rsc_state_migrate_"))
    state_m = ServerState(home=tmp2, migration_secret="MIGRATED_SECRET_42")
    assert state_m.get_secret() == "MIGRATED_SECRET_42", "migration failed"
    print("[4] migration secret honored on first run OK")

    # 4b. Migration only applies on FIRST run
    state_m2 = ServerState(home=tmp2, migration_secret="DIFFERENT_SECRET")
    assert state_m2.get_secret() == "MIGRATED_SECRET_42", "should not re-migrate"
    print("[4b] migration secret ignored on subsequent runs OK")

    # 5. Register a payload
    assert state.register_payload("uuid-aaaa") is True
    assert state.has_payload("uuid-aaaa")
    assert not state.has_payload("uuid-bbbb")
    print("[5] register_payload + has_payload OK")

    # 6. Duplicate registration returns False, no state change
    assert state.register_payload("uuid-aaaa") is False
    print("[6] duplicate register returns False OK")

    # 7. touch_payload updates last_auth
    before = state.get_registry()["payloads"]["uuid-aaaa"]["last_auth"]
    assert before is None, f"last_auth should be None before touch, got {before}"
    time.sleep(0.05)
    assert state.touch_payload("uuid-aaaa") is True
    after = state.get_registry()["payloads"]["uuid-aaaa"]["last_auth"]
    assert after is not None and after > 0, "last_auth not set"
    print(f"[7] touch_payload updates last_auth OK (last_auth={after:.2f})")

    # 7b. touch_payload on unknown uuid returns False
    assert state.touch_payload("uuid-unknown") is False
    print("[7b] touch_payload on unknown uuid returns False OK")

    # 8. Registry persists across instances
    state3 = ServerState(home=tmp)
    assert state3.has_payload("uuid-aaaa"), "registry not persistent"
    assert state3.get_registry()["payloads"]["uuid-aaaa"]["last_auth"] is not None
    print("[8] registry persists across instances OK")

    # 9. Prune removes stale entries
    #    Manually backdate uuid-aaaa's last_auth to 60 days ago
    reg = state3.get_registry()
    reg["payloads"]["uuid-aaaa"]["last_auth"] = time.time() - 60 * 86400
    state3._write_registry(reg)

    # Add a fresh entry
    state3.register_payload("uuid-fresh")
    state3.touch_payload("uuid-fresh")

    removed = state3.prune_stale(days=30)
    assert "uuid-aaaa" in removed, f"stale uuid not removed: {removed}"
    assert not state3.has_payload("uuid-aaaa"), "uuid-aaaa should be gone"
    assert state3.has_payload("uuid-fresh"), "fresh uuid should remain"
    print(f"[9] prune_stale removes entries older than 30d OK ({removed})")

    # 10. Meta file persists created_at
    meta = state3.get_meta()
    assert "created_at" in meta
    assert meta["instance"] == "default"
    print(f"[10] meta persists OK (created_at={meta['created_at']:.2f})")

    # 11. Registry file on disk is valid JSON after all operations
    on_disk = json.loads(state3.registry_path.read_text())
    assert "payloads" in on_disk
    print(f"[11] registry.json valid on disk OK ({len(on_disk['payloads'])} entries)")

    print("\n[PASS] persistent server state works")
    return 0


if __name__ == "__main__":
    sys.exit(main())
