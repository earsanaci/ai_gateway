"""Home Assistant entity yeniden adlandirma / entity_id degistirme / alan tasima (onayli).

Bu islemler HA'da servis degil, entity ve cihaz kayitlarinda (registry) yapilir; yalnizca
WebSocket API ile mumkundur. Kural ayni: once onerilir, kullanici onaylarsa
homeassistant_apply_control ile uygulanir ve dogrulanir.
"""
import time
import uuid

from gateway.clients.homeassistant import ENTITY_RE, _check_entity, _is_sensitive, ha, ha_get, ha_ws
from gateway.config import APPROVAL_TTL
from gateway.core import PENDING, audit, audited, mcp

_TR = str.maketrans("ıİöÖüÜşŞçÇğĞ", "iioouussccgg")


def _norm(s):
    return (s or "").translate(_TR).casefold().strip()


def _resolve_area(area, areas):
    for a in areas:
        if area == a["area_id"] or _norm(area) == _norm(a["name"]):
            return a
    raise ValueError(f"Alan bulunamadi: '{area}'. Mevcut alanlar: {sorted(a['name'] for a in areas)}")


def _automations_using(entity_id):
    """entity_id'yi metin olarak iceren otomasyonlar (id ile kayitli olanlar)."""
    found = []
    for st in ha_get("/states"):
        if not st.get("entity_id", "").startswith("automation."):
            continue
        aid = st.get("attributes", {}).get("id")
        if not aid:
            continue
        r = ha.get(f"/config/automation/config/{aid}")
        if r.status_code == 200 and entity_id in r.text:
            found.append({"id": str(aid), "name": st["attributes"].get("friendly_name", st["entity_id"])})
    return found


@mcp.tool()
@audited(risk="L0")
def homeassistant_propose_entity_update(entity_id: str, new_entity_id: str = "", name: str = "",
                                        area: str = "", move_device: bool = True) -> dict:
    """Bir entity'nin gorunen adini, entity_id'sini ve/veya alanini (oda) degistirmeyi ONERIR, uygulamaz.
    entity_id: mevcut id (orn. binary_sensor.koridor_hareket).
    new_entity_id: yeni id, ayni domain (bos = degismez).
    name: yeni gorunen ad (bos = degismez).
    area: alan adi veya area_id (orn. "Mutfak"; bos = degismez).
    move_device: area verildiyse entity'nin bagli oldugu cihazi da o alana tasir (varsayilan evet).
    Eski entity_id'yi kullanan otomasyonlar uyari olarak listelenir; id degisirse onlari
    homeassistant_propose_automation_change ile ayrica guncellemek gerekir.
    Donen 'understood' ve uyarilari kullaniciya anlat, acik onay iste, sonra
    homeassistant_apply_control ile uygula."""
    if ha is None:
        raise RuntimeError("Home Assistant yapilandirilmamis")
    _check_entity(entity_id)
    if not (new_entity_id or name or area):
        raise ValueError("Degistirilecek bir sey verilmedi (new_entity_id, name veya area)")
    if new_entity_id:
        if not ENTITY_RE.match(new_entity_id):
            raise ValueError("Gecersiz new_entity_id")
        if new_entity_id.split(".")[0] != entity_id.split(".")[0]:
            raise ValueError("new_entity_id ayni domain'de olmali")
        if new_entity_id == entity_id:
            new_entity_id = ""
    if name and len(name) > 100:
        raise ValueError("Ad cok uzun")

    ent, areas, entities, devices = ha_ws([
        {"type": "config/entity_registry/get", "entity_id": entity_id},
        {"type": "config/area_registry/list"},
        {"type": "config/entity_registry/list"},
        {"type": "config/device_registry/list"},
    ])
    if new_entity_id and any(e["entity_id"] == new_entity_id for e in entities):
        raise ValueError(f"{new_entity_id} zaten kullaniliyor")
    device = next((d for d in devices if d["id"] == ent.get("device_id")), None) if ent.get("device_id") else None
    area_by_id = {a["area_id"]: a["name"] for a in areas}
    cur_name = ent.get("name") or ent.get("original_name") or entity_id
    eff_area_id = ent.get("area_id") or (device or {}).get("area_id")

    ent_changes, dev_changes, lines = {}, {}, []
    if new_entity_id:
        ent_changes["new_entity_id"] = new_entity_id
        lines.append(f"entity_id: {entity_id} -> {new_entity_id}")
    if name and name != ent.get("name"):
        ent_changes["name"] = name
        lines.append(f"gorunen ad: '{cur_name}' -> '{name}'")
    target = None
    if area:
        target = _resolve_area(area, areas)
        if ent.get("area_id") != target["area_id"]:
            ent_changes["area_id"] = target["area_id"]
        if move_device and device and device.get("area_id") != target["area_id"]:
            dev_changes["area_id"] = target["area_id"]
        if ent_changes.get("area_id") or dev_changes:
            lines.append(f"alan: {area_by_id.get(eff_area_id, 'yok')} -> {target['name']}"
                         + (" (cihaz da tasinacak)" if dev_changes else ""))
    if not ent_changes and not dev_changes:
        raise ValueError("Degisiklik yok")

    warnings = []
    if _is_sensitive(entity_id, cur_name):
        warnings.append(f"DIKKAT: {cur_name} hassas bir cihaz")
    if dev_changes and device:
        others = [e["entity_id"] for e in entities
                  if e.get("device_id") == device["id"] and e["entity_id"] != entity_id and not e.get("area_id")]
        if others:
            warnings.append("Cihazla birlikte su entity'ler de yeni alana gecer: " + ", ".join(sorted(others)))
    users = _automations_using(entity_id) if new_entity_id else []
    if users:
        warnings.append("Eski entity_id'yi kullanan otomasyonlar id degisince calismaz, ayrica "
                        "guncellenmeli: " + ", ".join(f"{u['name']} ({u['id']})" for u in users))

    dev_label = f", cihaz '{device.get('name_by_user') or device.get('name')}'" if device else ""
    understood = (f"Home Assistant'ta '{cur_name}' [{entity_id}]{dev_label} icin kayit degisikligi: "
                  + "; ".join(lines) + ".")
    now = time.time()
    for k in [k for k, v in PENDING.items() if v["expires"] < now]:
        del PENDING[k]
    approval_id = uuid.uuid4().hex[:12]
    PENDING[approval_id] = {
        "kind": "ha_entity", "entity_id": entity_id, "device_id": (device or {}).get("id"),
        "ent_changes": ent_changes, "dev_changes": dev_changes,
        "old": {"name": ent.get("name"), "area_id": ent.get("area_id"),
                "device_area_id": (device or {}).get("area_id")},
        "expires": now + APPROVAL_TTL,
    }
    return {"approval_id": approval_id, "understood": understood, "warnings": warnings,
            "automations_using_entity": users, "risk": "L2", "expires_in_seconds": APPROVAL_TTL,
            "note": "Uygulanmadi. Kullaniciya anlat ve acik onay iste."}


