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

        # One call for the whole ad set, not one per ad. Each of these expands
        # three nested creative objects server-side; asking 24 times is 24
        # separate expansions, and Meta's binding limit is processing time,
        # not call count. Same data, a fraction of the cost.
        fetched = {x["id"]: x for x in meta.get_all(
            f"{aid}/ads", "id,name,status,adset_id,creative{id,degrees_of_freedom_spec,"
                          "object_story_spec,asset_feed_spec}", limit=50, cap=1000)}

        for ad in a["ads"]:
            adid = state["ads"].get(ad["name"])
            if not adid:
                print(f"{FAIL}  ad '{ad['name']}' missing from state"); rows.append(False); continue
            ga = fetched.get(adid)
            if ga is None:
                # Created but not returned by the edge — read it directly rather
                # than reporting a pass on data we never received.
                ga = meta.get(adid, "name,status,adset_id,creative{id,degrees_of_freedom_spec,"
                                    "object_story_spec,asset_feed_spec}")
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

            # --- content checks, independent of the spec ---------------------
            # A spec that was parsed wrongly still "matches" whatever it built,
            # so these assert things that are true of a correct ad regardless
            # of what the spec says. This is what catches a parsing bug.
            feed = cr.get("asset_feed_spec") or {}
            stored_bodies = [b.get("text", "") for b in feed.get("bodies", [])] or \
                            ([data.get("message")] if data.get("message") else [])
            stored_titles = [t.get("text", "") for t in feed.get("titles", [])] or \
                            ([data.get("name") or data.get("title")]
                             if (data.get("name") or data.get("title")) else [])

            # 1. A pipe surviving into live ad copy means the variant split
            #    never happened — the reader stored "A | B | C" as one string.
            leaked = [t for t in stored_bodies + stored_titles if t and "|" in t]
            rows.append(not leaked)
            if leaked:
                print(f"{FAIL}    copy contains a literal '|' — variants were NOT split:")
                for t in leaked[:3]:
                    print(f"           {t[:78]}")
            else:
                print(f"{PASS}    no unsplit '|' in the stored copy")

            # 2. Variant counts must match what the sheet asked for.
            want_b = len(ad.get("bodies") or ([ad["body"]] if ad.get("body") else []))
            want_t = len(ad.get("headlines") or ([ad["headline"]] if ad.get("headline") else []))
            ok_counts = (len(stored_bodies) == want_b and len(stored_titles) == want_t)
            rows.append(ok_counts)
            print(f"{PASS if ok_counts else FAIL}    variants  "
                  f"bodies {len(stored_bodies)}/{want_b}  headlines {len(stored_titles)}/{want_t}")

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
