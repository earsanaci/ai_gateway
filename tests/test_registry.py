"""Tum araclar kayitli mi ve beklenen isimlerle mi? Yazma araclari propose/apply ciftinde mi?"""
import asyncio

import gateway.__main__  # noqa: F401  araclari kaydeder
from gateway.core import mcp

EXPECTED = {
    "proxmox_list_guests", "proxmox_get_guest_status", "proxmox_get_node_status",
    "proxmox_get_storage_status", "proxmox_get_recent_tasks", "proxmox_get_backup_status",
    "proxmox_propose_action", "proxmox_apply_action", "proxmox_get_task_status",
    "proxmox_list_backup_jobs", "proxmox_get_not_backed_up", "maintenance_mode_status",
    "proxmox_propose_backup_job_change",
    "homeassistant_get_live_context", "homeassistant_get_connectivity_report",
    "homeassistant_get_entity_history", "homeassistant_get_logbook", "homeassistant_get_error_log",
    "homeassistant_list_automations", "homeassistant_get_automation_config",
    "homeassistant_propose_control", "homeassistant_apply_control",
    "homeassistant_propose_automation_change", "homeassistant_propose_automation_rollback",
    "audit_get_recent", "audit_verify",
}


def tool_names():
    return {t.name for t in asyncio.run(mcp.list_tools())}


def test_all_tools_registered():
    assert tool_names() == EXPECTED


def test_no_free_form_tools():
    forbidden = ("exec", "shell", "command", "delete_guest", "ssh")
    assert not [n for n in tool_names() if any(f in n for f in forbidden)]
