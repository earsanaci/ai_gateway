"""Audit hash zinciri: silme/degistirme tespiti, eski satirlarla uyum, tanik kopya, okuma araci."""
import json

import pytest

from gateway import audit as A
from gateway import config


@pytest.fixture()
def log(tmp_path, monkeypatch):
    p = tmp_path / "audit.jsonl"
    monkeypatch.setattr(config, "AUDIT_LOG", str(p))
    return p


def write(n=4):
    for i in range(n):
        A.audit({"tool": f"t{i}", "risk": "L0", "result": "ok", "params": {"i": i}})


def test_chain_ok(log):
    write()
    v = A.verify()
    assert v["ok"] and v["chained_lines"] == 4 and v["unchained_lines_after_start"] == 0


def test_deleted_middle_line_detected(log):
    write()
    lines = log.read_text().splitlines()
    del lines[1]
    log.write_text("\n".join(lines) + "\n")
    v = A.verify()
    assert not v["ok"] and v["broken"][0]["line"] == 2


def test_modified_line_detected(log):
    write()
    lines = log.read_text().splitlines()
    e = json.loads(lines[1])
    e["result"] = "gizlendi"
    lines[1] = json.dumps(e, ensure_ascii=False)
    log.write_text("\n".join(lines) + "\n")
    assert not A.verify()["ok"]


def test_legacy_lines_before_chain_are_anchored(log):
    log.write_text('{"tool":"eski1"}\n{"event":"deploy","result":"ok"}\n')
    write(2)
    v = A.verify()
    assert v["ok"] and v["legacy_lines_before_chain"] == 2 and v["chained_lines"] == 2
    # eski son satir degistirilirse zincirin ilk halkasi bunu yakalar
    txt = log.read_text().replace('"deploy"', '"deployX"')
    log.write_text(txt)
    assert not A.verify()["ok"]


def test_foreign_line_between_entries_keeps_chain(log):
    write(2)
    with open(log, "ab") as f:
        f.write(b'{"event":"deploy","result":"ok"}\n')  # betigin yazdigi satir
    write(2)
    v = A.verify()
    assert v["ok"] and v["unchained_lines_after_start"] == 1


def test_witness_written_to_stderr(log, capsys):
    A.audit({"tool": "x", "result": "ok", "request_id": "r1"})
    err = capsys.readouterr().err
    assert err.startswith("AUDIT ")
    w = json.loads(err[6:])
    import hashlib
    line = log.read_bytes().rstrip(b"\n")
    assert w["h"] == hashlib.sha256(line).hexdigest() and w["id"] == "r1"


def test_recent_filters_and_shortens(log):
    A.audit({"tool": "proxmox_list_guests", "risk": "L0", "result": "ok"})
    A.audit({"tool": "proxmox_apply_action", "risk": "L2", "result": "ok", "params": {"approval_id": "a" * 500}})
    A.audit({"event": "ha_control_applied", "actions": []})
    only = A.recent(10, only_changes=True)
    assert {e.get("tool") or e.get("event") for e in only} == {"proxmox_apply_action", "ha_control_applied"}
    assert "prev" not in only[0]
    apply_entry = [e for e in only if e.get("tool")][0]
    assert len(apply_entry["params"]["approval_id"]) < 300
    assert [e["tool"] for e in A.recent(10, tool="list_guests")] == ["proxmox_list_guests"]


def test_verify_when_no_file(log):
    assert A.verify()["ok"]
