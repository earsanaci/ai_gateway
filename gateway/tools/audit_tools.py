"""Audit kayitlarini okuma ve dogrulama (L0, salt-okunur)."""
from gateway import audit as _audit
from gateway.core import audited, mcp


@mcp.tool()
@audited()
def audit_get_recent(limit: int = 30, tool: str = "", only_changes: bool = False) -> list[dict]:
    """Gateway'in son audit kayitlarini getirir (en yeni once, en fazla 100). tool ile arac adina
    gore suzulebilir; only_changes=True ise yalnizca degisiklik yapan islemler (L1+ ve
    uygulanan degisiklik olaylari). Uzun parametreler kisaltilir. Salt-okunur."""
    return _audit.recent(limit, tool, only_changes)


@mcp.tool()
@audited()
def audit_verify() -> dict:
    """Audit dosyasinin hash zincirini dogrular: satir silinmis veya degistirilmisse tespit eder.
    Salt-okunur; dosyaya yazmaz."""
    return _audit.verify()
