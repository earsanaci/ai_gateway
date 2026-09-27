# ai-gateway

Homelab Operations Gateway: Claude'un Proxmox ve Home Assistant'i guvenli, onayli ve
denetlenebilir sekilde yonetmesi icin MCP sunucusu. Mimari ve kararlar Notion'daki
"AI Operations Control Plane" sayfasinda.

## Yapi
```
gateway/
  config.py            ortam degiskenleri (sirlar /etc/ai-gateway/*.env icinde, repoda degil)
  core.py              MCP sunucusu, genel kurallar, audit, onay deposu
  auth.py              Bearer anahtar dogrulamasi
  clients/             Proxmox (reader/operator/admin) ve Home Assistant istemcileri
  tools/
    proxmox_read.py        L0 okuma
    proxmox_control.py     baslat/kapat/yeniden baslat/yedek (onayli)
    proxmox_backup_jobs.py yedek isleri + bakim modu (L3, ai-admin)
    ha_read.py             HA okuma, kopma raporu, loglar, otomasyonlar
    ha_control.py          HA cihaz kontrolu (her zaman onayli)
    ha_automations.py      HA otomasyon olustur/duzenle/geri al (onayli, yedekli)
deploy/                systemd servisi, firewall, deploy betigi
tests/                 onay ve arac kaydi testleri
```

## Kurallar
- Degistiren her islem: `propose_*` -> kullaniciya "ne anladim" -> acik onay -> `apply_*`.
- Onay 10 dk gecerli, tek kullanimlik, parametreler oneride sabit.
- Sirlar repoya girmez (`.gitignore`: `*.env`).

## Gelistirme
```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
PYTHONPATH=. .venv/bin/python -m pytest -q
```

## Dagitim (ai-gateway konsolunda)
```
/opt/ai-gateway/src/deploy/deploy.sh
```
Betik: son surumu ceker, bagimliliklari kurar, kodu ve araclari dogrular, servisi yeniden
baslatir, saglik kontrolu yapar. Herhangi bir adim basarisizsa otomatik olarak onceki surume doner.
