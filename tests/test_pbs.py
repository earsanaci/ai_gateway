"""PBS istemcisi: parmak izi sabitleme, kapaliyken nazik hata, yetki hatasi, araclarin cevabi."""
import hashlib

import pytest

from gateway.clients import pbs


def test_fingerprint_normalization():
    assert pbs._norm_fp("AA:bb:Cc") == "aabbcc"


def test_fingerprint_mismatch_refused(monkeypatch):
    der = b"sahte-sertifika"
    monkeypatch.setattr(pbs, "_fetch_cert_pem", lambda h, p, timeout=5: (der, "PEM"))
    with pytest.raises(PermissionError):
        pbs._pinned_context("1.2.3.4", 8007, "00:11:22")


def test_offline_is_reported_not_crash(monkeypatch):
    def boom(h, p, timeout=5):
        raise ConnectionRefusedError()
    monkeypatch.setattr(pbs, "_fetch_cert_pem", boom)
    with pytest.raises(pbs.PBSOffline):
        pbs._pinned_context("1.2.3.4", 8007, hashlib.sha256(b"x").hexdigest())


def test_status_tool_when_offline(monkeypatch):
    import gateway.__main__  # noqa: F401
    from gateway.tools import pbs_read

    def off(path, params=None):
        raise pbs.PBSOffline("PBS su an kapali")
    monkeypatch.setattr(pbs_read, "pbs_get", off)
    r = pbs_read.pbs_get_status()
    assert r["online"] is False and "kapali" in r["note"]


def test_groups_marks_stale(monkeypatch):
    import time
    from gateway.tools import pbs_read
    now = time.time()
    data = {
        "/admin/datastore": [{"store": "ds1"}],
        "/admin/datastore/ds1/groups": [
            {"backup-type": "ct", "backup-id": "109", "last-backup": now - 3600, "backup-count": 5},
            {"backup-type": "vm", "backup-id": "100", "last-backup": now - 5 * 86400, "backup-count": 9},
        ],
    }
    monkeypatch.setattr(pbs_read, "pbs_get", lambda path, params=None: data[path])
    g = {x["id"]: x for x in pbs_read.pbs_list_backup_groups()}
    assert g["109"]["stale"] is False and g["100"]["stale"] is True


def test_unconfigured(monkeypatch):
    monkeypatch.setattr(pbs, "configured", lambda: False)
    monkeypatch.setattr(pbs, "_client", None)
    with pytest.raises(RuntimeError):
        pbs._get_client()


def test_journal_window_and_filter(monkeypatch):
    from gateway.tools import pbs_read
    seen = {}

    def fake(path, params=None):
        seen["path"], seen["params"] = path, params
        return ["Oct 05 03:00:50 pbs kernel: usb 2-1: reset high-speed USB device",
                "Oct 05 03:00:50 pbs systemd[1]: Started foo",
                "Oct 05 03:00:51 pbs kernel: Buffer I/O error on dev sdc3"]
    monkeypatch.setattr(pbs_read, "pbs_get", fake)
    r = pbs_read.pbs_get_journal(since="2026-10-05T02:55:00+03:00", until="2026-10-05T03:10:00+03:00",
                                 pattern="usb|i/o error")
    assert seen["path"] == "/nodes/localhost/journal"
    assert seen["params"]["since"] < seen["params"]["until"]
    assert r["matched"] == 2 and r["total_lines"] == 3


def test_journal_requires_timezone():
    from gateway.tools import pbs_read
    with pytest.raises(ValueError):
        pbs_read.pbs_get_journal(since="2026-10-05T02:55:00")


def test_disk_health_rejects_bad_name(monkeypatch):
    from gateway.tools import pbs_read
    monkeypatch.setattr(pbs_read, "pbs_get", lambda path, params=None: [])
    with pytest.raises(ValueError):
        pbs_read.pbs_get_disk_health(disk="../../etc")


def test_disk_health_smart_subset(monkeypatch):
    from gateway.tools import pbs_read

    def fake(path, params=None):
        if path.endswith("/disks/list"):
            return [{"name": "sdc", "model": "USB SSD", "status": "passed", "wearout": 97}]
        return {"status": "PASSED", "type": "ata", "attributes": [
            {"name": "Reallocated_Sector_Ct", "raw": "0"}, {"name": "Seek_Error_Rate", "raw": "1"},
            {"name": "Power_On_Hours", "raw": "1234"}]}
    monkeypatch.setattr(pbs_read, "pbs_get", fake)
    r = pbs_read.pbs_get_disk_health(disk="sdc")
    names = [a["name"] for a in r["smart"]["attributes"]]
    assert "Reallocated_Sector_Ct" in names and "Seek_Error_Rate" not in names
    assert r["disks"][0]["name"] == "sdc"
