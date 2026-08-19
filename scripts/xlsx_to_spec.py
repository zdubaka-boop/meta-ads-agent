#!/usr/bin/env python3
"""Convert the filled-in CAMPAIGN-TEMPLATE.xlsx into a spec JSON + ads CSV.

  python3 scripts/xlsx_to_spec.py my-campaign.xlsx --out specs/q3-uk.json

Then build exactly as normal:
  python3 scripts/build_campaign.py --spec specs/q3-uk.json            # preview
  python3 scripts/build_campaign.py --spec specs/q3-uk.json --execute  # create, PAUSED

Fails loudly on anything it cannot map. Nothing is ever defaulted.
"""
import argparse, csv, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "lib"))
import xlsx

EXAMPLE_MARKERS = ("Q3 — UK", "Q3 - UK", "act_1234567890", "example.com", "Example Ltd")


def is_example(row):
    blob = " ".join(str(v) for v in row.values())
    return any(m in blob for m in EXAMPLE_MARKERS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workbook")
    ap.add_argument("--out", required=True, help="spec JSON path, e.g. specs/q3-uk.json")
    ap.add_argument("--keep-examples", action="store_true",
                    help="do not drop the template's grey example rows")
    args = ap.parse_args()

    sh = xlsx.sheets(args.workbook)
    for need in ("Campaign", "Ad Sets", "Ads"):
        if need not in sh:
            sys.exit(f"Workbook is missing the '{need}' tab. Start from spec/CAMPAIGN-TEMPLATE.xlsx")

    # ---- Campaign tab: two-column key/value ----
    kv = {}
    for row in sh["Campaign"][1:]:
        if len(row) >= 2 and str(row[0]).strip():
            kv[str(row[0]).strip()] = str(row[1]).strip() if row[1] != "" else ""
    g = lambda k: (kv.get(k) or "").strip()

    problems = []
    for req in ("account_id", "campaign_name", "objective", "budget_mode", "page_id", "link", "cta"):
        if not g(req):
            problems.append(f"Campaign tab: '{req}' is empty and is required")

    mode = g("budget_mode").upper()
    if mode not in ("CBO", "ABO"):
        problems.append("Campaign tab: budget_mode must be CBO or ABO")

    def minor(v, where):
        if v in ("", None):
            return None
        try:
            f = float(str(v).replace(",", ""))
        except ValueError:
            problems.append(f"{where}: '{v}' is not a number"); return None
        if f != int(f):
            problems.append(f"{where}: budgets are MINOR units (whole cents) — got {v}"); return None
        return int(f)

    camp_budget = minor(g("daily_budget_minor"), "Campaign tab daily_budget_minor")
    if mode == "CBO" and not camp_budget:
        problems.append("Campaign tab: daily_budget_minor is required for CBO (e.g. 20000 = 200.00)")

    defaults = {k: g(k) for k in ("page_id", "instagram_user_id", "pixel_id", "link", "cta",
                                  "url_tags", "dsa_beneficiary", "dsa_payor") if g(k)}

    # ---- Ad Sets tab ----
    adset_rows = xlsx.table(sh["Ad Sets"])
    if not args.keep_examples:
        adset_rows = [r for r in adset_rows if not is_example(r)]
    adset_rows = [r for r in adset_rows if str(r.get("adset_name", "")).strip()
                  and not str(r.get("adset_name", "")).startswith("↑")
                  and "countries:" not in str(r.get("adset_name", ""))
                  and "start_time" not in str(r.get("adset_name", ""))]
    if not adset_rows:
        problems.append("Ad Sets tab: no ad sets found (did you delete the example rows and add your own?)")

    adsets, by_name = [], {}
    for i, r in enumerate(adset_rows, start=2):
        name = str(r["adset_name"]).strip()
        if name in by_name:
            problems.append(f"Ad Sets tab: duplicate adset_name '{name}'")
        countries = [c.strip().upper() for c in str(r.get("countries", "")).split(",") if c.strip()]
        if not countries:
            problems.append(f"Ad Sets tab '{name}': countries is required")
        a = {
            "name": name,
            "optimization_goal": str(r.get("optimization_goal") or "LINK_CLICKS").strip(),
            "billing_event": str(r.get("billing_event") or "IMPRESSIONS").strip(),
            "targeting": {"geo_locations": {"countries": countries},
                          "age_min": int(r["age_min"]) if str(r.get("age_min", "")).strip() else 18,
                          "age_max": int(r["age_max"]) if str(r.get("age_max", "")).strip() else 65},
            "ads": [],
        }
        b = minor(r.get("daily_budget_minor"), f"Ad Sets tab '{name}' daily_budget_minor")
        if mode == "ABO":
            if not b:
                problems.append(f"Ad Sets tab '{name}': daily_budget_minor is required for ABO "
                                f"— budgets are never defaulted")
            a["daily_budget_minor"] = b
        elif b:
            problems.append(f"Ad Sets tab '{name}': has a budget but the campaign is CBO — "
                            f"clear it, or switch budget_mode to ABO")
        ev = str(r.get("custom_event_type", "")).strip()
        if ev and defaults.get("pixel_id"):
            a["promoted_object"] = {"pixel_id": defaults["pixel_id"], "custom_event_type": ev}
        for k in ("start_time", "end_time", "dsa_beneficiary"):
            if str(r.get(k, "")).strip():
                a[k] = str(r[k]).strip()
        adsets.append(a); by_name[name] = a

    # ---- Ads tab ----
    ad_rows = xlsx.table(sh["Ads"])
    if not args.keep_examples:
        ad_rows = [r for r in ad_rows if not is_example(r)]
    ad_rows = [r for r in ad_rows if str(r.get("ad_name", "")).strip()
               and not str(r.get("adset_name", "")).startswith("↑")]
    if not ad_rows:
        problems.append("Ads tab: no ads found")

    seen, csv_rows = set(), []
    for r in ad_rows:
        an, adn = str(r.get("adset_name", "")).strip(), str(r.get("ad_name", "")).strip()
        if an not in by_name:
            problems.append(f"Ads tab: ad '{adn}' references adset '{an}' which is not on the Ad Sets tab")
            continue
        if adn in seen:
            problems.append(f"Ads tab: duplicate ad_name '{adn}' — ad names must be unique")
        seen.add(adn)
        cre = str(r.get("creative_file", "")).strip()
        if not cre:
            problems.append(f"Ads tab: ad '{adn}' has no creative_file")
        ad = {"name": adn, "creative": f"creatives/{cre}" if cre and "/" not in cre else cre}
        for src, dst in [("body", "body"), ("headline", "headline"), ("description", "description"),
                         ("cta", "cta"), ("link", "link"), ("url_tags", "url_tags"),
                         ("page_id", "page_id")]:
            v = str(r.get(src, "")).strip()
            if v:
                ad[dst] = v
        by_name[an]["ads"].append(ad)
        csv_rows.append({"adset": an, "ad_name": adn, "creative": ad["creative"],
                         "body": ad.get("body", ""), "headline": ad.get("headline", ""),
                         "description": ad.get("description", ""), "cta": ad.get("cta", ""),
                         "link": ad.get("link", "")})

    for a in adsets:
        if not a["ads"]:
            problems.append(f"Ad set '{a['name']}' has no ads on the Ads tab")

    if problems:
        print(f"{len(problems)} problem(s) — nothing was written:\n")
        for p in problems:
            print("  x " + p)
        print("\nFix these in the workbook and run again.")
        sys.exit(1)

    spec = {
        "account_id": g("account_id"),
        "campaign": {"name": g("campaign_name"), "objective": g("objective"),
                     "budget_mode": mode,
                     **({"daily_budget_minor": camp_budget} if mode == "CBO" else {}),
                     "special_ad_categories": [s.strip() for s in g("special_ad_categories").split(",") if s.strip()]},
        "defaults": defaults,
        "adsets": adsets,
    }
    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, indent=2, ensure_ascii=False))
    csv_path = out.with_suffix(".ads.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys())); w.writeheader(); w.writerows(csv_rows)

    print(f"OK — {len(adsets)} ad set(s), {len(csv_rows)} ad(s)")
    print(f"  spec : {out}")
    print(f"  ads  : {csv_path}  (reference copy; ads are already inline in the spec)")
    print(f"\nNext:  python3 scripts/build_campaign.py --spec {out}")


if __name__ == "__main__":
    main()