def _apply_entity_update(approval_id, p):
    eid = p["entity_id"]
    (ent,) = ha_ws([{"type": "config/entity_registry/get", "entity_id": eid}])
    if ent.get("name") != p["old"]["name"] or ent.get("area_id") != p["old"]["area_id"]:
        raise PermissionError("Entity oneri sonrasi degismis; yeniden oner")
    cmds = []
    if p["dev_changes"]:
        cmds.append({"type": "config/device_registry/update", "device_id": p["device_id"], **p["dev_changes"]})
    if p["ent_changes"]:
        cmds.append({"type": "config/entity_registry/update", "entity_id": eid, **p["ent_changes"]})
    ha_ws(cmds)
    final_id = p["ent_changes"].get("new_entity_id", eid)
    (after,) = ha_ws([{"type": "config/entity_registry/get", "entity_id": final_id}])
    verified = (after.get("entity_id") == final_id
                and ("name" not in p["ent_changes"] or after.get("name") == p["ent_changes"]["name"])
                and ("area_id" not in p["ent_changes"] or after.get("area_id") == p["ent_changes"]["area_id"]))
    audit({"event": "ha_entity_updated", "approval_id": approval_id, "entity_id": eid,
           "new_entity_id": final_id, "ent_changes": p["ent_changes"], "dev_changes": p["dev_changes"],
           "old": p["old"], "verified": verified, "risk": "L2"})
    return {"applied": True, "entity_id": final_id, "previous_entity_id": eid,
            "name": after.get("name") or after.get("original_name"), "area_id": after.get("area_id"),
            "verified": verified,
            "rollback": "Geri almak icin ayni araci eski degerlerle yeniden oner.", "old": p["old"]}
