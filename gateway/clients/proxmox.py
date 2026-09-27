"""Proxmox API istemcileri: reader (her zaman), operator (onayli isler), admin (bakim modu)."""
import httpx

from gateway.config import (PVE_ADMIN_TOKEN_ID, PVE_ADMIN_TOKEN_SECRET, PVE_CA, PVE_HOST,
                            PVE_OP_TOKEN_ID, PVE_OP_TOKEN_SECRET, PVE_TOKEN_ID, PVE_TOKEN_SECRET)

pve = httpx.Client(
    base_url=f"{PVE_HOST}/api2/json",
    headers={"Authorization": f"PVEAPIToken={PVE_TOKEN_ID}={PVE_TOKEN_SECRET}"},
    verify=PVE_CA if PVE_CA else False,
    timeout=15.0,
)


def pve_get(path, params=None):
    r = pve.get(path, params=params)
    r.raise_for_status()
    return r.json()["data"]

pve_op = None
if PVE_OP_TOKEN_ID and PVE_OP_TOKEN_SECRET:
    pve_op = httpx.Client(
        base_url=f"{PVE_HOST}/api2/json",
        headers={"Authorization": f"PVEAPIToken={PVE_OP_TOKEN_ID}={PVE_OP_TOKEN_SECRET}"},
        verify=PVE_CA if PVE_CA else False,
        timeout=30.0,
    )

pve_admin = None
if PVE_ADMIN_TOKEN_ID and PVE_ADMIN_TOKEN_SECRET:
    pve_admin = httpx.Client(
        base_url=f"{PVE_HOST}/api2/json",
        headers={"Authorization": f"PVEAPIToken={PVE_ADMIN_TOKEN_ID}={PVE_ADMIN_TOKEN_SECRET}"},
        verify=PVE_CA if PVE_CA else False,
        timeout=30.0,
    )


def _find_guest(vmid):
    for r in pve_get("/cluster/resources", {"type": "vm"}):
        if r.get("vmid") == vmid:
            return r
    raise ValueError(f"vmid {vmid} bulunamadi")
