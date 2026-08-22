#!/usr/bin/env python3
"""Export a live campaign into a workbook you can edit and re-upload.

Nobody should start a campaign from a blank sheet. Copy the closest thing that
already works, change what differs, upload it as a new campaign.

  python3 scripts/export_campaign.py 120250... --out ~/Desktop/NEW.xlsx
  python3 scripts/export_campaign.py 120250... --out NEW.xlsx --settings-only

Creatives come out as Meta image hashes, so the re-upload needs no image files
at all unless you are swapping in new ones.

--settings-only keeps the campaign, ad sets and targeting but drops the ads,
for when the structure is right but every ad is new.
"""
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "lib"))
import meta

ROOT = meta.load_env()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("campaign")
    ap.add_argument("--out", required=True)
    ap.add_argument("--settings-only", action="store_true",
                    help="keep targeting and structure, drop the ads")
    ap.add_argument("--template", default=str(ROOT / "spec" / "CAMPAIGN-TEMPLATE.xlsx"))
    args = ap.parse_args()

    sys.path.insert(0, str(ROOT / "scripts"))
    from fill_template import _openpyxl
    load_workbook, Font = _openpyxl()

    camp = meta.get(args.campaign, "name,objective,status,daily_budget,lifetime_budget,"
                                   "account_id,special_ad_categories")
    acct = meta.account(camp.get("account_id"))
    cbo = bool(camp.get("daily_budget") or camp.get("lifetime_budget"))
    locales = {v: k for k, v in (meta.load_locales() or {}).items()}

    wb = load_workbook(args.template)
    blue = Font(name="Arial", size=10, color="0000FF")
    put = lambda ws, r, c, v: (ws.cell(row=r, column=c, value=v).__setattr__("font", blue)
                               if v not in (None, "") else None)

    c = wb["Campaign"]
    for row in range(2, 27):
        c.cell(row=row, column=2).value = None
    put(c, 2, 2, acct)
    put(c, 3, 2, f"{camp.get('name')} (copy)")
    put(c, 4, 2, camp.get("objective"))
    put(c, 6, 2, "CBO" if cbo else "ABO")
    if camp.get("daily_budget"):
        put(c, 7, 2, int(camp["daily_budget"]))
    if camp.get("lifetime_budget"):
        put(c, 8, 2, int(camp["lifetime_budget"]))

    a, ads_ws = wb["Ad Sets"], wb["Ads"]
    for row in range(2, 40):
        for col in range(1, 30):
            a.cell(row=row, column=col).value = None
    for row in range(2, 400):
        for col in range(1, 13):
            ads_ws.cell(row=row, column=col).value = None

    page_seen = link_seen = cta_seen = None
    ar = dr = 2
    n_ads = 0
    for aset in meta.get_all(f"{args.campaign}/adsets",
            "id,name,daily_budget,optimization_goal,billing_event,targeting,"
            "promoted_object,dsa_beneficiary", cap=200):
        t = aset.get("targeting") or {}
        geo = t.get("geo_locations") or {}
        countries = list(geo.get("countries") or [])
        if geo.get("country_groups"):
            countries = ["worldwide"] + countries
        put(a, ar, 1, aset.get("name"))
        if not cbo and aset.get("daily_budget"):
            put(a, ar, 2, int(aset["daily_budget"]))
        put(a, ar, 4, aset.get("optimization_goal"))
        put(a, ar, 5, aset.get("billing_event"))
        put(a, ar, 8, ",".join(countries))
        excl = ((t.get("excluded_geo_locations") or {}).get("countries") or [])
        if excl:
            put(a, ar, 9, ",".join(excl))
        names = [locales.get(x) for x in (t.get("locales") or []) if locales.get(x)]
        if names:
            put(a, ar, 13, ",".join(names))
        g = t.get("genders") or []
        put(a, ar, 14, "Men" if g == [1] else "Women" if g == [2] else "All")
        put(a, ar, 15, t.get("age_min")); put(a, ar, 16, t.get("age_max"))
        if t.get("publisher_platforms"):
            put(a, ar, 23, ",".join(t["publisher_platforms"]))
        if (aset.get("promoted_object") or {}).get("custom_event_type"):
            put(a, ar, 26, aset["promoted_object"]["custom_event_type"])
        if aset.get("dsa_beneficiary"):
            put(a, ar, 29, aset["dsa_beneficiary"])
        ar += 1

        for ad in meta.get_all(f"{aset['id']}/ads",
                "name,creative{object_story_spec,asset_feed_spec}", cap=500):
            cr = ad.get("creative") or {}
            oss = cr.get("object_story_spec") or {}
            ld = oss.get("link_data") or oss.get("video_data") or {}
            feed = cr.get("asset_feed_spec") or {}
            cta = (ld.get("call_to_action") or {})
            page_seen = page_seen or oss.get("page_id")
            link_seen = link_seen or ld.get("link") or (cta.get("value") or {}).get("link")
            cta_seen = cta_seen or cta.get("type")
            if args.settings_only:
                continue
            bodies = [b["text"] for b in feed.get("bodies", [])] or \
                     ([ld.get("message")] if ld.get("message") else [])
            titles = [x["text"] for x in feed.get("titles", [])] or \
                     ([ld.get("name") or ld.get("title")] if
                      (ld.get("name") or ld.get("title")) else [])
            put(ads_ws, dr, 1, aset.get("name"))
            put(ads_ws, dr, 2, ad.get("name"))
            put(ads_ws, dr, 3, ld.get("image_hash") or "")
            put(ads_ws, dr, 4, " | ".join(x for x in bodies if x))
            put(ads_ws, dr, 5, " | ".join(x for x in titles if x))
            put(ads_ws, dr, 6, ld.get("description") or "")
            put(ads_ws, dr, 7, cta.get("type")); put(ads_ws, dr, 8,
                ld.get("link") or (cta.get("value") or {}).get("link"))
            dr += 1; n_ads += 1

    put(c, 17, 2, page_seen); put(c, 21, 2, link_seen); put(c, 23, 2, cta_seen)

    try:
        sys.path.insert(0, str(ROOT / "api" / "_lib"))
        from aitab import add_ai_tab
        add_ai_tab(wb, scope="campaign", context={
            "account_id": acct,
            "this sheet is": "a copy of a live campaign. Uploading it creates a NEW "
                             "campaign; it does not edit the original.",
            "creative_file": "image hashes from this account — leave them and no image "
                             "files are needed" if not args.settings_only else
                             "EMPTY on purpose — the ads still need to be written",
            "page_id": page_seen or "ASK"})
    except Exception:
        pass

    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    print(f"Wrote {out}")
    print(f"  copied from : {camp.get('name')}")
    print(f"  {ar-2} ad set(s), {n_ads} ad(s)"
          + ("   (settings only — ads left blank)" if args.settings_only else ""))
    print(f"  RENAME the campaign on the Campaign tab before uploading — "
          f"it is currently '{camp.get('name')} (copy)'.")


if __name__ == "__main__":
    main()
