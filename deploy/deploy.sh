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
# Betigin kendisi degistiyse, kurulumdan once YENI surumle yeniden basla (eski betik yeni
# kurallari bilmez; orn. HTTPS saglik kontrolu). Yalnizca bir kez yapilir.
if [ -z "${DEPLOY_REEXEC:-}" ] && ! git diff --quiet "$OLD" "$NEW" -- deploy/deploy.sh; then
  echo "deploy.sh guncellenmis; yeni surumle yeniden baslatiliyor"
  TMP_SELF=$(mktemp)
  git show "$NEW:deploy/deploy.sh" > "$TMP_SELF"
  DEPLOY_REEXEC=1 exec bash "$TMP_SELF" "$@"
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

# Porta cevap gelene kadar (en fazla ~12sn) dener; TLS baslatmasi HTTP'den yavas olabilir.
wait_healthy() {
  local proto=http
  grep -q '^GW_TLS_CERT=' /etc/ai-gateway/tls.env 2>/dev/null && proto=https
  local code=000
  for _ in 1 2 3 4 5 6; do
    sleep 2
    code=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 2 "$proto://127.0.0.1:8765/mcp" || true)
    [ "$code" = "401" ] && { echo "$proto"; return 0; }
  done
  echo "$proto $code"; return 1
}

rollback() {
  echo "HATA: $1 -> onceki surume donuluyor (${OLD:0:7})"
  log_audit rolled_back "$1"
  git reset --quiet --hard "$OLD"
  $APP/venv/bin/pip install -q -r requirements.txt || true
  cp deploy/ai-gateway.service /etc/systemd/system/ai-gateway.service
  systemctl daemon-reload; systemctl restart ai-gateway
  systemctl is-active --quiet ai-gateway || echo "UYARI: geri donus sonrasi servis hala ayakta degil, elle bak: systemctl status ai-gateway"
  wait_healthy >/dev/null || echo "UYARI: geri donus sonrasi saglik kontrolu de basarisiz, elle bak: journalctl -u ai-gateway -n 40"
  exit 1
}

set -a; for f in /etc/ai-gateway/*.env; do . "$f"; done; set +a
COUNT=$(PYTHONPATH="$SRC" GW_AUDIT_LOG=/dev/null $PY -c \
  "import asyncio, gateway.__main__; from gateway.core import mcp; print(len(asyncio.run(mcp.list_tools())))") \
  || rollback "araclar yuklenemedi"

# Yeni servis dosyasinin istedigi EnvironmentFile'lar mevcut mu, kurmadan once kontrol et
MISSING=""
for f in $(grep -oP '(?<=EnvironmentFile=)\S+' deploy/ai-gateway.service); do
  case "$f" in -*) continue ;; esac   # "-" ile baslayanlar istege bagli (orn. tls.env, pbs.env)
  [ -f "$f" ] || MISSING="$MISSING $f"
done
[ -z "$MISSING" ] || rollback "eksik ayar dosyasi(lari):$MISSING (once olustur, sonra tekrar dene)"

cp deploy/ai-gateway.service /etc/systemd/system/ai-gateway.service
systemctl daemon-reload
systemctl restart ai-gateway
sleep 2
systemctl is-active --quiet ai-gateway || rollback "servis baslamadi: $(journalctl -u ai-gateway -n 5 --no-pager -o cat | tr '\n' ' ')"
RESULT=$(wait_healthy) || rollback "saglik kontrolu basarisiz ($RESULT)"

log_audit ok "$COUNT arac"
echo "Tamam: $(git log -1 --oneline) | $COUNT arac | servis calisiyor"
