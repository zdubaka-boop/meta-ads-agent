#!/usr/bin/env python3
"""Copy an ad set inside its campaign, changing only what you name.

  python3 scripts/duplicate_adset.py 120... --name "Spring | CZ | Broad"
  python3 scripts/duplicate_adset.py 120... --name "..." --countries CZ,SK --execute
  python3 scripts/duplicate_adset.py 120... --name "..." --no-ads --execute

"Same ad set, different country" is most of what adding an ad set means. The
copy is always created PAUSED and the original is never touched.
"""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "lib"))
import meta

meta.load_env()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("adset")
    ap.add_argument("--name", required=True, help="name for the copy")
    ap.add_argument("--countries", help="ISO codes, e.g. CZ,SK. Omit to keep the same.")
    ap.add_argument("--daily", type=float, help="new daily budget in account currency")
    ap.add_argument("--no-ads", action="store_true", help="copy the ad set without its ads")
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()

    src = meta.get(args.adset, "name,campaign_id,daily_budget,targeting,account_id")
    geo = (src.get("targeting") or {}).get("geo_locations") or {}
    n_ads = len(meta.get_all(f"{args.adset}/ads", "id", cap=1000))

    print("=" * 70)
    print(f"DUPLICATE — {src.get('name')}")
    print("=" * 70)
    print(f"  new name    {args.name}")
    print(f"  countries   {args.countries or ', '.join(geo.get('countries') or ['(unchanged)'])}")
    print(f"  budget      {f'{args.daily:.2f}' if args.daily else '(unchanged)'}")
    print(f"  ads         {'not copied' if args.no_ads else f'{n_ads} copied too'}")
    print(f"  the copy is created PAUSED. '{src.get('name')}' is not touched.")

    if not args.execute:
        print("\nDRY RUN — nothing created. Add --execute.")
        return

    new_id = meta.copy_object(args.adset, "adset", campaign_id=src.get("campaign_id"),
                              deep_copy="false" if args.no_ads else "true",
                              rename_strategy="NO_RENAME")
    if not new_id:
        sys.exit("Meta did not return a new ad set id.")
    print(f"\n  created {new_id}")

    params = {"name": args.name}
    if args.countries:
        t = dict(src.get("targeting") or {})
        g = dict(geo)
        for k in ("country_groups", "cities", "regions"):
            g.pop(k, None)
        g["countries"] = [c.strip().upper() for c in args.countries.split(",") if c.strip()]
        t["geo_locations"] = g
        params["targeting"] = json.dumps(t)
    if args.daily:
        params["daily_budget"] = str(int(round(args.daily * 100)))
    meta.post(new_id, params, "update_copy")

    after = meta.get(new_id, "name,status,daily_budget,targeting")
    ag = (after.get("targeting") or {}).get("geo_locations", {}) or {}
    print(f"  name        {after.get('name')}")
    print(f"  status      {after.get('status')}")
    print(f"  countries   {ag.get('countries')}")
    print(f"  budget      {after.get('daily_budget') or '(campaign level)'}")


if __name__ == "__main__":
    main()
