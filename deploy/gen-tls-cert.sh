#!/usr/bin/env bash
# Gateway icin kendinden imzali TLS sertifikasi uretir (10 yil gecerli).
# Kullanim (ai-gateway konsolunda, root): deploy/gen-tls-cert.sh 192.168.7.18 [ek-IP-veya-ad ...]
set -euo pipefail
[ $# -ge 1 ] || { echo "Kullanim: $0 <IP> [ek adres ...]"; exit 1; }
OUT=/etc/ai-gateway/tls
mkdir -p "$OUT"
SAN="IP:$1"
for extra in "${@:2}"; do
  if [[ "$extra" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then SAN="$SAN,IP:$extra"; else SAN="$SAN,DNS:$extra"; fi
done
openssl req -x509 -nodes -newkey ed25519 -days 3650 \
  -keyout "$OUT/gateway.key" -out "$OUT/gateway.crt" \
  -subj "/CN=ai-gateway" -addext "subjectAltName=$SAN"
chgrp aigw "$OUT" "$OUT"/gateway.key "$OUT"/gateway.crt
chmod 750 "$OUT"; chmod 640 "$OUT/gateway.key" "$OUT/gateway.crt"
echo "Olusturuldu: $OUT/gateway.crt ($SAN)"
echo "Parmak izi (SHA256): $(openssl x509 -in "$OUT/gateway.crt" -noout -fingerprint -sha256)"
