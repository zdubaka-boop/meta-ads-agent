#!/usr/bin/env python3
"""Build a campaign from a spec file. Everything is created PAUSED.

  # 1. validate + preview (this is the DEFAULT — no API writes)
  python3 scripts/build_campaign.py --spec spec/examples/example-campaign.json

  # 2. actually create, after a human has read the preview
  python3 scripts/build_campaign.py --spec ... --execute

Bulk ads live in a CSV referenced by the spec, or passed with --ads.
Re-running with --execute RESUMES from the state file; it never duplicates
objects that already exist.
"""
import argparse, csv, json, sys, hashlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "lib"))
import meta

ROOT = meta.load_env()


def load_spec(p):
    p = Path(p)
    text = p.read_text()
    if p.suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError:
            sys.exit("PyYAML not installed. Use a .json spec, or: pip3 install pyyaml")
        return yaml.safe_load(text)
    return json.loads(text)


def merge_csv(spec, csv_path):
    """Fold a bulk ads CSV into the spec's ad sets, matching on adset name."""
    by_name = {a["name"]: a for a in spec["adsets"]}
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for i, row in enumerate(csv.DictReader(f), start=2):
            row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
            target = row.get("adset")
            if target not in by_name:
                sys.exit(f"{csv_path}:{i} — adset '{target}' is not defined in the spec")
            ad = {k: row[k] for k in ("ad_name", "creative", "body", "headline",
                                      "description", "cta", "link") if row.get(k)}
            ad["name"] = ad.pop("ad_name", None)
            by_name[target].setdefault("ads", []).append(ad)


def validate(spec):
    """Collect every problem before touching the API. No value is ever guessed."""
    errs, warns = [], []
    d = spec.get("defaults", {})
    c = spec.get("campaign", {})

    if not spec.get("account_id"):        errs.append("account_id is required")
    if not c.get("name"):                 errs.append("campaign.name is required")
    if not c.get("objective"):            errs.append("campaign.objective is required")

    mode = (c.get("budget_mode") or "").upper()
    if mode not in ("CBO", "ABO"):
        errs.append("campaign.budget_mode must be 'CBO' or 'ABO'")
    if mode == "CBO" and not c.get("daily_budget_minor"):
        errs.append("campaign.daily_budget_minor is required for CBO (minor units, e.g. 5000 = 50.00)")
    if mode == "CBO" and any(a.get("daily_budget_minor") for a in spec.get("adsets", [])):
        errs.append("CBO campaign: ad sets must not carry daily_budget_minor")

    if not spec.get("adsets"):
        errs.append("at least one adset is required")

    seen_adsets, seen_ads = set(), set()
    for i, a in enumerate(spec.get("adsets", [])):
        tag = f"adsets[{i}]"
        if not a.get("name"):
            errs.append(f"{tag}.name is required")
        elif a["name"] in seen_adsets:
            errs.append(f"{tag}.name '{a['name']}' is duplicated")
        else:
            seen_adsets.add(a["name"])
        if mode == "ABO" and not a.get("daily_budget_minor"):
            errs.append(f"{tag}.daily_budget_minor is required for ABO — budgets are never defaulted")
        if not (a.get("targeting") or {}).get("geo_locations"):
            errs.append(f"{tag}.targeting.geo_locations is required")
        if not a.get("ads"):
            errs.append(f"{tag} has no ads")

        geo = ((a.get("targeting") or {}).get("geo_locations") or {})
        eu = {"AT","BE","BG","HR","CY","CZ","DK","EE","FI","FR","DE","GR","HU","IE","IT",
              "LV","LT","LU","MT","NL","PL","PT","RO","SK","SI","ES","SE"}
        if set(geo.get("countries") or []) & eu and not (a.get("dsa_beneficiary") or d.get("dsa_beneficiary")):
            errs.append(f"{tag}: dsa_beneficiary is required when targeting the EU "
                        f"(names the advertiser; Meta rejects the ad set without it)")

        for j, ad in enumerate(a.get("ads", [])):
            atag = f"{tag}.ads[{j}]"
            if not ad.get("name"):
                errs.append(f"{atag}.name is required")
            elif ad["name"] in seen_ads:
                errs.append(f"{atag}.name '{ad['name']}' is duplicated — ad names must be unique")
            else:
                seen_ads.add(ad["name"])
            if not (ad.get("link") or d.get("link")):
                errs.append(f"{atag}.link is required (no destination is ever inferred)")
            if not (ad.get("page_id") or d.get("page_id")):
                errs.append(f"{atag}: page_id is required (no identity is ever inferred)")
            cre = ad.get("creative")
            if not cre:
                errs.append(f"{atag}.creative (file path) is required")
            elif not (ROOT / cre).exists() and not Path(cre).exists():
                errs.append(f"{atag}.creative file not found: {cre}")
            if not ad.get("body"):    warns.append(f"{atag} has no body text")
            if not ad.get("headline"): warns.append(f"{atag} has no headline")
    return errs, warns


