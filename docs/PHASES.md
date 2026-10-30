
## Phase 5 — Exporter (+ 5.5: Bundling & Protocol Hardening)

**Status:** ✅ Complete

### Shipped
- Multi-format exporters: `py`, `sh`, `bat`, `js`, `exe` (PyInstaller spec + launcher)
- Base64 obfuscation with chunked Python-literal rendering
- `ExportManager.export()` (single file) and `export_bundle()` (portable `.zip` with `core/`)
- Dashboard `📦 Export Payload ▾` dropdown menu

### Protocol changes (breaking for old clients)
- **Sentinel framing** — command responses wrapped in `<<<RSC_BEGIN>>>...<<<RSC_END>>>`
- **Per-session response queue** — handler thread is sole `recv` reader;
  `send_command` consumes from `session.response_queue` (fixes multi-command desync)
- **Client keepalive guard** — suppressed during command execution
- **Exit interception** — `exit` / `quit` / `bye` cleanly terminates the client

### Tests
- `tests/test_e2e_export.py` — bundle → extract → connect → 2× command → clean exit
  (must be run from project root; sets `sys.path` itself)

## Phase 6 — Web Dashboard (Flask + SSE)

**Status:** ✅ Complete

### Shipped
- `web/` module — Flask app serving HTML dashboard + JSON API
- `web/stream.py` — EventBus for SSE fan-out to browser clients
- `web/state.py` — singleton wiring Server/SessionManager/ExportManager to the bus
- `web/app.py` — routes: sessions, server status/toggle, command, formats, export, download, SSE stream
- `web/templates/index.html` — dashboard layout (sidebar + terminal + command bar)
- `web/static/style.css` — dark monospace theme (muted red accent)
- `web/static/app.js` — SSE wiring, session selection, command send, export

### Endpoints
- `GET  /api/sessions` — active + inactive session list
- `GET  /api/server/status` — running, host, port, token, countdown
- `POST /api/server/toggle` — start/stop
- `POST /api/command` — body `{session_id, command, timeout?}` → `{ok, output}`
- `GET  /api/formats` — supported export formats
- `POST /api/export/<fmt>` — bundle to builds/, return path + size
- `GET  /api/download/<name>` — serve from builds/
- `GET  /api/logs/stream` — SSE for live log + session events

### Bug fixes during Phase 6
- `_process_message` now filters sentinel-framed responses so they don't
  duplicate in the UI (only the `send_command` return value reaches the terminal)

### Tests
- `tests/test_web_api.sh` — 14-step API smoke test (all passing)

### Legacy
- Tk dashboard (`dashboard/`) remains functional as a fallback

## Phase 6.5 — Auto-auth Payloads

**Status:** ✅ Complete

### Problem
Exported payloads required `--token <rotating-hmac>` at runtime.
Recipients don't have that token. Payloads weren't actually portable.

### Solution
- `ExportManager.export(..., embed_secret=True)` prepends
  `_RSC_MASTER_SECRET` + `_RSC_ROTATION_SECONDS` globals to the client
  source before Base64 encoding.
- `client/client.py` gains `--secret SECRET` flag and falls back to
  the embedded `_RSC_MASTER_SECRET` global if no CLI token is given.
- Client computes the *current* rotating token locally using
  `Auth(master_secret=...).token`. Token rotation "just works."

### Security tradeoff
The payload contains the master secret. Anyone with the payload can
generate valid tokens. Mitigation: `embed_secret=False` for operators
who want to keep requiring `--token`; rotate `auth_secret` in
`config.json` to invalidate all previously exported payloads.

### Changes
- `exporter/export_manager.py` — new `embed_secret` parameter
- `client/client.py` — `--secret` flag + embedded-secret fallback
  (removed the misleading `--token default='SHELL_ACCESS_2024'`)
- `tests/test_e2e_export.py` — removed `--token` from payload spawn;
  test now proves auto-auth end-to-end

### Tests
- 3× e2e pass with no token passed to the payload
- Manual: exported bundle run with `--host --port` only → authenticates
  → commands round-trip → clean exit

## Phase 7 — Payload Integrity + Decoy Tripwires

**Status:** ✅ Complete

### Goal
Make exported payloads resist casual extraction. A recipient who decodes
the Base64 blob and runs it standalone should get nothing. Attempts to
extract the "wrong" blob should notify the operator.

