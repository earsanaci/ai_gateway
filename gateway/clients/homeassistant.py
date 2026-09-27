"""Home Assistant istemcileri (REST + yerlesik MCP) ve ortak yardimcilar."""
import json
import re
from datetime import datetime, timedelta, timezone

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from gateway.config import HA_SENSITIVE, HA_TOKEN, HA_URL

ENTITY_RE = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")
DOWN_STATES = {"unavailable", "unknown"}
ha = None
if HA_URL and HA_TOKEN:
    ha = httpx.Client(base_url=f"{HA_URL}/api",
                      headers={"Authorization": f"Bearer {HA_TOKEN}"}, timeout=60.0)


def ha_get(path, params=None):
    if ha is None:
        raise RuntimeError("Home Assistant yapilandirilmamis")
    r = ha.get(path, params=params)
    if r.status_code in (401, 403):
        raise PermissionError("HA bu istegi reddetti; yapay kullanicisi yonetici mi?")
    r.raise_for_status()
    return r.json() if "json" in r.headers.get("content-type", "") else r.text


def ha_post(path, payload):
    if ha is None:
        raise RuntimeError("Home Assistant yapilandirilmamis")
    r = ha.post(path, json=payload)
    r.raise_for_status()
    return r.json() if "json" in r.headers.get("content-type", "") else r.text


def _since(hours):
    hours = max(1, min(int(hours), 168))
    ts = datetime.now(timezone.utc) - timedelta(hours=hours)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ"), hours


def _check_entity(eid):
    if not ENTITY_RE.match(eid or ""):
        raise ValueError("Gecersiz entity_id")


def _device_info(entity_ids):
    if not entity_ids:
        return {}
    tpl = ("{% for e in ids %}{{ e }}|{{ device_attr(e,'manufacturer') }}|"
           "{{ device_attr(e,'model') }}|{{ device_attr(e,'name') }}\n{% endfor %}")
    tpl = "{% set ids = " + json.dumps(entity_ids) + " %}" + tpl
    out = {}
    for line in ha_post("/template", {"template": tpl}).splitlines():
        parts = line.split("|")
        if len(parts) == 4:
            out[parts[0]] = {"manufacturer": parts[1], "model": parts[2], "device": parts[3]}
    return out

HA_READ_TOOLS = {"homeassistant__GetLiveContext"}


async def ha_call(tool, args=None):
    if tool not in HA_READ_TOOLS:
        raise PermissionError(f"{tool} bu surumde izinli degil")
    if not HA_URL or not HA_TOKEN:
        raise RuntimeError("Home Assistant yapilandirilmamis")
    async with streamablehttp_client(
        f"{HA_URL}/api/mcp",
        headers={"Authorization": f"Bearer {HA_TOKEN}"},
        timeout=15,
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            res = await session.call_tool(tool, args or {})
            if res.isError:
                raise RuntimeError("Home Assistant hata dondurdu")
            return "\n".join(c.text for c in res.content if getattr(c, "type", "") == "text")


HA_SENSITIVE_DOMAINS = {"climate", "lock", "alarm_control_panel"}


def _is_sensitive(eid, name):
    key = (eid + " " + (name or "")).lower()
    key = key.replace("ı", "i").replace("ö", "o").replace("ü", "u").replace("ş", "s").replace("ç", "c").replace("ğ", "g")
    return eid.split(".")[0] in HA_SENSITIVE_DOMAINS or any(p in key for p in HA_SENSITIVE)
