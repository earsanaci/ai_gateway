"""Home Assistant cihaz kontrolu (her zaman onayli)."""
import time
import uuid

from gateway.clients.homeassistant import _check_entity, _is_sensitive, ha_get, ha_post
from gateway.config import APPROVAL_TTL
from gateway.core import PENDING, audit, audited, mcp

# ---------------------------------------------------------------- Home Assistant kontrol (her zaman onayli)
# Kural: HA'da HER kontrol islemi once onerilir (ne anlasildigi ve ne yapilacagi
# gosterilir), kullanici onaylamadan uygulanmaz. Hassas cihazlar DIKKAT ile isaretlenir,
# gruplar uyeleriyle birlikte acilir.
HA_SERVICES = {
    "light": {"turn_on", "turn_off", "toggle"},
    "switch": {"turn_on", "turn_off", "toggle"},
    "fan": {"turn_on", "turn_off", "toggle"},
    "media_player": {"turn_on", "turn_off", "media_play", "media_pause", "media_stop",
                     "volume_set", "volume_mute", "media_next_track", "media_previous_track"},
    "vacuum": {"start", "pause", "stop", "return_to_base"},
    "climate": {"turn_on", "turn_off", "set_temperature", "set_hvac_mode"},
    "cover": {"open_cover", "close_cover", "stop_cover"},
    "scene": {"turn_on"},
    "script": {"turn_on"},
    "automation": {"turn_on", "turn_off", "trigger"},
}
HA_DATA_KEYS = {"brightness_pct", "color_temp_kelvin", "temperature", "hvac_mode",
                "volume_level", "is_volume_muted"}


@mcp.tool()
@audited(risk="L0")
def homeassistant_propose_control(actions: list[dict]) -> dict:
    """Home Assistant'ta bir veya birden fazla cihaz kontrolunu ONERIR, uygulamaz.
    actions: [{"entity_id": "light.x", "service": "turn_on", "data": {"brightness_pct": 50}}, ...]
    Donen 'understood' listesini kullaniciya aynen anlat (ne anladigini ve ne yapacagini),
    DIKKAT uyarilarini ve grup uyelerini goster, acik onay iste. Onay gelirse
    homeassistant_apply_control'u approval_id ile cagir. Onaysiz asla uygulama."""
    if not actions or len(actions) > 20:
        raise ValueError("1 ile 20 arasi islem verilmeli")
    states = {x["entity_id"]: x for x in ha_get("/states")}
    plan, lines, warnings = [], [], []
    for a in actions:
        eid = a.get("entity_id", "")
        service = a.get("service", "")
        data = a.get("data") or {}
        _check_entity(eid)
        domain = eid.split(".")[0]
        if service not in HA_SERVICES.get(domain, set()):
            raise ValueError(f"{eid}: '{service}' izinli degil. Izinli: {sorted(HA_SERVICES.get(domain, []))}")
        bad = set(data) - HA_DATA_KEYS
        if bad:
            raise ValueError(f"Izinli olmayan parametre: {sorted(bad)}")
        st = states.get(eid)
        if st is None:
            raise ValueError(f"{eid} bulunamadi")
        name = st.get("attributes", {}).get("friendly_name", eid)
        members = st.get("attributes", {}).get("entity_id") or []
        member_info = []
        for m in members:
            ms = states.get(m, {})
            mname = ms.get("attributes", {}).get("friendly_name", m)
            sens = _is_sensitive(m, mname)
            member_info.append({"entity_id": m, "name": mname, "state": ms.get("state"), "sensitive": sens})
            if sens:
                warnings.append(f"DIKKAT: '{name}' grubu hassas cihaz iceriyor: {mname}")
        sens = _is_sensitive(eid, name)
        if sens:
            warnings.append(f"DIKKAT: {name} hassas bir cihaz")
        extra = f" ({', '.join(f'{k}={v}' for k, v in data.items())})" if data else ""
        lines.append(f"{name} [{eid}], su an '{st.get('state')}' -> {domain}.{service}{extra}"
                     + (f"; grup uyeleri: {', '.join(i['name'] for i in member_info)}" if member_info else ""))
        plan.append({"entity_id": eid, "name": name, "domain": domain, "service": service,
                     "data": data, "current_state": st.get("state"),
                     "sensitive": sens, "group_members": member_info})
    now = time.time()
    for k in [k for k, v in PENDING.items() if v["expires"] < now]:
        del PENDING[k]
    approval_id = uuid.uuid4().hex[:12]
    PENDING[approval_id] = {"kind": "ha_control", "plan": plan, "expires": now + APPROVAL_TTL}
    return {"approval_id": approval_id, "understood": lines, "warnings": warnings,
            "risk": "L2" if warnings else "L1", "expires_in_seconds": APPROVAL_TTL,
            "note": "Uygulanmadi. Kullaniciya anlat ve acik onay iste."}


@mcp.tool()
@audited(risk="L1")
def homeassistant_apply_control(approval_id: str) -> dict:
    """homeassistant_propose_control, homeassistant_propose_automation_change veya
    homeassistant_propose_automation_rollback ile onerilmis ve KULLANICI TARAFINDAN
    ONAYLANMIS islemi uygular ve sonucu dogrular. Yalnizca acik onaydan sonra cagir."""
    p = PENDING.get(approval_id)
    if p is None or p.get("kind") not in ("ha_control", "ha_automation"):
        raise PermissionError("Onay bulunamadi, kullanildi veya suresi doldu")
    PENDING.pop(approval_id, None)
    if p["expires"] < time.time():
        raise PermissionError("Onayin suresi doldu; islemi yeniden oner")
    if p["kind"] == "ha_automation":
        from gateway.tools.ha_automations import _apply_automation_change
        return _apply_automation_change(approval_id, p)
    results = []
    for a in p["plan"]:
        ha_post(f"/services/{a['domain']}/{a['service']}", {"entity_id": a["entity_id"], **a["data"]})
    time.sleep(2)
    for a in p["plan"]:
        st = ha_get(f"/states/{a['entity_id']}")
        results.append({"name": a["name"], "entity_id": a["entity_id"],
                        "before": a["current_state"], "after": st.get("state")})
    audit({"event": "ha_control_applied", "approval_id": approval_id,
           "actions": [{"entity_id": a["entity_id"], "service": a["service"], "data": a["data"]}
                       for a in p["plan"]]})
    return {"applied": True, "results": results}

