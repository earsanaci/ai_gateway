# ai-gateway

Homelab Operations Gateway: Claude'un Proxmox ve Home Assistant'i guvenli, onayli ve
denetlenebilir sekilde yonetmesi icin MCP sunucusu. Mimari ve kararlar Notion'daki
"AI Operations Control Plane" sayfasinda.

## Yapi
```
gateway/
  config.py            ortam degiskenleri (sirlar /etc/ai-gateway/*.env icinde, repoda degil)
  core.py              MCP sunucusu, genel kurallar, audit, onay deposu
  audit.py             hash zincirli audit + journald tanik kopyasi
  auditcheck.py        konsol dogrulama araci
  auth.py              Bearer anahtar dogrulamasi
  clients/             Proxmox (reader/operator/admin) ve Home Assistant istemcileri
  tools/
    proxmox_read.py        L0 okuma
    proxmox_control.py     baslat/kapat/yeniden baslat/yedek (onayli)
    proxmox_backup_jobs.py yedek isleri + bakim modu (L3, ai-admin)
    ha_read.py             HA okuma, kopma raporu, loglar, otomasyonlar
    ha_control.py          HA cihaz kontrolu (her zaman onayli)
    ha_automations.py      HA otomasyon olustur/duzenle/geri al (onayli, yedekli)
    audit_tools.py         audit_get_recent, audit_verify (salt-okunur)
    pbs_read.py            Proxmox Backup Server okuma (durum, gruplar, snapshot, gorevler, isler,
                           sistem gunlugu, disk/SMART sagligi)
deploy/                systemd servisi, firewall, deploy betigi
tests/                 onay ve arac kaydi testleri
```

## Proxmox Backup Server
Istege bagli: `/etc/ai-gateway/pbs.env` varsa PBS araclari calisir. Token yalnizca okuma
yetkili olmali (PBS'te rol `Audit`, yol `/`, hem kullaniciya hem token'a). PBS'in kendinden
imzali sertifikasi `PBS_FINGERPRINT` ile sabitlenir; eslesmezse baglanilmaz. PBS kapaliyken
(Wake-on-LAN) araclar cokmez, "PBS su an kapali" der.

## TLS
Varsayilan HTTP + Bearer token; ayni LAN'daki bir cihaz (AdGuard/IoT) trafigi dinleyip
anahtari calabilir. TLS acmak icin (kendinden imzali sertifika, gateway'in genel bir
alan adi yok):
```
deploy/gen-tls-cert.sh 192.168.7.18                 # gateway'in LAN IP'si
cp deploy/example-tls.env /etc/ai-gateway/tls.env   # yollari kontrol et
```
`deploy.sh` bunu otomatik algilar: `GW_TLS_CERT`/`GW_TLS_KEY` tanimliysa gateway HTTPS
dinler. Sertifikanin genel kismini (`gateway.crt`) istemciye (Mac) kopyalayip ona
guvenmesini soylemek gerekir; ozel anahtar (`gateway.key`) hicbir yere cikmaz.

## Audit
`/var/log/ai-gateway/audit.jsonl`: her satir bir oncekinin SHA-256 ozetini (`prev`) tasir; satir
silme/degistirme `audit_verify` ile yakalanir. Her satirin ozeti ayrica journald'ye `AUDIT {...}`
olarak yazilir (servis kullanicisi journald'yi degistiremez). Konsolda tam kontrol (root):
```
cd /opt/ai-gateway/src && PYTHONPATH=. /opt/ai-gateway/venv/bin/python -m gateway.auditcheck
```
Betik zinciri dogrular, dosyanin sonundan silinen veya tum zincirin yeniden yazildigi durumlari
journald kopyasiyla karsilastirarak yakalar. Deploy olaylari `deploy.jsonl` dosyasina yazilir.

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
Betik: yeni surumu ayri bir klasorde testlerden gecirir (gecmezse canli koda dokunmaz),
kurar, yeni servis dosyasinin istedigi TUM EnvironmentFile'larin (`/etc/ai-gateway/*.env`)
var oldugunu kontrol eder, arac sayisini ve sagligi (HTTP veya HTTPS, tls.env'e gore) dogrular,
servisi yeniden baslatir. Herhangi bir adim basarisizsa otomatik olarak onceki surume doner.
Her deneme audit kaydina yazilir.

Yeni bir `.env` dosyasi gerektiren bir degisiklik (orn. TLS) gonderiyorsan, `deploy.sh`
koşmadan once o dosyayi konsolda olustur — yoksa betik kurmadan once reddeder, servisi
bozmaz.
