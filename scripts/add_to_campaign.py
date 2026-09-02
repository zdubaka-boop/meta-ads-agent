#!/usr/bin/env python3
"""Add ads (or a whole ad set) to a campaign that ALREADY EXISTS.

build_campaign.py only creates fresh campaigns and refuses to touch one whose
name is already taken. This is the other half: browsing what exists, then
adding into it. Everything created here is PAUSED, same as everywhere else.

  # 1. what campaigns are in this account?
  python3 scripts/add_to_campaign.py --account act_123 --list

  # 2. what ad sets are in that campaign?
  python3 scripts/add_to_campaign.py --account act_123 --campaign 120250... --list

  # 3. add ads into one existing ad set (preview, then execute)
  python3 scripts/add_to_campaign.py --account act_123 --adset 120250... --ads new-ads.csv
  python3 scripts/add_to_campaign.py --account act_123 --adset 120250... --ads new-ads.csv --execute

  # 4. add a whole new ad set (with its ads) into an existing campaign
  python3 scripts/add_to_campaign.py --account act_123 --campaign 120250... \
         --new-adsets-from specs/extra.json --execute

Add --json to any command for machine-readable output (used by the web UI).

Ads whose name already exists in the target ad set are SKIPPED, so re-running
after a failure never duplicates.
"""
import argparse, csv, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "lib"))
import meta, xlsx

ROOT = meta.load_env()


# ───────────────────────────────────────────────────────────── browsing

def list_campaigns(acct):
    camps = meta.get_all(f"{meta.account(acct)}/campaigns",
        "id,name,objective,status,effective_status,daily_budget,lifetime_budget,created_time")
    for c in camps:
        c["budget_mode"] = "CBO" if (c.get("daily_budget") or c.get("lifetime_budget")) else "ABO"
    camps.sort(key=lambda c: c.get("created_time") or "", reverse=True)
    return camps


def list_adsets(campaign_id, with_counts=True):
    """Ad sets in a campaign.

    with_counts=False skips one /ads request PER ad set. Those requests
    paginate over every existing ad, so on a campaign holding 100+ ads they
    are the most expensive thing here — and the duplicate-name check below
    only ever wanted the names.
    """
    sets_ = meta.get_all(f"{campaign_id}/adsets",
        "id,name,status,effective_status,daily_budget,lifetime_budget,optimization_goal,targeting")
    for a in sets_:
        geo = (a.get("targeting") or {}).get("geo_locations", {}) or {}
        a["countries"] = geo.get("countries") or []
        a.pop("targeting", None)
        if with_counts:
            try:
                a["ad_count"] = len(meta.get_all(f"{a['id']}/ads", "id", cap=500))
            except Exception:
                a["ad_count"] = None
    return sets_


def existing_ad_names(adset_id):
    return {a.get("name") for a in meta.get_all(f"{adset_id}/ads", "id,name", cap=1000)}


# ───────────────────────────────────────────────────────────── ad input