### Design (all in one file)
Single `payload_py.py` contains three Base64 blobs:

- **`_ACTUAL_B64`** — real client, prefixed with a UUID integrity check.
  Requires `_RSC_LAUNCHED` and matching `_RSC_UUID` globals, which are
  set only by the launcher. Missing → silent `sys.exit(1)`.
- **`_DECOY1_B64`** — plausible "RuntimeBootstrap" module. Referenced
  by the launcher (`_RSC_LOADER = _b64.b64decode(_DECOY1_B64)`) so it
  looks used, but never exec'd. If extracted standalone, prints harmless
  version info.
- **`_DECOY2_B64`** — diagnostic beacon. Referenced by the launcher
  (`_RSC_DIAG = ...`) but never exec'd during normal operation. If
  extracted and run standalone, connects to the server and sends
  `Nice try dumbass`.

### Server tripwire
`_process_message` detects `Nice try dumbass`, logs
`[!] TRIPWIRE — extraction attempt from <addr>` at ERROR level, and
disconnects the attacker session.

### Security model
- **Blocks casual extraction**: decode → run → silent exit(1), no connection
- **Detects lazy extraction**: running a decoy fires the tripwire
- **Raises effort cost**: decoys demand time to rule out
- **Accepts**: a determined RE who reads the payload and wraps the actual
  blob in `exec(code, {fake_globals})` will bypass 7a. That's Phase 8+
  territory (server-side signing).

### Changes
- `exporter/formats/py_exporter.py` — 3-blob generation + UUID check + decoy builders
- `modules/server.py` — tripwire detection in `_process_message`;
  `_disconnect_client` made idempotent (was double-firing on tripwire path)
- `tests/test_payload_integrity.py` — 7a test (UUID + silent exit)
- `tests/test_decoy_tripwire.py` — 7b test (decoys + tripwire)

### Known limitations
- Only `py` format currently gets 3-blob treatment. `sh`/`bat`/`js`/`exe`
  still use the single-blob format from Phase 5. Backfill is a future item.
- Old Phase 5/6.5 exports still work (no UUID check). Re-export after
  Phase 7 for the new protections.

## Phase 7.5 — Format Backfill (all 5 formats)

**Status:** ✅ Complete

### What
Extended Phase 7's integrity check + decoys to every launcher format.
All 5 exporters now emit the same 3-blob + UUID structure. The pattern
is identical across formats — only the outer wrapper differs.

### Shared helpers
- `exporter/payload_prep.py` — `prepare_payload()` (UUID + check),
  `build_decoy1()`, `build_decoy2()`. Single source of truth; every
  exporter calls these.

### Per-format backfill
- **py** — refactored to use shared helpers (no behavior change)
- **sh** — python program inside bash heredoc carries the 3 blobs
- **bat** — python program piped via PowerShell `-EncodedCommand`
- **js** — python program piped via Node spawn's stdin
- **exe** — companion launcher.py (frozen by PyInstaller) carries the blobs

### Tests
- `tests/test_backfill.py` — checks all 5 formats:
  - 3 distinct blobs per format
  - `_RSC_LAUNCHED` + `_RSC_UUID` present in the decoded python source
  - ACTUAL blob standalone exits 1 silently
  - bat: inner python compiles (decoded from UTF-16LE b64)
  - js: inner python compiles (unwrapped from template literal)
  - exe: spec compiles, launcher compiles, `__main__` guard intact
  - decoy2 fires tripwire on a live server

## Phase 8 — Persistent State + Payload Registry

**Status:** ✅ Complete

### Motivation
Phase 7 protected payloads from casual extraction, but:
- Payloads from different sessions weren't distinguishable
- Dashboard restarts broke all active clients (ephemeral secret)
- No way to revoke a payload after distribution

### Design
Persistent state lives under `~/.config/reverse-shell/servers/<instance>/`:
- `secret` — HMAC master secret (chmod 0600, survives restarts)
- `registry.json` — {"payloads": {uuid: {created_at, last_auth}}}
- `meta.json` — instance metadata

### Subtasks
- **8a** — `core/server_state.py`: persistent storage layer
- **8b** — `Server` uses `ServerState` secret when provided (legacy auth_secret
  path preserved for backward compat)