def resolve(ad, defaults, key, fallback=None):
    return ad.get(key) or defaults.get(key) or fallback


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--ads", help="bulk ads CSV (overrides spec.ads_csv)")
    ap.add_argument("--execute", action="store_true",
                    help="perform API writes. Without this, nothing is created.")
    ap.add_argument("--state", help="state file path (default outputs/<campaign>-state.json)")
    args = ap.parse_args()

    spec = load_spec(args.spec)
    csv_path = args.ads or spec.get("ads_csv")
    if csv_path:
        p = Path(csv_path)
        merge_csv(spec, p if p.exists() else ROOT / csv_path)

    errs, warns = validate(spec)
    c, d = spec["campaign"], spec.get("defaults", {})
    n_adsets = len(spec.get("adsets", []))
    n_ads = sum(len(a.get("ads", [])) for a in spec.get("adsets", []))

    print("=" * 72)
    print(f"CAMPAIGN   {c.get('name')}")
    print(f"  account  {spec.get('account_id')}")
    print(f"  objective {c.get('objective')}   budget_mode {c.get('budget_mode')}")
    if (c.get("budget_mode") or "").upper() == "CBO":
        print(f"  campaign daily budget: {c.get('daily_budget_minor')} (minor units)")
    print(f"  {n_adsets} ad set(s), {n_ads} ad(s) — ALL WILL BE CREATED PAUSED")
    print("=" * 72)
    for a in spec.get("adsets", []):
        b = a.get("daily_budget_minor")
        print(f"\n  AD SET  {a.get('name')}   budget={b if b else '(campaign-level)'}")
        print(f"          geo={((a.get('targeting') or {}).get('geo_locations') or {}).get('countries')}"
              f"  opt={a.get('optimization_goal', 'LINK_CLICKS')}")
        for ad in a.get("ads", [])[:6]:
            print(f"            - {ad.get('name'):<34} {Path(str(ad.get('creative',''))).name}")
        if len(a.get("ads", [])) > 6:
            print(f"            ... and {len(a['ads']) - 6} more")

    if warns:
        print("\nWARNINGS")
        for w in warns[:30]:
            print("  ! " + w)
    if errs:
        print(f"\n{len(errs)} ERROR(S) — nothing was created:")
        for e in errs[:40]:
            print("  x " + e)
        sys.exit(1)

    print("\nValidation passed.")
    if not args.execute:
        print("DRY RUN — no API calls were made. Re-run with --execute to create.")
        return

    # ---------------------------------------------------------------- execute
    acct = spec["account_id"]
    slug = "".join(ch if ch.isalnum() else "-" for ch in c["name"]).strip("-").lower()
    state_path = Path(args.state) if args.state else ROOT / "outputs" / f"{slug}-state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    state.setdefault("adsets", {}); state.setdefault("ads", {}); state.setdefault("media", {})

    def save():
        state_path.write_text(json.dumps(state, indent=2))

    # Duplicate guard: refuse if a same-named campaign exists and we have no state.
    if "campaign_id" not in state:
        existing = [x for x in meta.get_all(f"{meta.account(acct)}/campaigns", "id,name")
                    if x.get("name") == c["name"]]
        if existing:
            sys.exit(f"ABORT: a campaign named '{c['name']}' already exists "
                     f"({', '.join(x['id'] for x in existing)}). Rename, or pass --state "
                     f"pointing at the run that created it.")
        state["campaign_id"] = meta.create_campaign(
            acct, c["name"], c["objective"],
            budget_minor=c.get("daily_budget_minor") if (c.get("budget_mode") or "").upper() == "CBO" else None,
            special_ad_categories=c.get("special_ad_categories"))
        save()
    print(f"\ncampaign  {state['campaign_id']}")

    for a in spec["adsets"]:
        if a["name"] not in state["adsets"]:
            state["adsets"][a["name"]] = meta.create_adset(
                acct, state["campaign_id"], a["name"], a["targeting"],
                budget_minor=a.get("daily_budget_minor"),
                optimization_goal=a.get("optimization_goal", "LINK_CLICKS"),
                billing_event=a.get("billing_event", "IMPRESSIONS"),
                promoted_object=a.get("promoted_object"),
                dsa_beneficiary=a.get("dsa_beneficiary") or d.get("dsa_beneficiary"),
                dsa_payor=a.get("dsa_payor") or d.get("dsa_payor"),
                start_time=a.get("start_time"), end_time=a.get("end_time"))
            save()
        print(f"  adset   {state['adsets'][a['name']]}  {a['name']}")

        for ad in a["ads"]:
            if ad["name"] in state["ads"]:
                print(f"    ad    {state['ads'][ad['name']]}  {ad['name']}  (already created, skipped)")
                continue
            path = ad["creative"]
            p = Path(path) if Path(path).exists() else ROOT / path
            key = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
            is_video = p.suffix.lower() in (".mp4", ".mov", ".m4v", ".avi")

            if key not in state["media"]:
                if is_video:
                    vid, thumb = meta.upload_video(acct, p, ad["name"])
                    state["media"][key] = {"video_id": vid, "thumb": thumb}
                else:
                    state["media"][key] = {"hash": meta.upload_image(acct, p, ad["name"])}
                save()
            m = state["media"][key]

            common = dict(link=resolve(ad, d, "link"), body=ad.get("body", ""),
                          headline=ad.get("headline", ""), description=ad.get("description"),
                          cta=resolve(ad, d, "cta", "LEARN_MORE"),
                          ig_user_id=resolve(ad, d, "instagram_user_id"),
                          url_tags=resolve(ad, d, "url_tags"))
            page = resolve(ad, d, "page_id")
            creative = (meta.video_creative(page, m["video_id"], m["thumb"], **common)
                        if is_video else meta.image_creative(page, m["hash"], **common))
            state["ads"][ad["name"]] = meta.create_ad(
                acct, state["adsets"][a["name"]], ad["name"], creative,
                pixel_id=resolve(ad, d, "pixel_id"))
            save()
            print(f"    ad    {state['ads'][ad['name']]}  {ad['name']}")

    print(f"\nCreated {len(state['ads'])} ad(s) across {len(state['adsets'])} ad set(s). "
          f"ALL PAUSED.\nState: {state_path}")
    print(f"Now verify:  python3 scripts/verify.py --state {state_path} --spec {args.spec}")


if __name__ == "__main__":
    main()
