"""Ortam degiskenlerinden okunan ayarlar. Gercek degerler /etc/ai-gateway/*.env dosyalarindadir; repoya girmez."""
import os

PVE_HOST = os.environ["PVE_HOST"].rstrip("/")
PVE_TOKEN_ID = os.environ["PVE_TOKEN_ID"]
PVE_TOKEN_SECRET = os.environ["PVE_TOKEN_SECRET"]
GATEWAY_TOKEN = os.environ["GATEWAY_TOKEN"]
BIND = os.environ.get("GW_BIND", "127.0.0.1")
PORT = int(os.environ.get("GW_PORT", "8765"))
PVE_CA = os.environ.get("PVE_CA")  # ileride Proxmox sertifikasini sabitlemek icin
AUDIT_LOG = os.environ.get("GW_AUDIT_LOG", "/var/log/ai-gateway/audit.jsonl")
HA_URL = os.environ.get("HA_URL", "").rstrip("/")
HA_TOKEN = os.environ.get("HA_TOKEN", "")
PVE_OP_TOKEN_ID = os.environ.get("PVE_OP_TOKEN_ID", "")
PVE_OP_TOKEN_SECRET = os.environ.get("PVE_OP_TOKEN_SECRET", "")
PVE_BACKUP_STORAGE = os.environ.get("PVE_BACKUP_STORAGE", "backup_usb")
# Kapatilamaz/yeniden baslatilamaz misafirler (gateway'in kendisi dahil)
PVE_PROTECTED = {int(x) for x in os.environ.get("PVE_PROTECTED", "109").split(",") if x.strip()}
PVE_ADMIN_TOKEN_ID = os.environ.get("PVE_ADMIN_TOKEN_ID", "")
PVE_ADMIN_TOKEN_SECRET = os.environ.get("PVE_ADMIN_TOKEN_SECRET", "")

APPROVAL_TTL = 600  # onay suresi: 10 dakika
HA_SENSITIVE = [x.strip().lower() for x in os.environ.get(
    "HA_SENSITIVE",
    "sunucu,kombi,isitici,3d_yazici,yazici_3d,prizler,priz_grubu").split(",") if x.strip()]
AUTO_BACKUP_DIR = os.environ.get("GW_AUTOMATION_BACKUP_DIR", "/var/log/ai-gateway/automation-backups")

if len(GATEWAY_TOKEN) < 32:
    raise SystemExit("GATEWAY_TOKEN en az 32 karakter olmali")

TLS_CERT = os.environ.get("GW_TLS_CERT", "")
TLS_KEY = os.environ.get("GW_TLS_KEY", "")
