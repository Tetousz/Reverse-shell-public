#!/usr/bin/env bash
# Phase 6c API smoke test. Requires the web server to already be running
# on http://127.0.0.1:8000 (or set BASE_URL).
#
#   python3 -m web.main &
#   bash tests/test_web_api.sh

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
pass=0; fail=0

check() {
    if [ "$2" = "$3" ]; then
        echo "  PASS: $1"
        pass=$((pass+1))
    else
        echo "  FAIL: $1"
        echo "    expected: $3"
        echo "    got:      $2"
        fail=$((fail+1))
    fi
}

echo "=== 1. sessions empty ==="
r=$(curl -s "$BASE_URL/api/sessions")
check "sessions initial" "$r" "[]"

echo "=== 2. server status (stopped) ==="
r=$(curl -s "$BASE_URL/api/server/status" | python3 -c "import sys,json; print(json.load(sys.stdin)['running'])")
check "running before toggle" "$r" "False"

echo "=== 3. toggle server ON ==="
r=$(curl -s -X POST "$BASE_URL/api/server/toggle" | python3 -c "import sys,json; print(json.load(sys.stdin)['running'])")
check "running after toggle" "$r" "True"

echo "=== 4. server status (running) ==="
r=$(curl -s "$BASE_URL/api/server/status" | python3 -c "import sys,json; print(json.load(sys.stdin)['running'])")
check "running after start" "$r" "True"
r=$(curl -s "$BASE_URL/api/server/status" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['token']))")
check "token present (32 chars)" "$r" "32"

echo "=== 5. formats ==="
r=$(curl -s "$BASE_URL/api/formats")
check "formats list" "$r" '["bat","exe","js","py","sh"]'

echo "=== 6. export py ==="
r=$(curl -s -X POST "$BASE_URL/api/export/py" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['ok'], d['name'])")
check "export py" "$r" "True payload_py.zip"

echo "=== 7. export unknown format -> 400 ==="
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/api/export/xyz")
check "export xyz -> 400" "$code" "400"

echo "=== 8. command with fake session -> ok=false ==="
r=$(curl -s -X POST -H 'Content-Type: application/json' \
    -d '{"session_id": 9999, "command": "echo hi"}' \
    "$BASE_URL/api/command" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['ok'])")
check "fake session rejected" "$r" "False"

echo "=== 9. command missing fields -> 400 ==="
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST -H 'Content-Type: application/json' -d '{}' "$BASE_URL/api/command")
check "missing fields -> 400" "$code" "400"

echo "=== 10. download exported zip -> 200 ==="
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/api/download/payload_py.zip")
check "download payload_py.zip" "$code" "200"

echo "=== 11. download nonexistent -> 404 ==="
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/api/download/does_not_exist.zip")
check "missing file -> 404" "$code" "404"

# Path traversal via URL is rejected by the route (Werkzeug's <name> converter
# refuses slashes), so the URL-decoded path normalizes away from our handler.
# The handler's own relative_to(builds) guard is unreachable via HTTP but
# stays as defense-in-depth if the converter is ever changed to <path:name>.
echo "=== 12. URL path traversal -> 404 (route rejected) ==="
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/api/download/..%2F..%2Fetc%2Fpasswd")
check "path traversal rejected by route" "$code" "404"

echo "=== 13. toggle server OFF ==="
r=$(curl -s -X POST "$BASE_URL/api/server/toggle" | python3 -c "import sys,json; print(json.load(sys.stdin)['running'])")
check "running after toggle off" "$r" "False"

echo
echo "=== RESULT: $pass passed, $fail failed ==="
[ "$fail" = "0" ] || exit 1
