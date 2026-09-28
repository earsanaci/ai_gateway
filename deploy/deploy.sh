#!/usr/bin/env bash
# Gateway'i Git'teki son surume gunceller. Once yeni surumu ayri bir klasorde
# testlerden gecirir; testler gecmezse canli koda hic dokunmaz. Kurulumdan
# sonra bir sey bozulursa otomatik olarak onceki surume doner.
# Kullanim (ai-gateway konsolunda, root): /opt/ai-gateway/src/deploy/deploy.sh [--force]
set -euo pipefail
APP=/opt/ai-gateway
SRC=$APP/src
PY=$APP/venv/bin/python
AUDIT=/var/log/ai-gateway/deploy.jsonl  # audit.jsonl zincirli; betik ona yazmaz
cd "$SRC"

log_audit() {
  printf '{"event":"deploy","result":"%s","from":"%s","to":"%s","detail":"%s","ts":"%s"}\n' \
    "$1" "${OLD:0:7}" "${NEW:0:7}" "$2" "$(date -u +%Y-%m-%dT%H:%M:%S+0000)" >> "$AUDIT" || true
}

OLD=$(git rev-parse HEAD)
git fetch --quiet origin main
NEW=$(git rev-parse origin/main)
if [ "$OLD" = "$NEW" ] && [ "${1:-}" != "--force" ]; then
  echo "Zaten guncel: $(git log -1 --oneline)"; exit 0
fi
echo "Guncelleniyor: $(git log -1 --format='%h %s' "$OLD") -> $(git log -1 --format='%h %s' "$NEW")"

# 1) Yeni surumu ayri bir klasorde test et; testler gecmeden canli koda dokunma
TEST=$(mktemp -d)
trap 'rm -rf "$TEST"' EXIT
git worktree add --quiet --detach "$TEST" "$NEW"
$APP/venv/bin/pip install -q -r "$TEST/requirements-dev.txt" \
  || { log_audit rejected "bagimliliklar kurulamadi"; git worktree remove --force "$TEST"; echo "Reddedildi: bagimliliklar"; exit 1; }
if ! (cd "$TEST" && PYTHONPATH="$TEST" $PY -m pytest -q -p no:cacheprovider); then
  log_audit rejected "testler basarisiz"
  git worktree remove --force "$TEST"
  echo "Reddedildi: testler basarisiz, canli surum degismedi"
  exit 1
fi
git worktree remove --force "$TEST"

# 2) Kur
git reset --quiet --hard "$NEW"

rollback() {
  echo "HATA: $1 -> onceki surume donuluyor (${OLD:0:7})"
  log_audit rolled_back "$1"
  git reset --quiet --hard "$OLD"
  $APP/venv/bin/pip install -q -r requirements.txt || true
  cp deploy/ai-gateway.service /etc/systemd/system/ai-gateway.service
  systemctl daemon-reload; systemctl restart ai-gateway
  exit 1
}

set -a; for f in /etc/ai-gateway/*.env; do . "$f"; done; set +a
COUNT=$(PYTHONPATH="$SRC" GW_AUDIT_LOG=/dev/null $PY -c \
  "import asyncio, gateway.__main__; from gateway.core import mcp; print(len(asyncio.run(mcp.list_tools())))") \
  || rollback "araclar yuklenemedi"

cp deploy/ai-gateway.service /etc/systemd/system/ai-gateway.service
systemctl daemon-reload
systemctl restart ai-gateway
sleep 4
systemctl is-active --quiet ai-gateway || rollback "servis baslamadi"
CODE=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8765/mcp || true)
[ "$CODE" = "401" ] || rollback "saglik kontrolu basarisiz (HTTP $CODE)"

log_audit ok "$COUNT arac"
echo "Tamam: $(git log -1 --oneline) | $COUNT arac | servis calisiyor"
