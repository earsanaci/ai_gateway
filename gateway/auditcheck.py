"""Konsol araci: audit dosyasini journald tanik kopyasi ile karsilastirir (root olarak calistir).

  cd /opt/ai-gateway/src && PYTHONPATH=. /opt/ai-gateway/venv/bin/python -m gateway.auditcheck [--since "7 days ago"]
"""
import argparse
import hashlib
import json
import subprocess
import sys

from gateway import config
from gateway.audit import verify


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="30 days ago")
    args = ap.parse_args()

    problems = 0
    v = verify()
    print(f"Zincir: {v['total_lines']} satir, {v.get('chained_lines', 0)} zincirli, "
          f"{v.get('legacy_lines_before_chain', 0)} eski (zincirsiz), durum: {'TAMAM' if v['ok'] else 'BOZUK'}")
    for b in v.get("broken", []):
        print(f"  ! satir {b['line']}: {b['reason']}")
        problems += 1

    out = subprocess.run(["journalctl", "-u", "ai-gateway", "-o", "cat", "--no-pager", "--since", args.since],
                         capture_output=True, text=True)
    if out.returncode != 0:
        print("journalctl okunamadi (root olarak calistir):", out.stderr.strip())
        return 2
    witnesses = {}
    for line in out.stdout.splitlines():
        if line.startswith("AUDIT "):
            try:
                w = json.loads(line[6:])
                witnesses[w["h"]] = w
            except (ValueError, KeyError):
                pass

    file_hashes = {}
    with open(config.AUDIT_LOG, "rb") as f:
        for raw in f:
            raw = raw.rstrip(b"\n")
            if raw.strip():
                file_hashes[hashlib.sha256(raw).hexdigest()] = raw
    missing = [w for h, w in witnesses.items() if h not in file_hashes]
    print(f"Tanik kopya (journald, {args.since}): {len(witnesses)} kayit")
    if missing:
        problems += len(missing)
        print(f"  ! {len(missing)} kayit journald'de var ama audit dosyasinda yok veya degistirilmis:")
        for w in sorted(missing, key=lambda x: x.get("ts") or "")[:20]:
            print(f"    {w.get('ts')}  {w.get('what')}  ({w.get('res')})")
    if witnesses:
        first_ts = min(w.get("ts") or "" for w in witnesses.values())
        unw = 0
        for h, raw in file_hashes.items():
            try:
                e = json.loads(raw)
            except ValueError:
                continue
            if e.get("prev") and (e.get("ts") or "") >= first_ts and h not in witnesses:
                unw += 1
        if unw:
            print(f"  ? {unw} zincirli satirin journald tanigi yok (journal donmus olabilir; beklenmedikse incele)")

    print("SONUC:", "SORUN YOK" if not problems else f"{problems} SORUN")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
