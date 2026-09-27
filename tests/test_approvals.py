"""Onay kurallari: onaysiz, suresi dolmus, yanlis turde veya tekrar kullanilan onay reddedilir."""
import time

import pytest

import gateway.__main__  # noqa: F401
from gateway.core import PENDING
from gateway.tools.ha_control import homeassistant_apply_control
from gateway.tools.proxmox_control import proxmox_apply_action


def test_unknown_approval_rejected():
    with pytest.raises(PermissionError):
        proxmox_apply_action(approval_id="yok")
    with pytest.raises(PermissionError):
        homeassistant_apply_control(approval_id="yok")


def test_expired_approval_rejected():
    PENDING["eski"] = {"kind": "ha_control", "plan": [], "expires": time.time() - 1}
    with pytest.raises(PermissionError):
        homeassistant_apply_control(approval_id="eski")
    assert "eski" not in PENDING  # tek kullanimlik: denendiyse silinir


def test_cross_kind_rejected():
    PENDING["ha1"] = {"kind": "ha_control", "plan": [], "expires": time.time() + 60}
    with pytest.raises(PermissionError):
        proxmox_apply_action(approval_id="ha1")
    PENDING["px1"] = {"kind": "backup_job", "expires": time.time() + 60}
    with pytest.raises(PermissionError):
        homeassistant_apply_control(approval_id="px1")


def test_protected_guest_cannot_be_shut_down(monkeypatch):
    from gateway.tools import proxmox_control as pc
    monkeypatch.setattr(pc, "pve_op", object())
    monkeypatch.setattr(pc, "_find_guest", lambda v: {"vmid": v, "status": "running", "name": "gw"})
    with pytest.raises(PermissionError):
        pc.proxmox_propose_action(action="shutdown", vmid=109)


def test_unknown_action_rejected(monkeypatch):
    from gateway.tools import proxmox_control as pc
    monkeypatch.setattr(pc, "pve_op", object())
    with pytest.raises(ValueError):
        pc.proxmox_propose_action(action="destroy", vmid=100)
