#!/usr/bin/env python3
"""Verify the token works, and report its scopes and expiry. Read-only."""
import sys, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "lib"))
import meta

meta.load_env()
try:
    me = meta.whoami()
except Exception as e:
    print(f"FAIL: {e}"); sys.exit(1)
print(f"Authenticated as : {me.get('name')} ({me.get('id')})")

t = meta.token()
d = meta.get("debug_token", None, input_token=t).get("data", {})
fmt = lambda ts: "never" if not ts else datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
print(f"App              : {d.get('application')} ({d.get('app_id')})")
print(f"Valid            : {d.get('is_valid')}")
print(f"Expires          : {fmt(d.get('expires_at', 0))}")
print(f"Data access ends : {fmt(d.get('data_access_expires_at', 0))}")

scopes = set(d.get("scopes", []))
print(f"Scopes           : {', '.join(sorted(scopes)) or '(none)'}")
need = {"ads_read", "ads_management", "business_management", "pages_show_list", "pages_read_engagement"}
missing = need - scopes
if missing:
    print(f"\nMISSING SCOPES: {', '.join(sorted(missing))}")
    print("Re-issue the token with all five permissions. See README.md §2.")
    sys.exit(1)

accts = meta.ad_accounts()
print(f"\nAd accounts accessible: {len(accts)}")
for a in accts[:15]:
    print(f"  act_{a['account_id']:<20} {a.get('name','')[:34]:<34} {a.get('currency','')}")
if len(accts) > 15:
    print(f"  ... and {len(accts)-15} more (run scripts/discover.py for the full list)")
print("\nOK.")
