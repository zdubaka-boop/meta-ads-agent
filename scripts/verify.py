#!/usr/bin/env python3
"""Read every created object back from Meta and diff it against the spec.

  python3 scripts/verify.py --state outputs/<name>-state.json --spec <spec.json>

Exit code 1 if any field does not match. Nothing is modified.
"""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "lib"))
import meta

ROOT = meta.load_env()
PASS, FAIL = "  ok  ", "  FAIL"
rows = []


def check(label, want, got):
    ok = str(want) == str(got)
    rows.append(ok)
    print(f"{PASS if ok else FAIL}  {label:<38} want={want!s:<24} got={got}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--spec", required=True)
    args = ap.parse_args()

    state = json.loads(Path(args.state).read_text())
    spec = json.loads(Path(args.spec).read_text()) if args.spec.endswith(".json") else None
    if spec is None:
        import yaml; spec = yaml.safe_load(Path(args.spec).read_text())

    c, d = spec["campaign"], spec.get("defaults", {})
    cbo = (c.get("budget_mode") or "").upper() == "CBO"

    print("=" * 78)
    print("CAMPAIGN")
    got = meta.get(state["campaign_id"],
                   "name,objective,status,effective_status,daily_budget,special_ad_categories")
    check("campaign.name", c["name"], got.get("name"))
    check("campaign.objective", c["objective"], got.get("objective"))
    check("campaign.status", "PAUSED", got.get("status"))
    if cbo:
        check("campaign.daily_budget", c["daily_budget_minor"], got.get("daily_budget"))
    else:
        check("campaign.daily_budget (ABO=none)", "None", got.get("daily_budget", "None"))

    for a in spec["adsets"]:
        aid = state["adsets"].get(a["name"])
        if not aid:
            print(f"{FAIL}  adset '{a['name']}' missing from state"); rows.append(False); continue
        print(f"\nAD SET  {a['name']}  ({aid})")
        g = meta.get(aid, "name,status,daily_budget,optimization_goal,billing_event,targeting,campaign_id")
        check("adset.name", a["name"], g.get("name"))
        check("adset.status", "PAUSED", g.get("status"))
        check("adset.campaign_id", state["campaign_id"], g.get("campaign_id"))
        check("adset.optimization_goal", a.get("optimization_goal", "LINK_CLICKS"), g.get("optimization_goal"))
        if cbo:
            check("adset.daily_budget (CBO=none)", "None", g.get("daily_budget", "None"))
        else:
            check("adset.daily_budget", a["daily_budget_minor"], g.get("daily_budget"))
        want_geo = (a.get("targeting") or {}).get("geo_locations", {}).get("countries")
        got_geo = (g.get("targeting") or {}).get("geo_locations", {}).get("countries")
        check("adset.geo_locations.countries", want_geo, got_geo)

        for ad in a["ads"]:
            adid = state["ads"].get(ad["name"])
            if not adid:
                print(f"{FAIL}  ad '{ad['name']}' missing from state"); rows.append(False); continue
            ga = meta.get(adid, "name,status,adset_id,creative{id,degrees_of_freedom_spec,object_story_spec}")
            cr = ga.get("creative", {})
            oss = cr.get("object_story_spec", {})
            data = oss.get("link_data") or oss.get("video_data") or {}
            print(f"\n  AD  {ad['name']}  ({adid})  creative={cr.get('id')}")
            check("  ad.status", "PAUSED", ga.get("status"))
            check("  ad.adset_id", aid, ga.get("adset_id"))
            check("  ad.page_id", ad.get("page_id") or d.get("page_id"), oss.get("page_id"))
            want_link = (ad.get("link") or d.get("link") or "").rstrip("/")
            got_link = (data.get("link") or (data.get("call_to_action", {}).get("value", {}) or {}).get("link") or "").rstrip("/")
            check("  ad.link", want_link, got_link)

            cfs = (cr.get("degrees_of_freedom_spec") or {}).get("creative_features_spec", {}) or {}
            optin = [k for k, v in cfs.items() if v.get("enroll_status") == "OPT_IN"]
            optout = [k for k, v in cfs.items() if v.get("enroll_status") == "OPT_OUT"]
            ok = not optin and bool(optout)
            rows.append(ok)
            print(f"{PASS if ok else FAIL}    enhancements  {len(optout)} OPT_OUT / "
                  f"{len(optin)} OPT_IN{'  -> ' + ', '.join(optin) if optin else ''}")

            # Meta does not return contextual_multi_ads. Report, never claim.
            print(f"  ....    multi-advertiser ads: NOT VERIFIABLE via API "
                  f"(field absent on read-back) — confirm in Ads Manager")

    n_fail = rows.count(False)
    print("\n" + "=" * 78)
    print(f"{len(rows) - n_fail}/{len(rows)} checks passed."
          + ("  ALL MATCH SPEC." if not n_fail else f"  {n_fail} MISMATCH(ES)."))
    print("Reminder: multi-advertiser ads cannot be confirmed programmatically.")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
