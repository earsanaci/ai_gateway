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
