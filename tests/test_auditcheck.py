"""Konsol araci: journald tanik kopyasi ile dosya karsilastirmasi (journalctl taklit edilir)."""
import subprocess
from types import SimpleNamespace

import pytest

from gateway import audit as A
from gateway import auditcheck, config


@pytest.fixture()
def env(tmp_path, monkeypatch, capsys):
    p = tmp_path / "audit.jsonl"
    monkeypatch.setattr(config, "AUDIT_LOG", str(p))
    for i in range(4):
        A.audit({"tool": f"t{i}", "result": "ok", "request_id": f"r{i}"})
    journal = "\n".join(l for l in capsys.readouterr().err.splitlines() if l.startswith("AUDIT "))

    def fake_run(*a, **k):
        return SimpleNamespace(returncode=0, stdout=journal + "\nbaska bir log satiri\n", stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("sys.argv", ["auditcheck"])
    return p


def test_clean(env, capsys):
    assert auditcheck.main() == 0
    assert "SORUN YOK" in capsys.readouterr().out


def test_tail_truncation_detected(env, capsys):
    lines = env.read_text().splitlines()
    env.write_text("\n".join(lines[:-1]) + "\n")  # son satiri sil: zincir bunu goremez
    assert A.verify()["ok"]
    assert auditcheck.main() == 1
    assert "audit dosyasinda yok" in capsys.readouterr().out


def test_rewritten_chain_detected(env, capsys):
    import json
    lines = env.read_text().splitlines()
    e = json.loads(lines[1]); e["result"] = "gizlendi"; e.pop("prev")
    # tum zinciri tutarli sekilde yeniden yaz
    env.write_text("")
    prev_entries = [json.loads(l) for l in lines]
    prev_entries[1] = e
    for x in prev_entries:
        x.pop("prev", None)
        A.audit(dict(x))
    capsys.readouterr()
    assert A.verify()["ok"]          # zincir kendi icinde tutarli
    assert auditcheck.main() == 1    # ama tanik kopya uyusmuyor
