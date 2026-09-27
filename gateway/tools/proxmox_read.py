"""Proxmox salt-okunur araclar (L0)."""
import time

from gateway.clients.proxmox import pve_get
from gateway.core import _pick, audited, mcp

GUEST_FIELDS = ("vmid", "name", "type", "node", "status", "uptime", "cpu",
                "maxcpu", "mem", "maxmem", "disk", "maxdisk", "template", "tags")


@mcp.tool()
@audited()
def proxmox_list_guests() -> list[dict]:
    """Proxmox'taki tum VM ve LXC'leri durum ve kaynak kullanimlariyla listeler. Salt-okunur."""
    return [_pick(r, GUEST_FIELDS) for r in pve_get("/cluster/resources", {"type": "vm"})]


@mcp.tool()
@audited()
def proxmox_get_guest_status(vmid: int) -> dict:
    """Tek bir VM/LXC'nin durumunu vmid ile getirir. Salt-okunur."""
    if not 100 <= vmid <= 999999999:
        raise ValueError("Gecersiz vmid")
    for r in pve_get("/cluster/resources", {"type": "vm"}):
        if r.get("vmid") == vmid:
            return _pick(r, GUEST_FIELDS)
    raise ValueError(f"vmid {vmid} bulunamadi")


@mcp.tool()
@audited()
def proxmox_get_node_status() -> list[dict]:
    """Proxmox node'larinin durumunu (CPU, bellek, uptime) getirir. Salt-okunur."""
    fields = ("node", "status", "cpu", "maxcpu", "mem", "maxmem", "uptime")
    return [_pick(n, fields) for n in pve_get("/nodes")]


@mcp.tool()
@audited()
def proxmox_get_storage_status() -> list[dict]:
    """Depolama alanlarinin doluluk ve durumunu getirir. Salt-okunur."""
    fields = ("storage", "node", "status", "plugintype", "content", "shared", "disk", "maxdisk")
    return [_pick(s, fields) for s in pve_get("/cluster/resources", {"type": "storage"})]


TASK_FIELDS = ("upid", "type", "id", "node", "user", "status", "starttime", "endtime")


@mcp.tool()
@audited()
def proxmox_get_recent_tasks(limit: int = 20, errors_only: bool = False) -> list[dict]:
    """Son Proxmox gorevlerini listeler. errors_only=True ise sadece basarisiz olanlar. Salt-okunur."""
    limit = max(1, min(limit, 100))
    tasks = pve_get("/cluster/tasks")
    if errors_only:
        tasks = [t for t in tasks if t.get("status") and t.get("status") != "OK"]
    return [_pick(t, TASK_FIELDS) for t in tasks[:limit]]


@mcp.tool()
@audited()
def proxmox_get_backup_status(days: int = 7) -> list[dict]:
    """Son N gundeki yedekleme (vzdump) gorevlerini ve sonuclarini listeler. Salt-okunur."""
    days = max(1, min(days, 60))
    since = time.time() - days * 86400
    return [_pick(t, TASK_FIELDS) for t in pve_get("/cluster/tasks")
            if t.get("type") == "vzdump" and t.get("starttime", 0) >= since]

