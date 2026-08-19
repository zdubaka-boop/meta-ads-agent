#!/usr/bin/env python3
"""Read-only inventory. Never modifies anything.

  python3 scripts/discover.py                 # list all ad accounts
  python3 scripts/discover.py act_123456      # full asset + campaign profile
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "lib"))
import meta

STATUS = {1: "ACTIVE", 2: "DISABLED", 3: "UNSETTLED", 7: "PENDING_REVIEW",
          8: "PENDING_CLOSURE", 9: "GRACE", 100: "CLOSED", 101: "ANY_ACTIVE", 201: "ANY_CLOSED"}

meta.load_env()
argv = [a for a in sys.argv[1:] if not a.startswith("-")]

if not argv:
    accts = meta.ad_accounts()
    print(f"AD ACCOUNTS ({len(accts)})\n")
    for a in accts:
        biz = (a.get("business") or {}).get("name", "-")
        print(f"  act_{a['account_id']:<20} {(a.get('name') or '')[:32]:<32} "
              f"{STATUS.get(a.get('account_status'), '?'):<12} {a.get('currency',''):<4} "
              f"{(a.get('timezone_name') or '')[:20]:<20} biz={biz[:22]}")
    print("\nProfile one with: python3 scripts/discover.py act_<id>")
    sys.exit(0)

acct = meta.account(argv[0])
info = meta.get(acct, "name,account_status,currency,timezone_name,min_daily_budget,business{id,name}")
print(f"ACCOUNT {acct} — {info.get('name')}")
print(f"  currency={info.get('currency')}  tz={info.get('timezone_name')}  "
      f"min_daily_budget={info.get('min_daily_budget')} (minor units)")

assets = meta.account_assets(acct)
for key, label in [("pages", "PAGES"), ("instagram", "INSTAGRAM"), ("pixels", "PIXELS"),
                   ("catalogs", "CATALOGS"), ("audiences", "AUDIENCES")]:
    v = assets.get(key)
    if isinstance(v, dict):
        print(f"\n{label}: unavailable — {v.get('error','')[:90]}")
        continue
    print(f"\n{label} ({len(v)})")
    for x in v[:25]:
        print(f"   {x.get('id'):<20} {x.get('name') or x.get('username') or ''}")
    if not v:
        print("   (none)")

camps = meta.get_all(f"{acct}/campaigns",
                     "id,name,objective,status,effective_status,daily_budget,lifetime_budget")
print(f"\nCAMPAIGNS ({len(camps)})")
for c in camps[:40]:
    budget = c.get("daily_budget") or c.get("lifetime_budget") or "-"
    mode = "CBO" if budget != "-" else "ABO"
    print(f"   {c['id']:<20} {(c.get('name') or '')[:36]:<36} {c.get('objective',''):<18} "
          f"{c.get('status',''):<8} {mode}")
if len(camps) > 40:
    print(f"   ... and {len(camps)-40} more")

print("\nNothing was modified.")
