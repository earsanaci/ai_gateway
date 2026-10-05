"""Proxmox Backup Server istemcisi (salt-okunur token).

Guvenlik: PBS kendinden imzali sertifika kullanir. Sertifikayi ilk baglantida alip SHA-256
parmak izini PBS_FINGERPRINT ile karsilastiriyoruz; eslesmezse baglanmiyoruz (sabitleme).
Eslesirse yalnizca o sertifikaya guvenen bir TLS baglami kuruyoruz.

Erisilebilirlik: PBS Wake-on-LAN ile yalnizca yedek saatlerinde aciliyor olabilir. Kapaliyken
araclar cokmez; PBSOffline hatasi "PBS su an kapali/ulasilamiyor" der.
"""
import hashlib
import socket
import ssl

import httpx

from gateway.config import PBS_FINGERPRINT, PBS_HOST, PBS_PORT, PBS_TOKEN_ID, PBS_TOKEN_SECRET


class PBSOffline(RuntimeError):
    pass


def _norm_fp(fp):
    return fp.replace(":", "").replace(" ", "").lower()


def configured():
    return bool(PBS_HOST and PBS_TOKEN_ID and PBS_TOKEN_SECRET and PBS_FINGERPRINT)


def _fetch_cert_pem(host, port, timeout=5):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=timeout) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            der = tls.getpeercert(binary_form=True)
    return der, ssl.DER_cert_to_PEM_cert(der)


def _pinned_context(host, port, expected_fp):
    try:
        der, pem = _fetch_cert_pem(host, port)
    except (OSError, ssl.SSLError) as e:
        raise PBSOffline(f"PBS su an kapali veya ulasilamiyor ({host}:{port}): {type(e).__name__}") from e
    got = hashlib.sha256(der).hexdigest()
    if got != _norm_fp(expected_fp):
        raise PermissionError("PBS sertifika parmak izi beklenenle eslesmiyor; baglanti reddedildi "
                              "(sertifika yenilendiyse PBS_FINGERPRINT'i guncelle)")
    ctx = ssl.create_default_context(cadata=pem)
    ctx.check_hostname = False  # IP ile baglaniyoruz; guven parmak izi sabitlemesinden geliyor
    # PBS'in kendinden imzali sertifikasi "CA" olarak isaretli olmayabilir; yalnizca bu sertifikanin
    # kendisine (zincirsiz) guvenilmesine izin ver. Baska hicbir sertifika kabul edilmez.
    ctx.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
    return ctx


_client = None


def _get_client():
    global _client
    if not configured():
        raise RuntimeError("PBS yapilandirilmamis (/etc/ai-gateway/pbs.env)")
    if _client is None:
        ctx = _pinned_context(PBS_HOST, PBS_PORT, PBS_FINGERPRINT)
        _client = httpx.Client(
            base_url=f"https://{PBS_HOST}:{PBS_PORT}/api2/json",
            headers={"Authorization": f"PBSAPIToken={PBS_TOKEN_ID}:{PBS_TOKEN_SECRET}"},
            verify=ctx, timeout=20.0)
    return _client


def pbs_get(path, params=None):
    global _client
    try:
        r = _get_client().get(path, params=params)
    except httpx.TransportError as e:
        _client = None  # PBS yeniden basladiysa bir sonraki cagrida sertifikayi tekrar dogrula
        raise PBSOffline(f"PBS su an kapali veya ulasilamiyor: {type(e).__name__}") from e
    if r.status_code in (401, 403):
        raise PermissionError(f"PBS istegi reddetti (HTTP {r.status_code}); token yetkilerini kontrol et")
    r.raise_for_status()
    return r.json().get("data")
