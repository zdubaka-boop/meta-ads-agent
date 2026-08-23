#!/usr/bin/env python3
"""Change a budget. The number always comes from you, never from a guess.

  python3 scripts/set_budget.py 120... --daily 25.00
  python3 scripts/set_budget.py 120... --daily 25.00 --execute

Works on a campaign (CBO) or an ad set (ABO). The amount is in the account's
own currency - 25.00 means twenty-five, not twenty-five cents.

A large jump resets Meta's learning phase, so anything over +/-30% is called
out before you commit to it.
"""
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "lib"))
import meta

meta.load_env()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("object_id", help="campaign id (CBO) or ad set id (ABO)")
    ap.add_argument("--daily", type=float, required=True,
                    help="new daily budget in the account currency, e.g. 25.00")
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()

    # Campaigns and ad sets expose different fields, and asking for the wrong
    # one is a hard error rather than a null - so try campaign shape first.
    try:
        obj = meta.get(args.object_id,
                       "name,daily_budget,lifetime_budget,account_id,objective")
        kind = "campaign"
    except meta.MetaError:
        obj = meta.get(args.object_id,
                       "name,daily_budget,lifetime_budget,campaign_id")
        kind = "ad set"
    acct_id = obj.get("account_id")
    if not acct_id:
        acct_id = meta.get(obj["campaign_id"], "account_id").get("account_id")
    acct = meta.account(acct_id)
    info = meta.get(acct, "currency,min_daily_budget")
    cur = info.get("currency", "")
    minimum = int(info.get("min_daily_budget") or 0)

    now_minor = int(obj.get("daily_budget") or 0)
    new_minor = int(round(args.daily * 100))

    print("=" * 70)
    print(f"BUDGET — {kind}: {obj.get('name')}")
    print("=" * 70)
    if obj.get("lifetime_budget") and not now_minor:
        sys.exit(f"This {kind} uses a LIFETIME budget, not a daily one. "
                 f"Change it in Ads Manager, or say so and it can be handled separately.")
    if not now_minor:
        print(f"  currently   no daily budget on this {kind}")
        print(f"              (its budget probably sits at the other level — check "
              f"whether the campaign is CBO)")
    else:
        print(f"  currently   {now_minor/100:.2f} {cur} / day")
    print(f"  new         {new_minor/100:.2f} {cur} / day")

    if new_minor < minimum:
        sys.exit(f"\nREFUSED: below this account's minimum of {minimum/100:.2f} {cur}/day.")

    if now_minor:
        pct = (new_minor - now_minor) / now_minor * 100
        print(f"  change      {pct:+.0f}%")
        if abs(pct) > 30:
            print(f"\n  NOTE: a change this size resets the learning phase. Meta will")
            print(f"        re-learn delivery from scratch, and performance usually dips")
            print(f"        for a few days. Smaller, repeated steps avoid that.")
    if new_minor > now_minor:
        extra = (new_minor - now_minor) / 100
        print(f"\n  >>> this INCREASES daily spend by {extra:.2f} {cur} "
              f"({extra*30:.2f} {cur} a month) <<<")

    if not args.execute:
        print("\nDRY RUN — nothing changed. Add --execute to apply.")
        return
    meta.post(args.object_id, {"daily_budget": str(new_minor)}, "set_budget")
    after = meta.get(args.object_id, "daily_budget")
    got = int(after.get("daily_budget") or 0)
    print(f"\nApplied. Meta now reports {got/100:.2f} {cur}/day"
          + ("  ✓" if got == new_minor else f"  MISMATCH — expected {new_minor/100:.2f}"))


if __name__ == "__main__":
    main()
