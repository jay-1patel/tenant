"""Dry-run of the incoming poller fetch - no replies are sent."""
import sys, os, asyncio
from datetime import datetime, timedelta

sys.path.insert(0, r"C:\keya\leeway_tenant_5\backend")
sys.path.insert(0, r"C:\keya\leeway_tenant_5")
sys.path.insert(0, os.path.join(r"C:\keya\leeway_tenant_5", "routing"))

from routing.config import (
    SEND2_USERNAME, SEND2_PASSWORD, SEND2_INCOMING_URL,
)
from routing.config import DB_PATH

import httpx

async def main():
    print(f"creds: user={SEND2_USERNAME!r} pass set={bool(SEND2_PASSWORD)}")
    print(f"incoming url: {SEND2_INCOMING_URL}")
    print(f"routing DB_PATH: {DB_PATH}")

    now = datetime.now()
    payload = {
        "user_name": SEND2_USERNAME,
        "password": SEND2_PASSWORD,
        "from_date": (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
        "to_date": now.strftime("%Y-%m-%d %H:%M:%S"),
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(SEND2_INCOMING_URL, json=payload)
    print(f"status: {resp.status_code}")
    text = resp.text
    if "No Data Found" in text:
        print("RESULT: No Data Found (no inbound in last hour)")
        return
    rows = resp.json()
    if not isinstance(rows, list):
        print(f"unexpected: {text[:200]}")
        return
    skip = {"sent", "delivered", "failed", "read"}
    inbound = [r for r in rows if not str(r.get("status", "")).strip().lower() in skip]
    print(f"total rows: {len(rows)} | inbound (would process): {len(inbound)}")
    for r in inbound:
        print(f"  wa_id={str(r.get('Number',''))} status={r.get('status')!r} text={str(r.get('Message',''))[:60]!r} msgid={str(r.get('messageid',''))[:16]}")

asyncio.run(main())