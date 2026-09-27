"""Proxmox onayli kontrol: baslat/kapat/yeniden baslat/yedek (propose -> apply)."""
import time
import uuid

from gateway.clients.proxmox import _find_guest, pve_get, pve_op
from gateway.config import APPROVAL_TTL, PVE_BACKUP_STORAGE, PVE_PROTECTED
from gateway.core import PENDING, audited, mcp

ACTIONS = {
    "start":    {"risk": "L1", "desc": "misafiri baslat"},
    "shutdown": {"risk": "L2", "desc": "misafiri duzgun sekilde kapat (shutdown)"},
    "reboot":   {"risk": "L2", "desc": "misafiri yeniden baslat"},
    "backup":   {"risk": "L1", "desc": "misafirin yedegini al"},
}

@mcp.tool()
@audited(risk="L0")
def proxmox_propose_action(action: str, vmid: int) -> dict:
    """Bir Proxmox islemi ONERIR, uygulamaz. action: start | shutdown | reboot | backup.
    Donen plani kullaniciya goster ve acik onayini iste. Onay gelirse
    proxmox_apply_action'i approval_id ile cagir. Kullanici onaylamadan apply cagirma."""
    if pve_op is None:
        raise RuntimeError("Operator token yapilandirilmamis")
    if action not in ACTIONS:
        raise ValueError(f"Gecersiz islem. Izinli: {', '.join(ACTIONS)}")
    g = _find_guest(vmid)
    if g.get("template"):
        raise ValueError("Sablonlar uzerinde islem yapilamaz")
    if action in ("shutdown", "reboot") and vmid in PVE_PROTECTED:
        raise PermissionError(f"vmid {vmid} korumali; kapatilamaz/yeniden baslatilamaz")
    status = g.get("status")
    if action == "start" and status == "running":
        raise ValueError("Misafir zaten calisiyor")
    if action in ("shutdown", "reboot") and status != "running":
        raise ValueError("Misafir calismiyor")

    now = time.time()
    for k in [k for k, v in PENDING.items() if v["expires"] < now]:
        del PENDING[k]

    approval_id = uuid.uuid4().hex[:12]
    plan = {
        "action": action, "vmid": vmid, "name": g.get("name"),
        "type": g.get("type"), "node": g.get("node"),
        "current_status": status, "risk": ACTIONS[action]["risk"],
    }
    if action == "backup":
        plan.update({"storage": PVE_BACKUP_STORAGE, "mode": "snapshot", "compress": "zstd"})
    PENDING[approval_id] = {**plan, "expires": now + APPROVAL_TTL}
    kind = "sanal makine" if g.get("type") == "qemu" else "container"
    effects = {
        "start": "Misafir acilacak, uzerindeki servisler birkac dakika icinde devreye girecek.",
        "shutdown": "Misafir duzgun sekilde kapatilacak; uzerindeki TUM servisler, tekrar acilana kadar calismayacak.",
        "reboot": "Misafir yeniden baslatilacak; uzerindeki servisler kisa sure (genelde 1-3 dk) kesilecek.",
        "backup": f"Calisirken anlik yedek (snapshot) alinacak, hedef {PVE_BACKUP_STORAGE}; servisler kesilmez, disk ve CPU kisa sure yuklenir.",
    }[action]
    understood = (f"Proxmox'ta {g.get('name')} ({kind}, ID {vmid}) su an '{status}'. "
                  f"Yapilacak: {ACTIONS[action]['desc']}. Etkisi: {effects}")
    return {
        "approval_id": approval_id,
        "understood": understood,
        "summary": f"{g.get('name')} ({vmid}) -> {ACTIONS[action]['desc']}",
        "plan": plan,
        "expires_in_seconds": APPROVAL_TTL,
        "note": "Uygulanmadi. Kullanicinin acik onayi gerekiyor.",
    }


@mcp.tool()
@audited(risk="L2")
def proxmox_apply_action(approval_id: str) -> dict:
    """Daha once proxmox_propose_action veya proxmox_propose_backup_job_change ile
    onerilmis ve KULLANICI TARAFINDAN ONAYLANMIS islemi uygular. Yalnizca kullanici bu sohbette acikca onay verdiyse cagir."""
    p = PENDING.pop(approval_id, None)
    if p is None:
        raise PermissionError("Onay bulunamadi, kullanildi veya suresi doldu")
    if p["expires"] < time.time():
        raise PermissionError("Onayin suresi doldu; islemi yeniden oner")
    if p.get("kind") == "backup_job":
        from gateway.tools.proxmox_backup_jobs import _apply_backup_job_change
        return _apply_backup_job_change(p)
    if p.get("kind") == "ha_control":
        raise PermissionError("Bu onay Home Assistant icin; homeassistant_apply_control kullan")
    # Durum oneri ile uygulama arasinda degistiyse reddet
    g = _find_guest(p["vmid"])
    if g.get("status") != p["current_status"] or g.get("node") != p["node"]:
        raise PermissionError("Misafirin durumu degisti; islemi yeniden oner")

    node, typ, vmid, action = p["node"], p["type"], p["vmid"], p["action"]
    if action == "backup":
        r = pve_op.post(f"/nodes/{node}/vzdump", data={
            "vmid": vmid, "storage": p["storage"], "mode": p["mode"], "compress": p["compress"]})
    else:
        r = pve_op.post(f"/nodes/{node}/{typ}/{vmid}/status/{action}")
    r.raise_for_status()
    return {"started": True, "action": action, "vmid": vmid, "upid": r.json()["data"],
            "note": "Gorev baslatildi. Sonucu proxmox_get_task_status ile kontrol et."}


@mcp.tool()
@audited()
def proxmox_get_task_status(upid: str) -> dict:
    """Bir Proxmox gorevinin (UPID) durumunu ve son log satirlarini getirir. Salt-okunur."""
    parts = upid.split(":")
    if len(parts) < 3 or parts[0] != "UPID":
        raise ValueError("Gecersiz UPID")
    node = parts[1]
    st = pve_get(f"/nodes/{node}/tasks/{upid}/status")
    log = pve_get(f"/nodes/{node}/tasks/{upid}/log", {"limit": 30, "start": 0})
    return {"status": st.get("status"), "exitstatus": st.get("exitstatus"),
            "type": st.get("type"), "id": st.get("id"),
            "log": [l.get("t") for l in log][-15:]}

