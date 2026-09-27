"""Home Assistant salt-okunur araclar (L0)."""
import re
from datetime import datetime, timezone

from gateway.clients.homeassistant import (DOWN_STATES, _check_entity, _device_info, _since,
                                           ha, ha_call, ha_get)
from gateway.core import _pick, audited, audited_async, mcp

@mcp.tool()
@audited_async()
async def homeassistant_get_live_context() -> str:
    """Home Assistant'ta AI'a acilmis (expose) cihazlarin guncel durumunu getirir:
    isiklar, sensorler, alanlar vb. Salt-okunur; hicbir cihazi kontrol etmez."""
    return await ha_call("homeassistant__GetLiveContext")


@mcp.tool()
@audited()
def homeassistant_get_connectivity_report(hours: int = 24) -> dict:
    """Son N saatte (varsayilan 24, en fazla 168) baglantisi kopan (unavailable/unknown olan)
    entity'leri analiz eder: kac kez koptu, toplam ne kadar sure koptu, son kopma zamani,
    uretici/model. Ayrica ayni dakikada toplu kopmalari (ag/modem/entegrasyon sorunu isareti)
    listeler (ayni dakikada 2+ farkli CIHAZ). Salt-okunur."""
    start, hours = _since(hours)
    ids = [x["entity_id"] for x in ha_get("/states")]
    hist = []
    for i in range(0, len(ids), 80):
        hist += ha_get(f"/history/period/{start}",
                       {"filter_entity_id": ",".join(ids[i:i + 80]),
                        "minimal_response": "", "no_attributes": ""})
    now = datetime.now(timezone.utc)
    stats, bursts = {}, {}
    for series in hist:
        if not series:
            continue
        eid = series[0].get("entity_id")
        if not eid:
            continue
        drops, down_sec, last_drop, down_since = 0, 0.0, None, None
        prev = None
        for s in series:
            st = s.get("state")
            ts = datetime.fromisoformat(s.get("last_changed").replace("Z", "+00:00"))
            if st in DOWN_STATES and prev not in DOWN_STATES:
                if prev is not None:
                    drops += 1
                    last_drop = ts
                    minute = ts.strftime("%Y-%m-%d %H:%M")
                    bursts.setdefault(minute, set()).add(eid)
                down_since = ts
            elif st not in DOWN_STATES and down_since is not None:
                down_sec += (ts - down_since).total_seconds()
                down_since = None
            prev = st
        if down_since is not None:
            down_sec += (now - down_since).total_seconds()
        if drops:
            stats[eid] = {"entity_id": eid, "drops": drops,
                          "down_minutes": round(down_sec / 60, 1),
                          "last_drop_utc": last_drop.isoformat() if last_drop else None,
                          "currently_down": prev in DOWN_STATES}
    top = sorted(stats.values(), key=lambda x: (-x["drops"], -x["down_minutes"]))[:40]
    info = _device_info([t["entity_id"] for t in top])
    for t in top:
        t.update(info.get(t["entity_id"], {}))
    burst_ids = sorted({e for es in bursts.values() for e in es})[:300]
    binfo = _device_info(burst_ids)
    mass = []
    for m, es in sorted(bursts.items()):
        devices = sorted({(binfo.get(e, {}).get("device") or e) for e in es})
        if len(devices) >= 2:
            mass.append({"minute_utc": m, "device_count": len(devices), "devices": devices[:15]})
    return {"hours": hours, "entities_with_drops": len(stats),
            "top_entities": top, "mass_disconnects": mass[-30:]}


@mcp.tool()
@audited()
def homeassistant_get_entity_history(entity_id: str, hours: int = 24) -> list[dict]:
    """Tek bir entity'nin son N saatteki durum degisikliklerini getirir (en fazla 200). Salt-okunur."""
    _check_entity(entity_id)
    start, _ = _since(hours)
    hist = ha_get(f"/history/period/{start}",
                  {"filter_entity_id": entity_id, "minimal_response": "", "no_attributes": ""})
    rows = hist[0] if hist else []
    return [{"state": r.get("state"), "at_utc": r.get("last_changed")} for r in rows][-200:]


@mcp.tool()
@audited()
def homeassistant_get_logbook(hours: int = 6, entity_id: str = "") -> list[dict]:
    """Logbook kayitlarini getirir (son N saat, en fazla 200 kayit); entity_id ile daraltilabilir. Salt-okunur."""
    start, _ = _since(hours)
    params = {}
    if entity_id:
        _check_entity(entity_id)
        params["entity"] = entity_id
    rows = ha_get(f"/logbook/{start}", params)
    fields = ("when", "name", "entity_id", "state", "message", "domain", "context_event_type")
    return [_pick(r, fields) for r in rows][-200:]


SECRET_RE = re.compile(r"(?i)(token|password|passwd|secret|api[_-]?key|authorization)([\"'=: ]+)\S+")


@mcp.tool()
@audited()
def homeassistant_get_error_log(lines: int = 200, contains: str = "") -> dict:
    """Home Assistant hata logunun son satirlarini getirir (en fazla 500). contains verilirse
    yalnizca o metni iceren satirlar. Parola/token benzeri degerler maskelenir. Salt-okunur."""
    lines = max(10, min(int(lines), 500))
    r = ha.get("/error_log")
    if r.status_code == 404:
        r = ha.get("/hassio/core/logs", headers={"Accept": "text/plain"})
    if r.status_code in (401, 403):
        raise PermissionError("HA log istegini reddetti; yapay yonetici mi?")
    r.raise_for_status()
    text = r.text
    rows = text.splitlines()
    if contains:
        rows = [r for r in rows if contains.lower() in r.lower()]
    rows = [SECRET_RE.sub(r"\1\2***", r) for r in rows[-lines:]]
    return {"line_count": len(rows), "lines": rows}


@mcp.tool()
@audited()
def homeassistant_list_automations() -> list[dict]:
    """Tum otomasyonlari listeler: ad, acik/kapali, son tetiklenme, id. Salt-okunur."""
    out = []
    for s in ha_get("/states"):
        if s.get("entity_id", "").startswith("automation."):
            a = s.get("attributes", {})
            out.append({"entity_id": s["entity_id"], "name": a.get("friendly_name"),
                        "state": s.get("state"), "last_triggered": a.get("last_triggered"),
                        "id": a.get("id"), "mode": a.get("mode")})
    return out


@mcp.tool()
@audited()
def homeassistant_get_automation_config(automation_id: str) -> dict:
    """Bir otomasyonun tam yapilandirmasini (tetikleyici, kosul, eylem) id ile getirir.
    id, homeassistant_list_automations ciktisindaki 'id' alanidir. Salt-okunur."""
    if not re.match(r"^[A-Za-z0-9_\-]+$", automation_id or ""):
        raise ValueError("Gecersiz otomasyon id")
    return ha_get(f"/config/automation/config/{automation_id}")

