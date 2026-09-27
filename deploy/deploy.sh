#!/usr/bin/env bash
# Gateway'i Git'teki son surume gunceller. Basarisiz olursa otomatik geri doner.
# Kullanim (ai-gateway konsolunda, root): /opt/ai-gateway/src/deploy/deploy.sh
set -euo pipefail
APP=/opt/ai-gateway
SRC=$APP/src
PY=$APP/venv/bin/python
cd "$SRC"

OLD=$(git rev-parse HEAD)
git fetch --quiet origin main
NEW=$(git rev-parse origin/main)
if [ "$OLD" = "$NEW" ] && [ "${1:-}" != "--force" ]; then
  echo "Zaten guncel: $(git log -1 --oneline)"; exit 0
fi
echo "Guncelleniyor: $(git log -1 --format='%h %s' "$OLD") -> $(git log -1 --format='%h %s' "$NEW")"
git reset --quiet --hard "$NEW"

rollback() {
  echo "HATA: $1 -> onceki surume donuluyor ($OLD)"
  git reset --quiet --hard "$OLD"
  $APP/venv/bin/pip install -q -r requirements.txt || true
  cp deploy/ai-gateway.service /etc/systemd/system/ai-gateway.service
  systemctl daemon-reload; systemctl restart ai-gateway
  exit 1
}

$APP/venv/bin/pip install -q -r requirements.txt || rollback "bagimliliklar kurulamadi"
PYTHONPATH="$SRC" $PY -m compileall -q gateway || rollback "kod derlenemedi"

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

echo "Tamam: $(git log -1 --oneline) | $COUNT arac | servis calisiyor"
