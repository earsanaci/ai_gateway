"""Proxmox Backup Server salt-okunur araclar (L0)."""
import time

from gateway.clients.pbs import PBSOffline, pbs_get
from gateway.core import _pick, audited, mcp

NODE = "localhost"


def _ago(ts):
    if not ts:
        return None
    h = (time.time() - ts) / 3600
    return f"{h:.1f} saat once" if h < 48 else f"{h / 24:.1f} gun once"


@mcp.tool()
@audited()
def pbs_get_status() -> dict:
    """Proxmox Backup Server'in durumunu getirir: acik mi, ne zamandir acik (uptime), CPU/bellek,
    datastore doluluklari ve son cop toplama (GC) durumu. PBS kapaliysa bunu acikca soyler. Salt-okunur."""
    try:
        node = pbs_get(f"/nodes/{NODE}/status") or {}
    except PBSOffline as e:
        return {"online": False, "note": str(e) + ". PBS Wake-on-LAN ile yalnizca yedek saatlerinde aciliyor olabilir."}
    stores = []
    for d in pbs_get("/status/datastore-usage") or []:
        total, used = d.get("total") or 0, d.get("used") or 0
        stores.append({"store": d.get("store"), "used_pct": round(100 * used / total, 1) if total else None,
                       "used_gb": round(used / 1e9, 1), "total_gb": round(total / 1e9, 1),
                       "gc_status": d.get("gc-status"), "error": d.get("error")})
    up = node.get("uptime")
    return {"online": True, "uptime_hours": round(up / 3600, 1) if up else None,
            "cpu": node.get("cpu"), "memory": node.get("memory"), "root_disk": node.get("root"),
            "datastores": stores}


@mcp.tool()
@audited()
def pbs_list_backup_groups(datastore: str = "") -> list[dict]:
    """PBS'teki yedek gruplarini (her misafir icin) listeler: son yedek zamani, yedek sayisi, sahip.
    Son yedegi 36 saatten eski olanlar 'stale' olarak isaretlenir. datastore bos ise tumu. Salt-okunur."""
    stores = [datastore] if datastore else [d.get("store") for d in pbs_get("/admin/datastore") or []]
    out = []
    for s in stores:
        for g in pbs_get(f"/admin/datastore/{s}/groups") or []:
            last = g.get("last-backup")
            out.append({"datastore": s, "type": g.get("backup-type"), "id": g.get("backup-id"),
                        "comment": g.get("comment"), "count": g.get("backup-count"),
                        "last_backup": last, "last_backup_ago": _ago(last),
                        "stale": bool(last) and (time.time() - last) > 36 * 3600,
                        "owner": g.get("owner")})
    return sorted(out, key=lambda x: (x["datastore"], str(x["id"])))


@mcp.tool()
@audited()
def pbs_list_snapshots(datastore: str, backup_type: str = "", backup_id: str = "", limit: int = 20) -> list[dict]:
    """Bir datastore'daki yedek anlik goruntulerini (snapshot) listeler, en yeni once: zaman, boyut,
    dogrulama (verify) durumu, korumali mi. backup_type (vm/ct/host) ve backup_id ile suzulebilir. Salt-okunur."""
    limit = max(1, min(int(limit), 100))
    params = {}
    if backup_type:
        params["backup-type"] = backup_type
    if backup_id:
        params["backup-id"] = backup_id
    snaps = pbs_get(f"/admin/datastore/{datastore}/snapshots", params) or []
    snaps.sort(key=lambda x: x.get("backup-time", 0), reverse=True)
    out = []
    for x in snaps[:limit]:
        v = x.get("verification") or {}
        out.append({"type": x.get("backup-type"), "id": x.get("backup-id"),
                    "time": x.get("backup-time"), "ago": _ago(x.get("backup-time")),
                    "size_gb": round((x.get("size") or 0) / 1e9, 2),
                    "verify_state": v.get("state"), "protected": x.get("protected"),
                    "comment": x.get("comment")})
    return out


TASK_FIELDS = ("upid", "worker_type", "worker_id", "user", "status", "starttime", "endtime")


@mcp.tool()
@audited()
def pbs_get_recent_tasks(hours: int = 48, errors_only: bool = False, limit: int = 50) -> list[dict]:
    """PBS'in son gorevlerini (yedek alma, verify, prune, GC, sync) listeler. errors_only=True ise
    yalnizca basarisizlar. Salt-okunur."""
    hours = max(1, min(int(hours), 24 * 30))
    limit = max(1, min(int(limit), 200))
    params = {"since": int(time.time() - hours * 3600), "limit": limit}
    if errors_only:
        params["errors"] = 1
    return [_pick(t, TASK_FIELDS) for t in pbs_get(f"/nodes/{NODE}/tasks", params) or []]


@mcp.tool()
@audited()
def pbs_get_task_log(upid: str) -> dict:
    """Bir PBS gorevinin (UPID) durumunu ve son log satirlarini getirir. Salt-okunur."""
    if not upid.startswith("UPID:"):
        raise ValueError("Gecersiz UPID")
    st = pbs_get(f"/nodes/{NODE}/tasks/{upid}/status") or {}
    log = pbs_get(f"/nodes/{NODE}/tasks/{upid}/log", {"limit": 200, "start": 0}) or []
    return {"status": st.get("status"), "exitstatus": st.get("exitstatus"),
            "type": st.get("worker_type"), "log": [l.get("t") for l in log][-40:]}


@mcp.tool()
@audited()
def pbs_list_jobs() -> dict:
    """PBS'teki zamanlanmis isleri ve son calisma durumlarini getirir: verify, prune, sync.
    Yetki olmayan veya PBS surumunde bulunmayan turler atlanir. Salt-okunur."""
    out = {}
    fields = ("id", "store", "schedule", "next-run", "last-run-state", "last-run-endtime", "comment")
    for kind in ("verify", "prune", "sync"):
        try:
            out[kind] = [_pick(j, fields) for j in pbs_get(f"/admin/{kind}") or []]
        except PermissionError:
            out[kind] = "yetki yok"
        except Exception as e:  # eski surumlerde uc nokta yoksa
            out[kind] = f"okunamadi: {type(e).__name__}"
    return out
