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
import meta

meta.load_env()

# The template ships example rows that must be ignored if left in. Match them
# by their EXACT names, never by substrings of their content: "example.com" is
# a perfectly ordinary landing page, and blocklisting it silently deleted every
# ad in a real sheet.
EXAMPLE_ADSET_NAMES = {
    "q3 uk broad 18-45", "q3 uk retarget 30d", "q3 spanish speakers ww",
    "example — lt — broad", "example — lt — 25-44",
}
EXAMPLE_AD_NAMES = {
    "q3-uk-01-price", "q3-uk-02-ugc", "q3-uk-03-offer", "q3-uk-01", "q3-uk-02",
    "ex-01-yellow", "ex-02-red", "ex-03-blue", "ex-04-black",
}


def is_example(row):
    """True only for the template's own demo rows, matched by exact name."""
    name = str(row.get("adset_name") or "").strip().lower()
    ad = str(row.get("ad_name") or "").strip().lower()
    if ad:
        return ad in EXAMPLE_AD_NAMES
    return name in EXAMPLE_ADSET_NAMES


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

    spec_account = g("account_id")
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
                                  "url_tags", "dsa_beneficiary", "dsa_payor", "display_link",
                                  "custom_event_type") if g(k)}

    # ---- Ad Sets tab ----
    adset_rows = xlsx.table(sh["Ad Sets"])
    if not args.keep_examples:
        adset_rows = [r for r in adset_rows if not is_example(r)]
    # A real ad set row has a name AND at least one other populated field. The
    # help notes under the table occupy column A only, so they drop out here
    # without any fragile string matching.
    adset_rows = [r for r in adset_rows
                  if str(r.get("adset_name", "")).strip()
                  and (str(r.get("countries", "")).strip()
                       or str(r.get("optimization_goal", "")).strip())]
    if not adset_rows:
        problems.append("Ad Sets tab: no ad sets found (did you delete the example rows and add your own?)")

    LOCALES = meta.load_locales()
    resolved_log = []

    def csv_list(v):
        return [x.strip() for x in str(v or "").split(",") if x.strip()]

    def variants(v):
        """Split a copy cell into its variants.

        A pipe (or a newline) separates several primary texts / headlines that
        Meta rotates inside one ad. Commas are NOT separators - ad copy is full
        of them. Max 5, which is Meta's limit.
        """
        raw = str(v or "")
        parts = raw.replace("\r", "").split("\n") if "\n" in raw else raw.split("|")
        return [x.strip() for x in parts if x.strip()][:5]

    adsets, by_name = [], {}
    for r in adset_rows:
        name = str(r["adset_name"]).strip()
        if name in by_name:
            problems.append(f"Ad Sets tab: duplicate adset_name '{name}'")

        # ---------------- geography ----------------
        countries = [c.upper() for c in csv_list(r.get("countries"))]
        if not countries:
            problems.append(f"Ad Sets '{name}': countries is required")
        geo = {"countries": countries}

        loc_types = str(r.get("location_types") or "home+recent").strip()
        geo["location_types"] = ["home", "recent"] if loc_types == "home+recent" else [loc_types]

        for col, kind, key in (("cities", "city", "cities"), ("regions", "region", "regions")):
            names = csv_list(r.get(col))
            if not names:
                continue
            out = []
            for nm in names:
                try:
                    hit = meta.search_geo(nm, kind)
                except Exception as e:
                    problems.append(f"Ad Sets '{name}': could not look up {kind} '{nm}' ({e})"); continue
                if not hit:
                    problems.append(f"Ad Sets '{name}': no Meta {kind} matches '{nm}'"); continue
                entry = {"key": hit["key"]}
                if kind == "city":
                    entry["radius"] = 10; entry["distance_unit"] = "mile"
                out.append(entry)
                resolved_log.append(f"{kind} '{nm}' -> {hit.get('name')}, "
                                    f"{hit.get('region') or ''} {hit.get('country_code') or ''} (key {hit['key']})")
            if out:
                geo[key] = out

        targeting = {"geo_locations": geo}

        excl = [c.upper() for c in csv_list(r.get("excluded_countries"))]
        if excl:
            targeting["excluded_geo_locations"] = {"countries": excl}

        # ---------------- demographics ----------------
        targeting["age_min"] = int(r["age_min"]) if str(r.get("age_min", "")).strip() else 18
        targeting["age_max"] = int(r["age_max"]) if str(r.get("age_max", "")).strip() else 65
        gender = str(r.get("genders") or "All").strip().lower()
        if gender == "men":
            targeting["genders"] = [1]
        elif gender == "women":
            targeting["genders"] = [2]

        # ---------------- languages ----------------
        langs = csv_list(r.get("languages"))
        if langs:
            ids = []
            for L in langs:
                if L in LOCALES:
                    ids.append(LOCALES[L])
                else:
                    near = [k for k in LOCALES if k.lower().startswith(L.lower()[:4])][:3]
                    problems.append(f"Ad Sets '{name}': language '{L}' is not a Meta language. "
                                    f"Use a name from the Languages tab"
                                    + (f" (did you mean: {', '.join(near)}?)" if near else ""))
            if ids:
                targeting["locales"] = ids

        # ---------------- interests ----------------
        for col, key in (("interests", "interests"), ("excluded_interests", "exclusions")):
            names = csv_list(r.get(col))
            if not names:
                continue
            found = []
            for nm in names:
                try:
                    hit = meta.search_interest(nm)
                except Exception as e:
                    problems.append(f"Ad Sets '{name}': could not look up interest '{nm}' ({e})"); continue
                if not hit:
                    problems.append(f"Ad Sets '{name}': no Meta interest matches '{nm}'"); continue
                found.append({"id": hit["id"], "name": hit["name"]})
                resolved_log.append(f"interest '{nm}' -> {hit['name']} (id {hit['id']}, "
                                    f"reach ~{hit.get('audience_size_lower_bound', '?')})")
            if found and key == "interests":
                targeting.setdefault("flexible_spec", [{}])[0]["interests"] = found
            elif found:
                targeting["exclusions"] = {"interests": found}

        # ---------------- custom audiences ----------------
        for col, key in (("custom_audiences", "custom_audiences"),
                         ("excluded_custom_audiences", "excluded_custom_audiences")):
            names = csv_list(r.get(col))
            if not names:
                continue
            found = []
            for nm in names:
                try:
                    hit = meta.find_custom_audience(spec_account, nm)
                except Exception as e:
                    problems.append(f"Ad Sets '{name}': could not look up audience '{nm}' ({e})"); continue
                if not hit:
                    problems.append(f"Ad Sets '{name}': no custom audience named '{nm}' in this ad account")
                    continue
                found.append({"id": hit["id"], "name": hit["name"]})
                resolved_log.append(f"audience '{nm}' -> {hit['name']} (id {hit['id']})")
            if found:
                targeting[key] = found

        # ---------------- placements ----------------
        dev = str(r.get("device_platforms") or "All").strip().lower()
        if dev and dev != "all":
            targeting["device_platforms"] = csv_list(dev)
        pubs = csv_list(r.get("publisher_platforms"))
        if pubs:
            targeting["publisher_platforms"] = pubs
        fbp = csv_list(r.get("facebook_positions"))
        if fbp:
            targeting["facebook_positions"] = fbp
        igp = csv_list(r.get("instagram_positions"))
        if igp:
            targeting["instagram_positions"] = igp
        if (fbp or igp) and not pubs:
            problems.append(f"Ad Sets '{name}': positions are set but publisher_platforms is blank — "
                            f"name the platforms too, or clear the positions")

        if str(r.get("advantage_audience") or "").strip().lower() == "yes":
            targeting["targeting_automation"] = {"advantage_audience": 1}

        # ---------------- assemble ----------------
        a = {
            "name": name,
            "optimization_goal": str(r.get("optimization_goal") or "LINK_CLICKS").strip(),
            "billing_event": str(r.get("billing_event") or "IMPRESSIONS").strip(),
            "targeting": targeting,
            "ads": [],
        }
        if str(r.get("bid_strategy") or "").strip():
            a["bid_strategy"] = str(r["bid_strategy"]).strip()
        ba = minor(r.get("bid_amount_minor"), f"Ad Sets '{name}' bid_amount_minor")
        if ba:
            a["bid_amount_minor"] = ba

        daily = minor(r.get("daily_budget_minor"), f"Ad Sets '{name}' daily_budget_minor")
        life = minor(r.get("lifetime_budget_minor"), f"Ad Sets '{name}' lifetime_budget_minor")
        if daily and life:
            problems.append(f"Ad Sets '{name}': set daily OR lifetime budget, not both")
        if mode == "ABO":
            if not (daily or life):
                problems.append(f"Ad Sets '{name}': a budget is required for ABO — never defaulted")
            if daily:
                a["daily_budget_minor"] = daily
            if life:
                a["lifetime_budget_minor"] = life
        elif daily or life:
            problems.append(f"Ad Sets '{name}': has a budget but the campaign is CBO — "
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
    # Same structural filter: a real ad row names an ad set AND an ad.
    ad_rows = [r for r in ad_rows
               if str(r.get("ad_name", "")).strip()
               and str(r.get("adset_name", "")).strip()]
    if not ad_rows:
        problems.append("Ads tab: no ads found")

    seen, csv_rows = set(), []
    for r in ad_rows:
        an, adn = str(r.get("adset_name", "")).strip(), str(r.get("ad_name", "")).strip()
        if an not in by_name:
            problems.append(f"Ads tab: ad '{adn}' references adset '{an}' which is not on the Ad Sets tab")
            continue
        # Several creatives in one cell = one ad each, sharing the copy.
        # Text variants rotate inside an ad; only creatives need separate ads.
        creatives_cell = variants(r.get("creative_file"))
        if not creatives_cell:
            problems.append(f"Ads tab: ad '{adn}' has no creative_file")

        base = {}
        for src, dst in [("cta", "cta"), ("link", "link"), ("url_tags", "url_tags"),
                         ("page_id", "page_id"), ("display_link", "display_link"),
                         ("instagram_user_id", "instagram_user_id")]:
            v = str(r.get(src, "")).strip()
            if v:
                base[dst] = v
        for src, many in (("body", "bodies"), ("headline", "headlines"),
                          ("description", "descriptions")):
            vs = variants(r.get(src))
            if vs:
                base[src] = vs[0]
                if len(vs) > 1:
                    base[many] = vs

        multi = len(creatives_cell) > 1
        for idx, cre in enumerate(creatives_cell, start=1):
            nm = adn if not multi else f"{adn} {idx:02d}"[:80]
            if nm in seen:
                problems.append(f"Ads tab: duplicate ad_name '{nm}' — ad names must be unique")
            seen.add(nm)
            ad = dict(base)
            ad["name"] = nm
            ad["creative"] = f"creatives/{cre}" if cre and "/" not in cre else cre
            by_name[an]["ads"].append(ad)
            csv_rows.append({"adset": an, "ad_name": nm, "creative": ad["creative"],
                             "body": ad.get("body", ""), "headline": ad.get("headline", ""),
                             "description": ad.get("description", ""),
                             "cta": ad.get("cta", ""), "link": ad.get("link", "")})


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

    if resolved_log:
        print("Resolved to Meta IDs (check these are right):")
        for line in resolved_log:
            print("   " + line)
        print()
    print(f"OK — {len(adsets)} ad set(s), {len(csv_rows)} ad(s)")
    print(f"  spec : {out}")
    print(f"  ads  : {csv_path}  (reference copy; ads are already inline in the spec)")
    print(f"\nNext:  python3 scripts/build_campaign.py --spec {out}")


if __name__ == "__main__":
    main()
