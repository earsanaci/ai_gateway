"""Audit kaydi: hash zinciri + journald tanik kopyasi.

- Her satir, bir onceki satirin SHA-256 ozetini ("prev") tasir. Ortadan satir silmek veya
  degistirmek zinciri kirar ve `verify()` ile tespit edilir.
- Her satirin ozeti ayrica stderr'e "AUDIT {...}" olarak yazilir; systemd bunu journald'ye
  alir. Servis kullanicisi (aigw) journald'yi degistiremedigi icin bu kopya, dosyanin
  sonundan satir silinmesini ve zincirin bastan yazilmasini da ortaya cikarir
  (`python -m gateway.auditcheck`).
"""
import hashlib
import json
import os
import sys
import threading
import time

from gateway import config

GENESIS = "0" * 64
_lock = threading.Lock()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _last_line_bytes(path, block=8192):
    """Dosyanin son (bos olmayan) satirini ham bayt olarak dondurur."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            pos = f.tell()
            buf = b""
            while pos > 0:
                step = min(block, pos)
                pos -= step
                f.seek(pos)
                buf = f.read(step) + buf
                stripped = buf.rstrip(b"\n")
                idx = stripped.rfind(b"\n")
                if idx != -1:
                    return stripped[idx + 1:]
                block = min(block * 2, 1 << 22)
            return buf.rstrip(b"\n") or None
    except FileNotFoundError:
        return None


def _prev_hash():
    last = _last_line_bytes(config.AUDIT_LOG)
    return GENESIS if last is None else _sha(last)


def audit(entry):
    entry.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    with _lock:
        entry["prev"] = _prev_hash()
        data = json.dumps(entry, ensure_ascii=False).encode("utf-8")
        with open(config.AUDIT_LOG, "ab") as f:
            f.write(data + b"\n")
    witness = {"h": _sha(data), "ts": entry.get("ts"), "id": entry.get("request_id"),
               "what": entry.get("tool") or entry.get("event"), "res": entry.get("result")}
    print("AUDIT " + json.dumps(witness, ensure_ascii=False), file=sys.stderr, flush=True)


def verify(path=None):
    """Zinciri bastan sona dogrular. Dosyaya yazmaz."""
    path = path or config.AUDIT_LOG
    total = chained = unchained = 0
    first_chained = None
    prev_raw = None
    broken = []
    try:
        f = open(path, "rb")
    except FileNotFoundError:
        return {"ok": True, "total_lines": 0, "note": "Audit dosyasi henuz yok"}
    with f:
        for n, raw in enumerate(f, 1):
            raw = raw.rstrip(b"\n")
            if not raw.strip():
                continue
            total += 1
            try:
                obj = json.loads(raw)
            except ValueError:
                broken.append({"line": n, "reason": "gecersiz JSON"})
                prev_raw = raw
                continue
            p = obj.get("prev") if isinstance(obj, dict) else None
            if p is None:
                if first_chained is not None:
                    unchained += 1
            else:
                if first_chained is None:
                    first_chained = n
                chained += 1
                expected = GENESIS if prev_raw is None else _sha(prev_raw)
                if p != expected:
                    broken.append({"line": n, "reason": "onceki satirin ozeti uyusmuyor (satir silinmis veya degistirilmis)"})
            prev_raw = raw
    return {
        "ok": not broken,
        "total_lines": total,
        "chained_lines": chained,
        "legacy_lines_before_chain": (first_chained - 1) if first_chained else total,
        "unchained_lines_after_start": unchained,
        "first_chained_line": first_chained,
        "broken": broken[:20],
        "head": GENESIS if prev_raw is None else _sha(prev_raw),
        "limits": "Zincir, satir silme/degistirmeyi yakalar; dosyanin SONUNDAN kesmeyi ve tum zincirin "
                  "bastan yazilmasini ancak journald tanik kopyasi ile karsilastirma yakalar "
                  "(konsolda: python -m gateway.auditcheck).",
    }


def tail_lines(path, n, max_bytes=2 << 20):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            end = f.tell()
            start = max(0, end - max_bytes)
            f.seek(start)
            data = f.read()
    except FileNotFoundError:
        return []
    lines = data.split(b"\n")
    if start > 0:
        lines = lines[1:]  # ilk satir kesik olabilir
    return [l for l in lines if l.strip()][-n:]


def _short(v, limit=200):
    if isinstance(v, str):
        return v if len(v) <= limit else v[:limit] + "..."
    if isinstance(v, (dict, list)):
        s = json.dumps(v, ensure_ascii=False)
        return s if len(s) <= limit * 2 else s[:limit * 2] + "..."
    return v


CHANGE_EVENTS = {"ha_control_applied", "ha_automation_changed", "backup_job_changed", "deploy"}


def recent(limit=30, tool="", only_changes=False):
    limit = max(1, min(int(limit), 100))
    out = []
    for raw in reversed(tail_lines(config.AUDIT_LOG, 1000)):
        try:
            e = json.loads(raw)
        except ValueError:
            continue
        if tool and tool.lower() not in str(e.get("tool") or e.get("event") or "").lower():
            continue
        if only_changes and not (e.get("risk") in ("L1", "L2", "L3") or e.get("event") in CHANGE_EVENTS):
            continue
        e.pop("prev", None)
        p = e.get("params")
        if isinstance(p, dict):
            e["params"] = {k: _short(v) for k, v in p.items()}
        out.append({k: _short(v) if k != "params" else v for k, v in e.items()})
        if len(out) >= limit:
            break
    return out
