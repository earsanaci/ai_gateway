"""Home Assistant otomasyon olusturma/duzenleme/geri alma (onayli, yedekli)."""
import difflib
import hashlib
import json
import os
import re
import time
import uuid

from gateway.clients.homeassistant import ENTITY_RE, _is_sensitive, ha, ha_get
from gateway.config import APPROVAL_TTL, AUTO_BACKUP_DIR
from gateway.core import PENDING, audit, audited, mcp

AUTO_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


def _ha_automation_get(aid):
    r = ha.get(f"/config/automation/config/{aid}")
    if r.status_code == 404:
        return None
    if r.status_code in (401, 403):
        raise PermissionError("HA reddetti; yapay yonetici mi?")
    r.raise_for_status()
    return r.json()


def _entities_in(obj, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "entity_id":
                for e in (v if isinstance(v, list) else [v]):
                    if isinstance(e, str) and ENTITY_RE.match(e):
                        out.add(e)
            else:
                _entities_in(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _entities_in(v, out)
    return out


def _canon(cfg):
    return json.dumps(cfg, ensure_ascii=False, indent=2, sort_keys=True) if cfg is not None else ""


def _diff(old, new):
    return list(difflib.unified_diff(_canon(old).splitlines(), _canon(new).splitlines(),
                                     "mevcut", "yeni", lineterm="", n=2))[:200]


def _hash(cfg):
    return hashlib.sha256(_canon(cfg).encode()).hexdigest()


def _automation_pending(aid, old, new, mode, extra_note=""):
    states = {x["entity_id"]: x for x in ha_get("/states")}
    ents = sorted(_entities_in(new, set())) if new else []
    missing = [e for e in ents if e not in states]
    if missing:
        raise ValueError(f"Otomasyonda bulunmayan cihazlar var: {missing}")
    warnings = []
    ent_lines = []
    for e in ents:
        name = states[e].get("attributes", {}).get("friendly_name", e)
        ent_lines.append(f"{name} [{e}]")
        if _is_sensitive(e, name):
            warnings.append(f"DIKKAT: otomasyon hassas bir cihazi etkiliyor: {name}")
    alias = (new or old or {}).get("alias", aid)
    verb = {"create": "yeni otomasyon olusturulacak", "update": "mevcut otomasyon degistirilecek",
            "rollback": "otomasyon yedekteki haline geri dondurulecek",
            "delete": "otomasyon silinecek (olusturulmadan onceki haline donus)"}[mode]
    understood = f"Home Assistant'ta '{alias}' (id {aid}): {verb}."
    if ents:
        understood += " Ilgili cihazlar: " + ", ".join(ent_lines) + "."
    if extra_note:
        understood += " " + extra_note
    now = time.time()
    for k in [k for k, v in PENDING.items() if v["expires"] < now]:
        del PENDING[k]
    approval_id = uuid.uuid4().hex[:12]
    PENDING[approval_id] = {"kind": "ha_automation", "mode": mode, "automation_id": aid,
                            "old_hash": _hash(old), "new": new, "alias": alias,
                            "expires": now + APPROVAL_TTL}
    return {"approval_id": approval_id, "understood": understood, "warnings": warnings,
            "diff": _diff(old, new), "risk": "L2", "expires_in_seconds": APPROVAL_TTL,
            "note": "Uygulanmadi. Kullaniciya anlat, degisiklikleri goster ve acik onay iste."}


@mcp.tool()
@audited(risk="L0")
def homeassistant_propose_automation_change(config: dict, automation_id: str = "") -> dict:
    """Home Assistant'ta yeni otomasyon olusturmayi veya mevcut birini degistirmeyi ONERIR, uygulamaz.
    config: HA otomasyon yapilandirmasi (alias, description, triggers, conditions, actions, mode).
    automation_id bos ise yeni otomasyon olusturulur; doluysa o otomasyonun TAM yeni hali verilmelidir
    (once homeassistant_get_automation_config ile mevcut hali oku).
    Donen 'understood' ve 'diff'i kullaniciya anlat, acik onay iste, sonra
    homeassistant_apply_control ile uygula."""
    if ha is None:
        raise RuntimeError("Home Assistant yapilandirilmamis")
    if not isinstance(config, dict) or not config.get("alias"):
        raise ValueError("config bir sozluk olmali ve 'alias' icermeli")
    if not (config.get("triggers") or config.get("trigger")):
        raise ValueError("Otomasyonda en az bir tetikleyici (triggers) olmali")
    if not (config.get("actions") or config.get("action")):
        raise ValueError("Otomasyonda en az bir eylem (actions) olmali")
    if len(_canon(config)) > 50000:
        raise ValueError("Otomasyon cok buyuk")
    if automation_id:
        if not AUTO_ID_RE.match(automation_id):
            raise ValueError("Gecersiz otomasyon id")
        old = _ha_automation_get(automation_id)
        if old is None:
            raise ValueError(f"Otomasyon bulunamadi: {automation_id}")
        cfg = {**config, "id": automation_id}
        if _canon(old) == _canon(cfg):
            raise ValueError("Degisiklik yok")
        return _automation_pending(automation_id, old, cfg, "update")
    aid = str(int(time.time() * 1000))
    return _automation_pending(aid, None, {**config, "id": aid}, "create")


@mcp.tool()
@audited(risk="L0")
def homeassistant_propose_automation_rollback(automation_id: str) -> dict:
    """Bir otomasyonu gateway'in aldigi son yedekteki haline geri dondurmeyi ONERIR, uygulamaz.
    Otomasyon gateway ile yeni olusturulduysa geri alma = silme. Kullaniciya anlat, onay iste,
    sonra homeassistant_apply_control ile uygula."""
    if not AUTO_ID_RE.match(automation_id or ""):
        raise ValueError("Gecersiz otomasyon id")
    try:
        files = sorted(f for f in os.listdir(AUTO_BACKUP_DIR) if f.startswith(automation_id + "__"))
    except FileNotFoundError:
        files = []
    if not files:
        raise ValueError("Bu otomasyon icin gateway yedegi yok")
    with open(os.path.join(AUTO_BACKUP_DIR, files[-1]), encoding="utf-8") as f:
        backup = json.load(f)
    current = _ha_automation_get(automation_id)
    stamp = files[-1].split("__")[1].replace(".json", "")
    note = f"Kullanilacak yedek: {stamp} (UTC)."
    if backup.get("config") is None:
        if current is None:
            raise ValueError("Otomasyon zaten yok")
        return _automation_pending(automation_id, current, None, "delete", note)
    return _automation_pending(automation_id, current, backup["config"], "rollback", note)


def _apply_automation_change(approval_id, p):
    aid = p["automation_id"]
    current = _ha_automation_get(aid)
    if _hash(current) != p["old_hash"]:
        raise PermissionError("Otomasyon oneri sonrasi degismis; yeniden oner")
    os.makedirs(AUTO_BACKUP_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    bfile = f"{aid}__{stamp}.json"
    with open(os.path.join(AUTO_BACKUP_DIR, bfile), "w", encoding="utf-8") as f:
        json.dump({"automation_id": aid, "config": current, "approval_id": approval_id}, f,
                  ensure_ascii=False, indent=2)
    if p["mode"] == "delete":
        r = ha.delete(f"/config/automation/config/{aid}")
    else:
        r = ha.post(f"/config/automation/config/{aid}", json=p["new"])
    if r.status_code >= 400:
        try:
            msg = r.json().get("message", r.text)
        except Exception:
            msg = r.text
        raise ValueError(f"Home Assistant degisikligi reddetti: {msg[:500]}")
    time.sleep(2)
    after = _ha_automation_get(aid)
    if p["mode"] == "delete":
        verified = after is None
    else:
        verified = after is not None and _hash(after) == _hash(p["new"])
    state = None
    for x in ha_get("/states"):
        if x.get("entity_id", "").startswith("automation.") and str(x.get("attributes", {}).get("id")) == aid:
            state = {"entity_id": x["entity_id"], "state": x.get("state")}
            break
    audit({"event": "ha_automation_changed", "approval_id": approval_id, "automation_id": aid,
           "mode": p["mode"], "backup": bfile, "verified": verified, "risk": "L2"})
    return {"applied": True, "mode": p["mode"], "automation_id": aid, "alias": p["alias"],
            "verified": verified, "automation_entity": state, "backup": bfile,
            "rollback": "Geri almak icin homeassistant_propose_automation_rollback kullan."}

