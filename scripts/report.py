#!/usr/bin/env python3
"""What is actually happening in an account. Read-only, always.

  python3 scripts/report.py act_123                        # campaigns, last 7d
  python3 scripts/report.py act_123 --level adset --days 30
  python3 scripts/report.py act_123 --campaign 120... --level ad
  python3 scripts/report.py act_123 --level ad --sort cpa --worst 10

--worst is the kill list: the N worst rows by whatever you sorted on, with
spend high enough to mean something.
"""
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "lib"))
import meta

meta.load_env()
PRESETS = {1: "today", 7: "last_7d", 14: "last_14d", 30: "last_30d", 90: "last_90d"}


def rows_for(edge, level, preset):
    key = {"campaign": "campaign_id", "adset": "adset_id", "ad": "ad_id"}[level]
    name_key = {"campaign": "campaign_name", "adset": "adset_name", "ad": "ad_name"}[level]
    try:
        raw = meta.get_all(edge, f"{key},{name_key},spend,impressions,clicks,ctr,cpc,"
                                 f"actions,cost_per_action_type",
                           limit=200, cap=3000, level=level, date_preset=preset)
    except meta.MetaError as e:
        sys.exit(f"Could not read insights: {e}")
    out = []
    for r in raw:
        acts = {a["action_type"]: float(a["value"]) for a in (r.get("actions") or [])}
        cpa_map = {a["action_type"]: float(a["value"])
                   for a in (r.get("cost_per_action_type") or [])}
        pick = lambda m: (m.get("purchase") or m.get("offsite_conversion.fb_pixel_purchase")
                          or m.get("lead") or m.get("link_click"))
        cpa = pick(cpa_map)
        out.append({"id": r.get(key), "name": r.get(name_key) or r.get(key),
                    "spend": float(r.get("spend") or 0),
                    "results": pick(acts) or 0,
                    "cpa": cpa, "ctr": float(r.get("ctr") or 0),
                    "cpc": float(r.get("cpc") or 0),
                    "clicks": int(r.get("clicks") or 0),
                    "impr": int(r.get("impressions") or 0)})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("account")
    ap.add_argument("--level", choices=["campaign", "adset", "ad"], default="campaign")
    ap.add_argument("--campaign", help="limit to one campaign")
    ap.add_argument("--adset", help="limit to one ad set")
    ap.add_argument("--days", type=int, default=7, choices=sorted(PRESETS))
    ap.add_argument("--sort", choices=["spend", "cpa", "results", "ctr"], default="spend")
    ap.add_argument("--worst", type=int, help="show only the N worst rows by --sort")
    ap.add_argument("--min-spend", type=float, default=0.0,
                    help="ignore rows below this spend (default 0)")
    args = ap.parse_args()

    acct = meta.account(args.account)
    edge = f"{args.adset}/insights" if args.adset else \
           f"{args.campaign}/insights" if args.campaign else f"{acct}/insights"
    preset = PRESETS[args.days]
    data = [r for r in rows_for(edge, args.level, preset) if r["spend"] >= args.min_spend]
    if not data:
        print(f"No spend at {args.level} level in the last {args.days} day(s)"
              + (f" above {args.min_spend}" if args.min_spend else "") + ".")
        return

    cur = meta.get(acct, "currency").get("currency", "")
    if args.sort == "cpa":
        # No CPA means no results at all: worst possible, so sort it last/worst.
        data.sort(key=lambda r: (r["cpa"] is None, r["cpa"] or 0), reverse=bool(args.worst))
    else:
        data.sort(key=lambda r: r[args.sort] or 0, reverse=not args.worst)
    if args.worst:
        data = data[:args.worst]

    total_spend = sum(r["spend"] for r in data)
    total_res = sum(r["results"] for r in data)
    print("=" * 96)
    print(f"  {args.level.upper()}S — last {args.days} day(s) — {acct} ({cur})"
          + (f"   [{args.worst} worst by {args.sort}]" if args.worst else ""))
    print("=" * 96)
    print(f"  {'NAME':<44} {'SPEND':>10} {'RESULTS':>8} {'CPA':>9} {'CTR%':>7} {'CLICKS':>8}")
    print("  " + "-" * 92)
    for r in data:
        cpa = f"{r['cpa']:.2f}" if r["cpa"] else "—"
        print(f"  {r['name'][:44]:<44} {r['spend']:>10.2f} {r['results']:>8.0f} "
              f"{cpa:>9} {r['ctr']:>7.2f} {r['clicks']:>8}")
    print("  " + "-" * 92)
    blended = f"{total_spend/total_res:.2f}" if total_res else "—"
    print(f"  {'TOTAL':<44} {total_spend:>10.2f} {total_res:>8.0f} {blended:>9}")
    print(f"\n  Nothing was modified. To act on this, see set_status.py / set_budget.py")



def _print_usage():
    """Where the account stands on its Meta rate budget."""
    try:
        print("\n  " + meta.usage_line())
    except Exception:
        pass

if __name__ == "__main__":
    main()
    _print_usage()
