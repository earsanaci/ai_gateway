"""Zamanlanmis yedek isleri ve bakim modu (ai-admin)."""
import time
import uuid

import httpx

from gateway.clients.proxmox import pve_admin, pve_get
from gateway.config import APPROVAL_TTL
from gateway.core import PENDING, _pick, audit, audited, mcp

JOB_FIELDS = ("id", "enabled", "schedule", "storage", "mode", "compress", "vmid",
              "all", "exclude", "pool", "node", "comment", "notes-template")


ADMIN_REQUIRED = {"/": ("Sys.Modify",), "/storage": ("Datastore.Allocate",)}


def _maintenance_missing():
    """Bakim modu kapaliysa None, aciksa eksik yetkilerin listesini dondurur."""
    if pve_admin is None:
        return None
    try:
        r = pve_admin.get("/access/permissions")
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    perms = r.json().get("data", {})
    missing = []
    for path, privs in ADMIN_REQUIRED.items():
        have = perms.get(path) or perms.get("/", {})
        missing += [f"{pr} ({path})" for pr in privs if not have.get(pr)]
    return missing


def _maintenance_on():
    m = _maintenance_missing()
    if m is None:
        return False
    if m:
        raise PermissionError("Bakim modu acik ama ai-admin yetkileri eksik: " + ", ".join(m))
    return True


def _vmid_list(s):
    return sorted({int(x) for x in str(s or "").split(",") if x.strip()})


@mcp.tool()
@audited()
def proxmox_list_backup_jobs() -> list[dict]:
    """Zamanlanmis yedekleme islerini (schedule, hedef depolama, kapsanan misafirler) listeler. Salt-okunur."""
    return [_pick(j, JOB_FIELDS) for j in pve_get("/cluster/backup")]


@mcp.tool()
@audited()
def proxmox_get_not_backed_up() -> list[dict]:
    """Hicbir zamanlanmis yedekleme isine dahil olmayan misafirleri listeler. Salt-okunur."""
    return [_pick(g, ("vmid", "name", "type")) for g in pve_get("/cluster/backup-info/not-backed-up")]


@mcp.tool()
@audited()
def maintenance_mode_status() -> dict:
    """Bakim modunun acik olup olmadigini soyler. Bakim modunu yalnizca kullanici
    Proxmox arayuzunde ai-admin kullanicisini Enabled yaparak acar; AI acamaz."""
    m = _maintenance_missing()
    if m is None:
        return {"maintenance_mode": False,
                "note": "Kapali. Acmak icin kullanici Proxmox'ta ai-admin kullanicisini Enabled yapmali."}
    return {"maintenance_mode": True, "missing_privileges": m,
            "note": "Acik" if not m else "Acik ama eksik yetkiler var; AIAdmin rolune eklenmeli."}


