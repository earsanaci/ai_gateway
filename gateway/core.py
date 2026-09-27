"""Ortak parcalar: MCP sunucusu, audit, onay deposu."""
import functools
import json
import time
import uuid

from mcp.server.fastmcp import FastMCP

from gateway.config import AUDIT_LOG


def audit(entry):
    entry.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def audited(risk="L0"):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            entry = {"request_id": str(uuid.uuid4()), "tool": fn.__name__,
                     "risk": risk, "params": kwargs}
            t0 = time.time()
            try:
                result = fn(*args, **kwargs)
                entry["result"] = "ok"
                return result
            except Exception as e:
                entry["result"] = "error"
                entry["error"] = type(e).__name__
                raise
            finally:
                entry["duration_ms"] = int((time.time() - t0) * 1000)
                audit(entry)
        return wrapper
    return deco


def audited_async(risk="L0"):
    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            entry = {"request_id": str(uuid.uuid4()), "tool": fn.__name__,
                     "risk": risk, "params": kwargs}
            t0 = time.time()
            try:
                result = await fn(*args, **kwargs)
                entry["result"] = "ok"
                return result
            except Exception as e:
                entry["result"] = "error"
                entry["error"] = type(e).__name__
                raise
            finally:
                entry["duration_ms"] = int((time.time() - t0) * 1000)
                audit(entry)
        return wrapper
    return deco


GATEWAY_INSTRUCTIONS = (
    "Bu gateway kullanicinin evdeki sistemlerini (Proxmox, Home Assistant) yonetir. "
    "Kural: Herhangi bir sistemde bir seyi DEGISTIRMEDEN once (cihaz kontrolu, misafir "
    "baslatma/kapatma, yedek, yapilandirma degisikligi) ilgili propose aracini cagir ve "
    "kullaniciya ne anladigini ve ne yapacagini kisaca, sade Turkce ile anlat: hangi "
    "sistem, hangi cihaz/misafir, su anki durum, yapilacak degisiklik ve olasi etkisi. "
    "DIKKAT uyarilarini ve grup uyelerini atlamadan goster. Ardindan acik onay iste. "
    "Kullanici bu sohbette acikca onay vermeden hicbir apply aracini cagirma. "
    "Istek belirsizse tahmin etme, once sor. Okuma araclari icin onay gerekmez."
)
mcp = FastMCP("homelab", instructions=GATEWAY_INSTRUCTIONS, host="0.0.0.0",
              stateless_http=True, json_response=True)


def _pick(d, fields):
    return {k: d.get(k) for k in fields if k in d}



# Onay bekleyen islemler: approval_id -> plan. Tek surec, bellekte tutulur.
PENDING = {}


def cleanup_pending():
    now = time.time()
    for k in [k for k, v in PENDING.items() if v["expires"] < now]:
        del PENDING[k]
