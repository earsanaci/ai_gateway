"""Entity guncelleme: dogrulama kurallari ve onay akisi (HA sahte WebSocket ile)."""
import time

import pytest

import gateway.__main__  # noqa: F401
from gateway.core import PENDING
from gateway.tools import ha_entities as he
from gateway.tools.ha_control import homeassistant_apply_control

AREAS = [{"area_id": "mutfak", "name": "Mutfak"}, {"area_id": "koridor_giris", "name": "Koridor Giriş"}]
ENT = {"entity_id": "binary_sensor.koridor_hareket", "name": None, "original_name": "Koridor Hareket",
       "area_id": None, "device_id": "dev1"}
DEVICES = [{"id": "dev1", "name": "Sensor", "name_by_user": None, "area_id": "koridor_giris"}]
ENTITIES = [ENT, {"entity_id": "sensor.koridor_pil", "device_id": "dev1", "area_id": None},
            {"entity_id": "binary_sensor.dolu", "device_id": "x", "area_id": None}]


@pytest.fixture
def fake_ha(monkeypatch):
    sent = []

    def ws(cmds):
        out = []
        for c in cmds:
            sent.append(c)
            t = c["type"]
            if t == "config/entity_registry/get":
                out.append({**ENT, "entity_id": c["entity_id"]})
            elif t == "config/area_registry/list":
                out.append(AREAS)
            elif t == "config/entity_registry/list":
                out.append(ENTITIES)
            elif t == "config/device_registry/list":
                out.append(DEVICES)
            else:
                out.append(None)
        return out

    monkeypatch.setattr(he, "ha", object())
    monkeypatch.setattr(he, "ha_ws", ws)
    monkeypatch.setattr(he, "_automations_using", lambda e: [{"id": "1", "name": "Mutfak LED"}])
    return sent


def test_nothing_to_change_rejected(fake_ha):
    with pytest.raises(ValueError):
        he.homeassistant_propose_entity_update(entity_id="binary_sensor.koridor_hareket")


def test_domain_change_rejected(fake_ha):
    with pytest.raises(ValueError):
        he.homeassistant_propose_entity_update(entity_id="binary_sensor.koridor_hareket",
                                               new_entity_id="sensor.mutfak")


def test_taken_id_rejected(fake_ha):
    with pytest.raises(ValueError, match="zaten"):
        he.homeassistant_propose_entity_update(entity_id="binary_sensor.koridor_hareket",
                                               new_entity_id="binary_sensor.dolu")


def test_unknown_area_rejected(fake_ha):
    with pytest.raises(ValueError, match="Alan"):
        he.homeassistant_propose_entity_update(entity_id="binary_sensor.koridor_hareket", area="Bodrum")


def test_propose_and_apply(fake_ha):
    r = he.homeassistant_propose_entity_update(
        entity_id="binary_sensor.koridor_hareket", new_entity_id="binary_sensor.mutfak_hareket",
        name="Mutfak Hareket Sensörü", area="mutfak")
    assert "Mutfak" in r["understood"]
    assert any("sensor.koridor_pil" in w for w in r["warnings"])
    assert any("Mutfak LED" in w for w in r["warnings"])
    assert not [c for c in fake_ha if c["type"].endswith("/update")]  # oneri hicbir sey degistirmez
    homeassistant_apply_control(approval_id=r["approval_id"])
    updates = [c for c in fake_ha if c["type"].endswith("/update")]
    assert {"type": "config/device_registry/update", "device_id": "dev1", "area_id": "mutfak"} in updates
    eu = next(c for c in updates if c["type"] == "config/entity_registry/update")
    assert eu["new_entity_id"] == "binary_sensor.mutfak_hareket" and eu["area_id"] == "mutfak"
    assert r["approval_id"] not in PENDING


def test_expired_entity_approval_rejected():
    PENDING["e1"] = {"kind": "ha_entity", "expires": time.time() - 1}
    with pytest.raises(PermissionError):
        homeassistant_apply_control(approval_id="e1")
