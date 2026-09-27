import os

os.environ.setdefault("PVE_HOST", "https://pve.invalid:8006")
os.environ.setdefault("PVE_TOKEN_ID", "test@pve!t")
os.environ.setdefault("PVE_TOKEN_SECRET", "x")
os.environ.setdefault("GATEWAY_TOKEN", "t" * 40)
os.environ.setdefault("GW_AUDIT_LOG", "/tmp/ai-gateway-test-audit.jsonl")
