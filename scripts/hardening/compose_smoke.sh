#!/usr/bin/env bash
# Phase 20 Docker validation: build every image, start the compose stack with throw-away secrets, wait
# for the health checks, then check the running containers end to end through the web app.
# Used by CI (docker job). Needs docker compose v2. Leaves nothing running (trap tears down).
set -euo pipefail
cd "$(dirname "$0")/../.."

export COMPOSE_PROJECT_NAME=pulsetrader-smoke
env_file=$(mktemp)
cat > "$env_file" <<EOF
POSTGRES_PASSWORD=$(openssl rand -hex 16)
JWT_SECRET=$(openssl rand -hex 32)
LIVE_INGEST_TOKEN=$(openssl rand -hex 32)
EOF
dc() { docker compose --env-file "$env_file" "$@"; }
cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then dc ps; dc logs --tail 80; fi
  dc down -v --remove-orphans >/dev/null 2>&1
  rm -f "$env_file"
  exit "$status"
}
trap cleanup EXIT

dc build
dc up -d postgres redis ml-service api web

wait_healthy() {
  local svc=$1
  for _ in $(seq 1 60); do
    state=$(docker inspect -f '{{.State.Health.Status}}' "$(dc ps -q "$svc")" 2>/dev/null || echo starting)
    [ "$state" = healthy ] && { echo "$svc healthy"; return 0; }
    sleep 5
  done
  echo "$svc did not become healthy (last state: $state)"; return 1
}
for svc in postgres redis ml-service api web; do wait_healthy "$svc"; done

fail() { echo "SMOKE FAIL: $*"; exit 1; }
web=http://localhost:3000
curl -fsS "$web/api/health" | grep -q '"ok"' || fail "API health through the web proxy"
ready=$(curl -sS "$web/api/health/ready")
echo "$ready" | grep -q '"database":true' || fail "readiness: database ($ready)"
echo "$ready" | grep -q '"redis":true' || fail "readiness: redis ($ready)"
curl -fsS "http://localhost:8000/health" >/dev/null || fail "ML service health"
code=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:3001/api/health || true)
[ "$code" = 000 ] || fail "API port 3001 is published (got HTTP $code); it must only be reachable via the web app"
curl -fsSI "$web/" | grep -qi "content-security-policy: .*nonce-" || fail "page CSP nonce"
# a user can register and log in through the web app; private routes need the session
jar=$(mktemp)
curl -fsS -c "$jar" -H 'content-type: application/json' \
  -d '{"email":"smoke@example.test","password":"correct horse 123"}' "$web/api/auth/register" >/dev/null \
  || fail "register"
curl -fsS -c "$jar" -b "$jar" -H 'content-type: application/json' \
  -d '{"email":"smoke@example.test","password":"correct horse 123"}' "$web/api/auth/login" >/dev/null \
  || fail "login"
curl -fsS -b "$jar" "$web/api/auth/me" | grep -q smoke@example.test || fail "session"
[ "$(curl -s -o /dev/null -w '%{http_code}' "$web/api/watchlists")" = 401 ] || fail "anonymous access"
rm -f "$jar"
# containers run as non-root
for svc in ml-service api web; do
  uid=$(docker exec "$(dc ps -q "$svc")" id -u)
  [ "$uid" != 0 ] || fail "$svc runs as root"
done
echo "compose smoke test passed"
