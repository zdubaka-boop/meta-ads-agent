#!/usr/bin/env python3
"""Audit EXISTING ads for creative enhancements that are switched on.

  python3 scripts/audit_enhancements.py act_123456
  python3 scripts/audit_enhancements.py act_123456 --campaign 120250...
  python3 scripts/audit_enhancements.py act_123456 --csv outputs/audit.csv

Read-only. Reports only — it never changes an ad. Turning enhancements off on a
LIVE ad requires a new creative and repointing the ad, which resets review, the
learning phase, and social proof. That is a human decision, per ad.
"""
import argparse, csv, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "lib"))
import meta

meta.load_env()
ap = argparse.ArgumentParser()
ap.add_argument("account")
ap.add_argument("--campaign", help="limit to one campaign id")
ap.add_argument("--csv", help="write full results to this path")
ap.add_argument("--limit", type=int, default=5000)
args = ap.parse_args()

acct = meta.account(args.account)
edge = f"{args.campaign}/ads" if args.campaign else f"{acct}/ads"
print(f"Scanning {edge} ...")
ads = meta.get_all(edge,
    "id,name,status,effective_status,adset{id,name},campaign{id,name},"
    "creative{id,degrees_of_freedom_spec}", limit=100, cap=args.limit)
print(f"{len(ads)} ad(s) found.\n")

rows, flagged = [], 0
for a in ads:
    cfs = ((a.get("creative") or {}).get("degrees_of_freedom_spec") or {}).get("creative_features_spec", {}) or {}
    on = sorted(k for k, v in cfs.items() if v.get("enroll_status") == "OPT_IN")
    rows.append({
        "ad_id": a["id"], "ad_name": a.get("name", ""),
        "status": a.get("status", ""), "effective_status": a.get("effective_status", ""),
        "campaign": (a.get("campaign") or {}).get("name", ""),
        "adset": (a.get("adset") or {}).get("name", ""),
        "enhancements_on_count": len(on), "enhancements_on": ";".join(on),
    })
    if on:
        flagged += 1
        print(f"  {a['id']:<20} {(a.get('name') or '')[:38]:<38} {a.get('effective_status',''):<16} "
              f"{len(on)} ON: {', '.join(on[:5])}{' ...' if len(on) > 5 else ''}")

print(f"\n{flagged}/{len(ads)} ad(s) have at least one enhancement enabled.")
if args.csv:
    p = Path(args.csv); p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["ad_id"])
        w.writeheader(); w.writerows(rows)
    print(f"Full report: {p}")
print("\nNote: multi-advertiser ads (contextual_multi_ads) is NOT included — Meta "
      "does not return it. Check that one in Ads Manager.")
print("Nothing was modified.")
