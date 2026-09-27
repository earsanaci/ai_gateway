"""Calistirma: python -m gateway"""
import uvicorn

from gateway.auth import BearerAuth
from gateway.config import BIND, PORT
from gateway.core import mcp
# Araclari kaydet (import yan etkisiyle @mcp.tool calisir)
from gateway.tools import (ha_automations, ha_control, ha_read,  # noqa: F401
                           proxmox_backup_jobs, proxmox_control, proxmox_read)


def main():
    uvicorn.run(BearerAuth(mcp.streamable_http_app()), host=BIND, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