def read_ads(path):
    """Read ads from a .csv or from the Ads tab of a .xlsx."""
    p = Path(path)
    if not p.exists():
        p = ROOT / path
    if not p.exists():
        sys.exit(f"Ads file not found: {path}")
    if p.suffix.lower() in (".xlsx", ".xlsm"):
        sheets = xlsx.sheets(p)
        if "Ads" not in sheets:
            sys.exit(f"{p.name} has no 'Ads' tab")
        rows = xlsx.table(sheets["Ads"])
    else:
        with open(p, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        r = {(k or "").strip(): (str(v).strip() if v is not None else "") for k, v in r.items() if k}
        name = r.get("ad_name") or r.get("name")
        if not name or not r.get("creative_file", r.get("creative", "")):
            continue
        def _var(v):
            raw = str(v or "")
            parts = raw.split("\n") if "\n" in raw else raw.split("|")
            return [x.strip() for x in parts if x.strip()][:5]
        b, h, dsc = _var(r.get("body")), _var(r.get("headline")), _var(r.get("description"))
        out.append({
            "name": name,
            "creative": r.get("creative_file") or r.get("creative"),
            "body": b[0] if b else "", "headline": h[0] if h else "",
            **({"bodies": b} if len(b) > 1 else {}),
            **({"headlines": h} if len(h) > 1 else {}),
            **({"descriptions": dsc} if len(dsc) > 1 else {}),
            "description": dsc[0] if dsc else "", "cta": r.get("cta", ""),
            "link": r.get("link", ""), "url_tags": r.get("url_tags", ""),
            "page_id": r.get("page_id", ""), "instagram_user_id": r.get("instagram_user_id", ""),
        })
    return out


def resolve_creative_path(name):
    if meta.is_remote_url(name):
        return name
    for cand in (Path(name), ROOT / name, ROOT / "creatives" / name):
        if cand.exists():
            return cand
    return None


# ───────────────────────────────────────────────────────────── adding

def add_ads(acct, adset_id, ads, execute, defaults, lanes=4):
    aset = meta.get(adset_id, "id,name,status,campaign{id,name}")
    camp = aset.get("campaign") or {}
    already = existing_ad_names(adset_id)

    fresh, skipped, problems = [], [], []
    for ad in ads:
        if ad["name"] in already:
            skipped.append(ad["name"]); continue
        if not resolve_creative_path(ad["creative"]):
            problems.append(f"{ad['name']}: creative not found: {ad['creative']}")
        if not (ad.get("link") or defaults.get("link")):
            problems.append(f"{ad['name']}: no link, and no META_LINK default — never inferred")
        if not (ad.get("page_id") or defaults.get("page_id")):
            problems.append(f"{ad['name']}: no page_id, and no META_PAGE_ID default — never inferred")
        fresh.append(ad)

    print("=" * 72)
    print(f"ADD ADS  ->  ad set  {aset.get('name')}  ({adset_id})")
    print(f"          campaign  {camp.get('name')}  ({camp.get('id')})")
    print(f"          ad set currently has {len(already)} ad(s), status {aset.get('status')}")
    print("=" * 72)
    for ad in fresh:
        print(f"  + {ad['name']:<34} {meta.media_name(ad['creative'])}")
    for s in skipped:
        print(f"  = {s:<34} already exists, will be skipped")
    if problems:
        print(f"\n{len(problems)} problem(s) — nothing was created:")
        for p in problems:
            print("  x " + p)
        sys.exit(1)
    if not fresh:
        print("\nNothing new to add — every ad in the file already exists in this ad set.")
        return {"adset_id": adset_id, "created": [], "skipped": skipped}

    print(f"\n{len(fresh)} ad(s) would be created PAUSED in this existing ad set.")
    if not execute:
        print("DRY RUN — no API calls made. Re-run with --execute to create.")
        return {"adset_id": adset_id, "created": [], "skipped": skipped, "dry_run": True}

    slug = "".join(ch if ch.isalnum() else "-" for ch in aset.get("name", adset_id)).lower()[:40]
    state_path = ROOT / "outputs" / f"addto-{slug}-{adset_id}.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    state.setdefault("ads", {}); state.setdefault("media", {})

    # Put all missing media in the account before creating the first ad. Local
    # files use parallel lanes; public URLs are fetched by Meta's datacenter.
    wanted = [resolve_creative_path(ad["creative"]) for ad in fresh
              if ad["name"] not in state["ads"]]
    todo = [ref for ref in wanted if meta.media_key(ref) not in state["media"]]
    if todo:
        state["media"].update(meta.upload_many(acct, todo, lanes=lanes))
        state_path.write_text(json.dumps(state, indent=2))

    created = []
    for ad in fresh:
        if ad["name"] in state["ads"]:
            print(f"  = {ad['name']} already created in a previous run ({state['ads'][ad['name']]})")
            continue
        p = resolve_creative_path(ad["creative"])
        key = meta.media_key(p)
        is_video = meta.is_video_ref(p)
        if key not in state["media"]:
            if is_video:
                if meta.is_remote_url(p):
                    vid, thumb = meta.upload_video_url(acct, p, ad["name"])
                else:
                    vid, thumb = meta.upload_video(acct, p, ad["name"])
                state["media"][key] = {"video_id": vid, "thumb": thumb}
            else:
                state["media"][key] = {"hash": meta.upload_image(acct, p, ad["name"])}
            state_path.write_text(json.dumps(state, indent=2))
        m = state["media"][key]
        pick = lambda k, d=None: ad.get(k) or defaults.get(k) or d
        common = dict(link=pick("link"), body=ad.get("body", ""), headline=ad.get("headline", ""),
                      description=ad.get("description") or None, cta=pick("cta", "LEARN_MORE"),
                      ig_user_id=pick("instagram_user_id"), url_tags=pick("url_tags"),
                      bodies=ad.get("bodies"), headlines=ad.get("headlines"),
                      descriptions=ad.get("descriptions"))
        creative = (meta.video_creative(pick("page_id"), m["video_id"], m["thumb"], **common)
                    if is_video else meta.image_creative(pick("page_id"), m["hash"], **common))
        ad_id = meta.create_ad(acct, adset_id, ad["name"], creative, pixel_id=defaults.get("pixel_id"))
        state["ads"][ad["name"]] = ad_id
        state_path.write_text(json.dumps(state, indent=2))
        created.append({"name": ad["name"], "id": ad_id})
        print(f"  created  {ad_id}  {ad['name']}")

    print(f"\nDONE. {len(created)} ad(s) added PAUSED to '{aset.get('name')}'.")
    print(f"State: {state_path}")
    return {"adset_id": adset_id, "created": created, "skipped": skipped}


def add_adsets(acct, campaign_id, spec_path, execute, lanes=4):
    """Add new ad set(s) + their ads into an existing campaign."""
    spec = json.loads(Path(spec_path).read_text())
    camp = meta.get(campaign_id, "id,name,daily_budget,lifetime_budget,objective")
    cbo = bool(camp.get("daily_budget") or camp.get("lifetime_budget"))
    defaults = spec.get("defaults", {})
    existing = {a["name"]: a["id"] for a in list_adsets(campaign_id, with_counts=False)}

    print("=" * 72)
    print(f"ADD AD SETS  ->  campaign  {camp.get('name')}  ({campaign_id})")
    print(f"              campaign is {'CBO' if cbo else 'ABO'}, objective {camp.get('objective')}")
    print("=" * 72)

    problems = []
    todo = []
    for a in spec.get("adsets", []):
        resumes = a["name"] in existing
        if not resumes and cbo and a.get("daily_budget_minor"):
            problems.append(f"{a['name']}: campaign is CBO — remove the ad set budget")
        if not resumes and not cbo and not a.get("daily_budget_minor"):
            problems.append(f"{a['name']}: campaign is ABO — a budget is required, never defaulted")
        todo.append(a)
        marker = "=" if resumes else "+"
        suffix = "resume existing set; add only missing ads" if resumes else "new ad set"
        print(f"  {marker} {a['name']:<34} {len(a.get('ads', []))} ad(s)  ({suffix})")
    if problems:
        print(f"\n{len(problems)} problem(s) — nothing created:")
        for p in problems:
            print("  x " + p)
        sys.exit(1)
    if not todo:
        print("\nNothing new to add.")
        return {"campaign_id": campaign_id, "created": []}
    if not execute:
        print("\nDRY RUN — no API calls made. Re-run with --execute.")
        return {"campaign_id": campaign_id, "created": [], "dry_run": True}

    out = []
    for a in todo:
        aid = existing.get(a["name"])
        if aid:
            print(f"  resuming ad set  {aid}  {a['name']}")
        else:
            aid = meta.create_adset(
                acct, campaign_id, a["name"], a["targeting"],
                budget_minor=a.get("daily_budget_minor"),
                lifetime_budget_minor=a.get("lifetime_budget_minor"),
                optimization_goal=a.get("optimization_goal", "LINK_CLICKS"),
                billing_event=a.get("billing_event", "IMPRESSIONS"),
                promoted_object=a.get("promoted_object"),
                dsa_beneficiary=a.get("dsa_beneficiary") or defaults.get("dsa_beneficiary"),
                dsa_payor=a.get("dsa_payor") or defaults.get("dsa_payor"),
                start_time=a.get("start_time"), end_time=a.get("end_time"))
            print(f"  created ad set  {aid}  {a['name']}")
        res = add_ads(acct, aid, a.get("ads", []), True, defaults, lanes=lanes)
        out.append({"adset": a["name"], "adset_id": aid, "ads": res["created"]})
    return {"campaign_id": campaign_id, "created": out}


# ───────────────────────────────────────────────────────────── cli

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True)
    ap.add_argument("--campaign")
    ap.add_argument("--adset")
    ap.add_argument("--ads", help="CSV or .xlsx of ads to add")
    ap.add_argument("--new-adsets-from", help="spec JSON containing adsets[] to add")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--lanes", type=int, default=4,
                    help="local creatives uploaded at once (default 4)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    acct = meta.account(args.account)

    if args.list and not args.campaign:
        camps = list_campaigns(acct)
        if args.json:
            print(json.dumps(camps, indent=2)); return
        print(f"CAMPAIGNS IN {acct} ({len(camps)})\n")
        for c in camps:
            print(f"  {c['id']:<20} {(c.get('name') or '')[:38]:<38} {c.get('objective',''):<18} "
                  f"{c.get('effective_status',''):<18} {c['budget_mode']}")
        print("\nNext:  --campaign <id> --list     to see its ad sets")
        return

    if args.list and args.campaign:
        sets_ = list_adsets(args.campaign)
        if args.json:
            print(json.dumps(sets_, indent=2)); return
        camp = meta.get(args.campaign, "name")
        print(f"AD SETS IN '{camp.get('name')}' ({len(sets_)})\n")
        for a in sets_:
            budget = a.get("daily_budget") or a.get("lifetime_budget") or "campaign-level"
            print(f"  {a['id']:<20} {(a.get('name') or '')[:34]:<34} {a.get('effective_status',''):<18} "
                  f"{str(a.get('ad_count')):>3} ad(s)  budget={budget}  {','.join(a.get('countries') or [])}")
        print("\nNext:  --adset <id> --ads <file.csv|.xlsx>     to add ads into one")
        return

    import os
    defaults = {k: v for k, v in (
        ("page_id", os.getenv("META_PAGE_ID")), ("link", os.getenv("META_LINK")),
        ("pixel_id", os.getenv("META_PIXEL_ID")),
        ("instagram_user_id", os.getenv("META_IG_USER_ID")),
        ("cta", os.getenv("META_CTA")), ("url_tags", os.getenv("META_URL_TAGS"))) if v}

    if args.adset and args.ads:
        res = add_ads(acct, args.adset, read_ads(args.ads), args.execute, defaults,
                      lanes=args.lanes)
        if args.json:
            print(json.dumps(res, indent=2))
        return
    if args.campaign and args.new_adsets_from:
        res = add_adsets(acct, args.campaign, args.new_adsets_from, args.execute,
                         lanes=args.lanes)
        if args.json:
            print(json.dumps(res, indent=2))
        return
    ap.error("nothing to do — use --list, or --adset with --ads, or --campaign with --new-adsets-from")


if __name__ == "__main__":
    main()
