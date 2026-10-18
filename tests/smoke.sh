#!/usr/bin/env bash
# End-to-end check: build the stack, import generated fixtures, hit every endpoint.
set -euo pipefail
cd "$(dirname "$0")/.."

TOKEN="${DASHBOARD_TOKEN:-test}"
PORT="${API_PORT:-8090}"

python3 tests/fixtures/make_fixture.py data/fixtures >/dev/null

docker compose up -d db
for _ in $(seq 1 30); do
  [ "$(docker inspect --format '{{.State.Health.Status}}' nfix-contribution-db-1 2>/dev/null)" = healthy ] && break
  sleep 2
done

docker compose run --rm ingest python -m ingest.discord_ingest --dir /data/fixtures

DASHBOARD_TOKEN="$TOKEN" docker compose up -d --force-recreate api
for _ in $(seq 1 30); do
  curl -sf "localhost:$PORT/healthz" >/dev/null && break
  sleep 2
done

fail=0
check() {
  local path="$1" expect="${2:-200}" kind="${3:-json}"
  local code
  code=$(curl -s -o /tmp/nfix-smoke.json -w '%{http_code}' "localhost:$PORT$path")
  if [ "$code" != "$expect" ]; then
    echo "FAIL $path -> $code (expected $expect)"; fail=1; return
  fi
  if [ "$code" = "200" ] && [ "$kind" = "json" ] \
     && ! python3 -c 'import json;json.load(open("/tmp/nfix-smoke.json"))' 2>/dev/null; then
    echo "FAIL $path -> not json"; fail=1; return
  fi
  if [ "$code" = "200" ] && [ "$kind" = "html" ] && ! grep -q "<title>" /tmp/nfix-smoke.json; then
    echo "FAIL $path -> no html title"; fail=1; return
  fi
  echo "ok   $path -> $code"
}

check "/healthz"
check "/api/meta"
check "/api/overview?days=30"
check "/api/tags?sort=sum"
check "/api/tag/200"
check "/api/grind"
check "/api/versions"
check "/api/pairs"
check "/api/exits"
check "/api/trades?token=$TOKEN"
check "/api/trades" 401
check "/api/worst?n=3&token=$TOKEN"
check "/api/trade/aaa111bbb222/101?token=$TOKEN"
check "/" 200 html

[ "$fail" = 0 ] && echo "smoke: OK" || { echo "smoke: FAILED"; exit 1; }