- **8c** — `ExportManager` registers each export + embeds `_RSC_SERVER_UUID`
  + `_RSC_PAYLOAD_UUID` in the payload prelude
- **8d** — Two-stage auth protocol:
    - `AUTH:<token>` — legacy (backward compat)
    - `AUTH:<server_uuid>:<payload_uuid>:<token>` — identity-aware
  Server validates server_uuid match + registry presence + token HMAC.
  Successful identity auth touches registry so prune_stale won't kill it.
- **8e** — Hibernation + revoke:
    - Client `RECONNECT_DELAY` = 30s, `_hibernate()` logs retry counter
    - `ServerState.revoke_payload(uuid)` removes from registry
    - Tk dashboard: right-click session → "Revoke payload"
    - Web dashboard: hover session row → × button → confirm → revoke

### Behavior changes
- **Old payloads** (Phase 5-7, no identity globals) still authenticate
  via the legacy path — no forced re-export
- **Dashboard restart** no longer invalidates old payloads — same secret
  loaded from disk
- **Revoked payloads** — next auth fails with "unregistered payload" log

### What this closes vs. doesn't
Closes:
- ✅ Payloads from other servers rejected (server_uuid + registry)
- ✅ Dashboard restart keeps clients connecting (persistent secret)
- ✅ Revoke a leaked payload (registry deletion → subsequent auths fail)

Doesn't close:
- ❌ Copied payload from THIS server still works (its UUID is in registry).
  Only true mitigation is single-use tokens (breaks hibernation) or machine
  fingerprinting (bypassable). Accepted limitation.

### Tests
- `tests/test_server_state.py` — 8a, 12 checkpoints
- `tests/test_server_state_wiring.py` — 8b, 5 checkpoints
- `tests/test_payload_registry.py` — 8c, 7 checkpoints
- `tests/test_two_stage_auth.py` — 8d, 6 scenarios
- `tests/test_revoke_hibernate.py` — 8e, 5 checkpoints
- `tests/test_web_revoke.py` — 8e-5, 5 checkpoints

## Phase 9 — Ngrok Integration

**Status:** ✅ Complete

### Motivation
Payloads connected to `Config().host` (localhost). Executing on a different
machine required manual `--host` with the ngrok URL — a UX cliff and a
common source of "why isn't this working?" moments.

### Solution
Ngrok integration at export time. When a payload is exported while an
ngrok TCP tunnel is running, the payload bakes in `_RSC_NGROK_HOST` +
`_RSC_NGROK_PORT`. Client uses those in priority order:

1. `--host` CLI arg (explicit override — always wins)
2. `_RSC_NGROK_HOST` from payload (baked at export)
3. Discovery (existing scan)

### Detection
- `core/ngrok.py`: `detect_tunnel()` queries ngrok's local admin API
  (`http://127.0.0.1:4040/api/tunnels`), picks first `tcp://` tunnel,
  returns `(host, port)` or `(None, None)` on any failure.
- `parse_ngrok_url()` handles both raw `host:port` and `tcp://host:port`.

### Configuration
`config.json` server section gains `ngrok_url` (default `None`). When set,
used instead of auto-detect (manual override for stable subdomains).

### Backwards compat
- No ngrok, no config → falls through to discovery (existing behavior)
- Old payloads (no `_RSC_NGROK_HOST`) → also fall through to discovery
- All existing tests pass unchanged

### Changes
- `core/ngrok.py` — new module, ~70 lines, pure stdlib
- `core/config.py` — `ngrok_url` server key (default `None`)
- `exporter/export_manager.py` — export() prepends `_RSC_NGROK_HOST`/`PORT`
  when a tunnel is available
- `client/client.py` — priority resolution: `--host` > embedded ngrok > discovery

### Tests
- `tests/test_ngrok.py` — 7 checkpoints (mocked admin API + edge cases)
- `tests/test_ngrok_integration.py` — 4 checkpoints (export → extract →
  connect without `--host` via embedded ngrok globals)

### Known limitation
Ngrok free tier rotates the URL/port on each restart. Payloads baked
against an old ngrok URL won't reconnect. Mitigation: re-export after
ngrok restart, or use a paid plan with a stable subdomain and set
`ngrok_url` in config.