@mcp.tool()
@audited(risk="L0")
def proxmox_propose_backup_job_change(job_id: str, add_vmids: list[int] = [],
                                      remove_vmids: list[int] = []) -> dict:
    """Mevcut bir zamanlanmis yedekleme isine misafir eklemeyi/cikarmayi ONERIR, uygulamaz.
    Liste modundaki islerde vmid listesini, 'tum misafirler' modundaki islerde haric tutma
    (exclude) listesini duzenler. Bakim modu gerektirir.
    Donen degisikligi kullaniciya goster, acik onay alinca proxmox_apply_action ile uygula."""
    if not _maintenance_on():
        raise PermissionError("Bakim modu kapali. Kullanici Proxmox'ta ai-admin kullanicisini Enabled yapmali.")
    if not add_vmids and not remove_vmids:
        raise ValueError("Eklenecek veya cikarilacak misafir belirtilmedi")
    job = next((j for j in pve_get("/cluster/backup") if j.get("id") == job_id), None)
    if job is None:
        raise ValueError(f"Yedek isi bulunamadi: {job_id}")
    if job.get("pool"):
        raise ValueError("Havuz (pool) modundaki isler desteklenmiyor")
    existing = {g.get("vmid") for g in pve_get("/cluster/resources", {"type": "vm"})}
    for v in list(add_vmids) + list(remove_vmids):
        if v not in existing:
            raise ValueError(f"vmid {v} bulunamadi")

    if job.get("all"):
        field = "exclude"
        old = _vmid_list(job.get("exclude"))
        # Ise eklemek = hariclerden cikarmak; isten cikarmak = harice eklemek
        new = sorted((set(old) - set(add_vmids)) | set(remove_vmids))
    else:
        field = "vmid"
        old = _vmid_list(job.get("vmid"))
        new = sorted((set(old) | set(add_vmids)) - set(remove_vmids))
        if not new:
            raise ValueError("Is bos birakilamaz")
    if new == old:
        raise ValueError("Degisiklik yok (misafir zaten istenen durumda)")

    now = time.time()
    approval_id = uuid.uuid4().hex[:12]
    plan = {"kind": "backup_job", "job_id": job_id, "schedule": job.get("schedule"),
            "storage": job.get("storage"), "mode": "tum misafirler" if job.get("all") else "liste",
            "field": field, f"old_{field}": old, f"new_{field}": new,
            "now_included": sorted(add_vmids), "now_excluded": sorted(remove_vmids),
            "risk": "L3"}
    PENDING[approval_id] = {**plan, "old": old, "new": new,
                            "raw_old": str(job.get(field) or ""), "expires": now + APPROVAL_TTL}
    names = {g.get("vmid"): g.get("name") for g in pve_get("/cluster/resources", {"type": "vm"})}
    def _n(ids):
        return ", ".join(f"{names.get(v, '?')} ({v})" for v in ids) or "yok"
    if job.get("all"):
        remaining = _n(new)
        understood = (f"Proxmox'ta her gun {job.get('schedule')}'de {job.get('storage')} hedefine calisan "
                      f"'tum misafirler' yedek isinde: dahil edilecek: {_n(sorted(add_vmids))}; "
                      f"haric tutulacak: {_n(sorted(remove_vmids))}. Degisiklikten sonra haric kalanlar: {remaining}.")
    else:
        understood = (f"Proxmox'ta her gun {job.get('schedule')}'de {job.get('storage')} hedefine calisan "
                      f"yedek isinde: eklenecek: {_n(sorted(add_vmids))}; cikarilacak: {_n(sorted(remove_vmids))}. "
                      f"Degisiklikten sonra kapsanan misafirler: {_n(new)}.")
    return {"approval_id": approval_id,
            "understood": understood,
            "summary": f"Yedek isi {job_id} ({job.get('schedule')}, {job.get('storage')}): "
                       f"dahil edilecek {sorted(add_vmids)}, cikarilacak {sorted(remove_vmids)}",
            "plan": plan, "expires_in_seconds": APPROVAL_TTL,
            "note": "Uygulanmadi. Kullanicinin acik onayi gerekiyor."}


def _apply_backup_job_change(p):
    if not _maintenance_on():
        raise PermissionError("Bakim modu kapali; degisiklik uygulanmadi")
    field = p["field"]
    job = next((j for j in pve_get("/cluster/backup") if j.get("id") == p["job_id"]), None)
    if job is None or str(job.get(field) or "") != p["raw_old"]:
        raise PermissionError("Yedek isi oneri sonrasi degismis; yeniden oner")
    value = ",".join(str(v) for v in p["new"])
    data = {field: value} if value else {"delete": field}
    r = pve_admin.put(f"/cluster/backup/{p['job_id']}", data=data)
    r.raise_for_status()
    audit({"event": "backup_job_changed", "job_id": p["job_id"], "field": field,
           "old": p["old"], "new": p["new"], "risk": "L3"})
    return {"applied": True, "job_id": p["job_id"], "field": field,
            "old": p["old"], "new": p["new"],
            "rollback": "Geri almak icin ayni is icin tersi degisikligi oner.",
            "reminder": "Is bitti; bakim modunu Proxmox'ta kapatmayi unutma."}

