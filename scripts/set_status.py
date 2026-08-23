#!/usr/bin/env python3
"""Turn things off, or on. Off is easy. On is deliberately hard.

  # OFF — dry run, then do it
  python3 scripts/set_status.py --off --ads 120...,120...
  python3 scripts/set_status.py --off --ads 120...,120... --execute
  python3 scripts/set_status.py --off --adset 120... --execute        # every ad in it

  # ON — launching a whole campaign, all three levels
  python3 scripts/set_status.py --launch --campaign 120...            # shows the tree + cost
  python3 scripts/set_status.py --launch --campaign 120... --execute --authorise-daily 50.00

WHY --authorise-daily EXISTS
  Meta only delivers when the campaign, its ad sets AND its ads are all active,
  so launching means switching on everything at once. To do that you must state
  the daily spend you are authorising, and it must match what the campaign
  actually holds. If you think it is 5.00 and it is 500.00, the numbers disagree
  and nothing happens. A yes/no prompt cannot catch that; a number can.
"""
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "lib"))
import meta

meta.load_env()


def collect(args):
    """-> (label, [(id, name, kind)]) for whatever the user pointed at."""
    out = []
    if args.ads:
        for i in [x.strip() for x in args.ads.split(",") if x.strip()]:
            d = meta.get(i, "name,status")
            out.append((i, d.get("name", i), "ad"))
        return "ads", out
    if args.adset:
        for a in meta.get_all(f"{args.adset}/ads", "id,name,status", cap=1000):
            out.append((a["id"], a.get("name", a["id"]), "ad"))
        return f"every ad in ad set {args.adset}", out
    if args.campaign and not args.launch:
        for s in meta.get_all(f"{args.campaign}/adsets", "id,name", cap=200):
            for a in meta.get_all(f"{s['id']}/ads", "id,name,status", cap=1000):
                out.append((a["id"], a.get("name", a["id"]), "ad"))
        return f"every ad in campaign {args.campaign}", out
    sys.exit("Point at something: --ads, --adset or --campaign")


def launch_tree(campaign_id):
    """Everything that must be switched on for the campaign to deliver."""
    camp = meta.get(campaign_id, "name,status,daily_budget,lifetime_budget")
    tree = [(campaign_id, camp.get("name"), "campaign", camp.get("status"))]
    budget = int(camp.get("daily_budget") or 0)
    for s in meta.get_all(f"{campaign_id}/adsets", "id,name,status,daily_budget", cap=200):
        tree.append((s["id"], s.get("name"), "adset", s.get("status")))
        budget += int(s.get("daily_budget") or 0)
        for a in meta.get_all(f"{s['id']}/ads", "id,name,status", cap=1000):
            tree.append((a["id"], a.get("name"), "ad", a.get("status")))
    return camp, tree, budget


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--off", action="store_true", help="pause. Never costs anything.")
    g.add_argument("--launch", action="store_true",
                   help="switch a whole campaign on. THIS SPENDS MONEY.")
    ap.add_argument("--ads", help="comma separated ad ids")
    ap.add_argument("--adset")
    ap.add_argument("--campaign")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--authorise-daily", type=float,
                    help="required with --launch --execute: the daily budget you are "
                         "authorising, in the account currency")
    args = ap.parse_args()

    # ---------------------------------------------------------------- OFF
    if args.off:
        label, items = collect(args)
        live = [x for x in items]
        print("=" * 74)
        print(f"PAUSE — {label}")
        print(f"  {len(live)} object(s). Pausing never costs anything and is reversible.")
        print("=" * 74)
        for i, n, _ in live[:40]:
            print(f"  {i}  {n[:56]}")
        if len(live) > 40:
            print(f"  ... and {len(live)-40} more")
        if not args.execute:
            print("\nDRY RUN — nothing changed. Add --execute to pause them.")
            return
        done, failed = 0, []
        for i, n, _ in live:
            try:
                meta.post(i, {"status": "PAUSED"}, "pause")
                done += 1
            except Exception as e:
                failed.append((i, str(e)[:90]))
        print(f"\nPaused {done}. {len(failed)} failed.")
        for i, e in failed:
            print(f"  {i}: {e}")
        return

    # ------------------------------------------------------------- LAUNCH
    if not args.campaign:
        sys.exit("--launch needs --campaign")
    camp, tree, budget_minor = launch_tree(args.campaign)
    acct = meta.get(args.campaign, "account_id").get("account_id", "")
    cur = meta.get(meta.account(acct), "currency").get("currency", "")
    daily = budget_minor / 100.0
    n_sets = sum(1 for t in tree if t[2] == "adset")
    n_ads = sum(1 for t in tree if t[2] == "ad")
    already = [t for t in tree if t[3] == "ACTIVE"]

    print("=" * 74)
    print(f"LAUNCH — {camp.get('name')}")
    print("=" * 74)
    print(f"  campaign     {args.campaign}")
    print(f"  ad sets      {n_sets}")
    print(f"  ads          {n_ads}")
    print(f"  already on   {len(already)}")
    print()
    print(f"  >>> THIS WILL START SPENDING {daily:.2f} {cur} PER DAY <<<")
    print(f"      about {daily*7:.2f} {cur} a week, {daily*30:.2f} {cur} a month")
    print()
    print("  Everything below is switched ON. Meta only delivers when the campaign,")
    print("  its ad sets and its ads are all active.")
    for i, n, kind, st in tree[:30]:
        mark = "  (already on)" if st == "ACTIVE" else ""
        print(f"    {kind:<9} {(n or i)[:52]:<52}{mark}")
    if len(tree) > 30:
        print(f"    ... and {len(tree)-30} more objects")

    if not args.execute:
        print("\nDRY RUN — nothing changed.")
        print(f"To launch, re-run with:  --execute --authorise-daily {daily:.2f}")
        return

    if args.authorise_daily is None:
        sys.exit(f"\nREFUSED: --authorise-daily is required to launch.\n"
                 f"This campaign will spend {daily:.2f} {cur}/day. Re-run with "
                 f"--authorise-daily {daily:.2f} to confirm you know that.")
    if abs(args.authorise_daily - daily) > 0.01:
        sys.exit(f"\nREFUSED: you authorised {args.authorise_daily:.2f} {cur}/day but this "
                 f"campaign will spend {daily:.2f} {cur}/day.\n"
                 f"Nothing was changed. Check the budget before launching.")

    # Ads first, then ad sets, then the campaign: if anything fails partway,
    # the campaign is still off and nothing has delivered.
    order = ([t for t in tree if t[2] == "ad"] +
             [t for t in tree if t[2] == "adset"] +
             [t for t in tree if t[2] == "campaign"])
    done, failed = [], []
    for i, n, kind, st in order:
        if st == "ACTIVE":
            continue
        try:
            meta.post(i, {"status": "ACTIVE"}, f"activate_{kind}")
            done.append((kind, i, n))
            print(f"  ON  {kind:<9} {i}  {n or ''}")
        except Exception as e:
            failed.append((kind, i, str(e)[:90]))
            print(f"  FAILED {kind} {i}: {str(e)[:90]}")
            if kind in ("adset", "campaign"):
                print("\n  Stopping here — the campaign was NOT switched on, so nothing "
                      "is delivering.")
                break
    print(f"\nActivated {len(done)}, {len(failed)} failed.")
    if not failed:
        print(f"LIVE. Spending up to {daily:.2f} {cur}/day from now.")
        print("To stop:  python3 scripts/set_status.py --off --campaign "
              f"{args.campaign} --execute")


if __name__ == "__main__":
    main()
