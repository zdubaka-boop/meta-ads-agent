"""Parse an uploaded workbook, validate it, and (on confirm) build it.

Shared by the web upload endpoint. Mirrors scripts/xlsx_to_spec.py +
build_campaign.py, but works from in-memory bytes instead of files, because a
serverless function has no writable project directory.

Safety is unchanged and non-negotiable: everything is created PAUSED, and a
missing budget / Page / link is an error rather than a default.
"""
import hashlib, json
from pathlib import Path
import meta, xlsx

LOCALES_PATH = Path(__file__).parent / "reference" / "data" / "locales.json"
VIDEO_EXT = (".mp4", ".mov", ".m4v", ".avi")


def _locales():
    try:
        return json.loads(LOCALES_PATH.read_text())
    except Exception:
        return {}


def _csv(v):
    return [x.strip() for x in str(v or "").split(",") if x.strip()]


def _minor(v, where, problems):
    if v in ("", None):
        return None
    try:
        f = float(str(v).replace(",", ""))
    except ValueError:
        problems.append(f"{where}: '{v}' is not a number")
        return None
    if f != int(f):
        problems.append(f"{where}: budgets are whole MINOR units (cents) — got {v}")
        return None
    return int(f)


def parse_workbook(xlsx_bytes, creatives):
    """-> (spec, problems, resolved). Never writes anything to Meta."""
    import io, tempfile, os
    fd, tmp = tempfile.mkstemp(suffix=".xlsx")
    try:
        os.write(fd, xlsx_bytes); os.close(fd)
        sheets = xlsx.sheets(tmp)
    finally:
        try: os.unlink(tmp)
        except OSError: pass

    problems, resolved = [], []
    for need in ("Campaign", "Ad Sets", "Ads"):
        if need not in sheets:
            problems.append(f"The workbook has no '{need}' tab — start from CAMPAIGN-TEMPLATE.xlsx")
    if problems:
        return None, problems, resolved

    kv = {}
    for row in sheets["Campaign"][1:]:
        if len(row) >= 2 and str(row[0]).strip():
            kv[str(row[0]).strip()] = str(row[1]).strip() if row[1] != "" else ""
    g = lambda k: (kv.get(k) or "").strip()

    for req in ("account_id", "campaign_name", "objective", "budget_mode", "page_id", "link", "cta"):
        if not g(req):
            problems.append(f"Campaign tab: '{req}' is empty and is required")
    mode = g("budget_mode").upper()
    if mode not in ("CBO", "ABO"):
        problems.append("Campaign tab: budget_mode must be CBO or ABO")
    camp_budget = _minor(g("daily_budget_minor"), "Campaign daily_budget_minor", problems)
    if mode == "CBO" and not camp_budget:
        problems.append("Campaign tab: daily_budget_minor is required for CBO (e.g. 20000 = 200.00)")

    defaults = {k: g(k) for k in ("page_id", "instagram_user_id", "pixel_id", "link", "cta",
                                  "url_tags", "dsa_beneficiary", "dsa_payor", "display_link") if g(k)}
    acct = g("account_id")
    LOC = _locales()

    # Validate the identities against the real account. These are the fields
    # people leave as template placeholders, and Meta's error for a bad one
    # ("The id of the object passed in is invalid") arrives only at ad
    # creation - after the campaign and ad sets already exist.
    if acct and defaults.get("page_id"):
        try:
            pages = {p["id"] for p in meta.get_all(f"{meta.account(acct)}/promote_pages", "id", cap=200)}
            if pages and defaults["page_id"] not in pages:
                problems.append(
                    f"Campaign tab: page_id {defaults['page_id']} is not a Page this ad "
                    f"account can promote. Available: {', '.join(sorted(pages)) or 'none'}")
        except Exception:
            pass
    if acct and defaults.get("pixel_id"):
        try:
            pix = {x["id"] for x in meta.get_all(f"{meta.account(acct)}/adspixels", "id", cap=100)}
            if pix and defaults["pixel_id"] not in pix:
                problems.append(
                    f"Campaign tab: pixel_id {defaults['pixel_id']} does not exist in this ad "
                    f"account (this is the template placeholder - replace or clear it). "
                    f"Available: {', '.join(sorted(pix)) or 'none'}")
        except Exception:
            pass

    rows = [r for r in xlsx.table(sheets["Ad Sets"])
            if str(r.get("adset_name", "")).strip()
            and (str(r.get("countries", "")).strip() or str(r.get("optimization_goal", "")).strip())]
    if not rows:
        problems.append("Ad Sets tab: no ad sets found (did you delete the example rows and add yours?)")

    adsets, by_name = [], {}
    for r in rows:
        name = str(r["adset_name"]).strip()
        countries = [c.upper() for c in _csv(r.get("countries"))]
        if not countries:
            problems.append(f"Ad set '{name}': countries is required")
        geo = {"countries": countries}
        lt = str(r.get("location_types") or "home+recent").strip()
        geo["location_types"] = ["home", "recent"] if lt == "home+recent" else [lt]

        for col, kind, key in (("cities", "city", "cities"), ("regions", "region", "regions")):
            out = []
            for nm in _csv(r.get(col)):
                try:
                    hit = meta.search_geo(nm, kind)
                except Exception as e:
                    problems.append(f"Ad set '{name}': could not look up {kind} '{nm}' ({e})"); continue
                if not hit:
                    problems.append(f"Ad set '{name}': no Meta {kind} matches '{nm}'"); continue
                e = {"key": hit["key"]}
                if kind == "city":
                    e["radius"] = 10; e["distance_unit"] = "mile"
                out.append(e)
                resolved.append(f"{kind} '{nm}' → {hit.get('name')} "
                                f"{hit.get('region') or ''} {hit.get('country_code') or ''}")
            if out:
                geo[key] = out

        t = {"geo_locations": geo,
             "age_min": int(r["age_min"]) if str(r.get("age_min", "")).strip() else 18,
             "age_max": int(r["age_max"]) if str(r.get("age_max", "")).strip() else 65}
        ex = [c.upper() for c in _csv(r.get("excluded_countries"))]
        if ex:
            t["excluded_geo_locations"] = {"countries": ex}
        gd = str(r.get("genders") or "All").strip().lower()
        if gd == "men":
            t["genders"] = [1]
        elif gd == "women":
            t["genders"] = [2]

        ids = []
        for L in _csv(r.get("languages")):
            if L in LOC:
                ids.append(LOC[L])
            else:
                near = [k for k in LOC if k.lower().startswith(L.lower()[:4])][:3]
                problems.append(f"Ad set '{name}': '{L}' is not a Meta language"
                                + (f" — did you mean {', '.join(near)}?" if near else ""))
        if ids:
            t["locales"] = ids

        found = []
        for nm in _csv(r.get("interests")):
            try:
                hit = meta.search_interest(nm)
            except Exception as e:
                problems.append(f"Ad set '{name}': could not look up interest '{nm}' ({e})"); continue
            if not hit:
                problems.append(f"Ad set '{name}': no Meta interest matches '{nm}'"); continue
            found.append({"id": hit["id"], "name": hit["name"]})
            resolved.append(f"interest '{nm}' → {hit['name']} "
                            f"(reach ~{hit.get('audience_size_lower_bound', '?'):,})"
                            if isinstance(hit.get("audience_size_lower_bound"), int)
                            else f"interest '{nm}' → {hit['name']}")
        if found:
            t["flexible_spec"] = [{"interests": found}]

        for col, key in (("publisher_platforms", "publisher_platforms"),
                         ("facebook_positions", "facebook_positions"),
                         ("instagram_positions", "instagram_positions")):
            v = _csv(r.get(col))
            if v:
                t[key] = v
        dev = str(r.get("device_platforms") or "All").strip().lower()
        if dev and dev != "all":
            t["device_platforms"] = _csv(dev)
        if str(r.get("advantage_audience") or "").strip().lower() == "yes":
            t["targeting_automation"] = {"advantage_audience": 1}

        a = {"name": name, "targeting": t, "ads": [],
             "optimization_goal": str(r.get("optimization_goal") or "LINK_CLICKS").strip(),
             "billing_event": str(r.get("billing_event") or "IMPRESSIONS").strip()}
        daily = _minor(r.get("daily_budget_minor"), f"Ad set '{name}' daily_budget_minor", problems)
        if mode == "ABO":
            if not daily:
                problems.append(f"Ad set '{name}': a budget is required for ABO — never defaulted")
            a["daily_budget_minor"] = daily
        elif daily:
            problems.append(f"Ad set '{name}': has a budget but the campaign is CBO — clear it")
        ev = str(r.get("custom_event_type", "")).strip()
        if ev and defaults.get("pixel_id"):
            a["promoted_object"] = {"pixel_id": defaults["pixel_id"], "custom_event_type": ev}
        for k in ("start_time", "end_time", "dsa_beneficiary"):
            if str(r.get(k, "")).strip():
                a[k] = str(r[k]).strip()
        adsets.append(a); by_name[name] = a

    seen = set()
    ad_rows = [r for r in xlsx.table(sheets["Ads"])
               if str(r.get("ad_name", "")).strip() and str(r.get("adset_name", "")).strip()]
    if not ad_rows:
        problems.append("Ads tab: no ads found")
    have = {k.lower(): k for k in creatives}
    for r in ad_rows:
        an, adn = str(r["adset_name"]).strip(), str(r["ad_name"]).strip()
        if an not in by_name:
            problems.append(f"Ad '{adn}' names ad set '{an}', which is not on the Ad Sets tab"); continue
        if adn in seen:
            problems.append(f"Duplicate ad name '{adn}' — ad names must be unique")
        seen.add(adn)
        cf = str(r.get("creative_file", "")).strip()
        key = Path(cf).name.lower()
        if not cf:
            problems.append(f"Ad '{adn}': creative_file is empty")
        elif key not in have:
            problems.append(f"Ad '{adn}': '{cf}' was not among the files you dropped in")
        elif Path(key).suffix in VIDEO_EXT:
            problems.append(f"Ad '{adn}': '{cf}' is a video. Serverless uploads cap at ~4.5MB, "
                            f"so videos must go through the CLI for now.")
        ad = {"name": adn, "creative": have.get(key, cf)}
        for k in ("body", "headline", "description", "cta", "link", "url_tags",
                  "page_id", "instagram_user_id"):
            v = str(r.get(k, "")).strip()
            if v:
                ad[k] = v
        if not (ad.get("link") or defaults.get("link")):
            problems.append(f"Ad '{adn}': no link, and no Campaign-tab default")
        if not (ad.get("page_id") or defaults.get("page_id")):
            problems.append(f"Ad '{adn}': no page_id, and no Campaign-tab default")
        by_name[an]["ads"].append(ad)

    for a in adsets:
        if not a["ads"]:
            problems.append(f"Ad set '{a['name']}' has no ads on the Ads tab")

    spec = {"account_id": acct, "defaults": defaults, "adsets": adsets,
            "campaign": {"name": g("campaign_name"), "objective": g("objective"),
                         "budget_mode": mode,
                         **({"daily_budget_minor": camp_budget} if mode == "CBO" else {}),
                         "special_ad_categories": _csv(g("special_ad_categories"))}}
    return spec, problems, resolved


class PartialBuild(RuntimeError):
    """Raised when a build dies after creating some objects, carrying their IDs
    so nothing is silently orphaned and a retry is not blind."""
    def __init__(self, msg, result):
        super().__init__(msg)
        self.result = result


def build(spec, creatives, log):
    """Create everything, PAUSED. Assumes parse_workbook returned no problems."""
    acct = spec["account_id"]
    c, d = spec["campaign"], spec.get("defaults", {})
    result = {"campaign": None, "adsets": [], "ads": [], "skipped": []}

    dupes = [x for x in meta.get_all(f"{meta.account(acct)}/campaigns", "id,name")
             if x.get("name") == c["name"]]
    if dupes:
        raise RuntimeError(
            f"A campaign named '{c['name']}' already exists ({dupes[0]['id']}). "
            f"Rename it in the workbook, or use option 2 to add into it instead.")

    cid = meta.create_campaign(acct, c["name"], c["objective"],
                              budget_minor=c.get("daily_budget_minor") if c["budget_mode"] == "CBO" else None,
                              special_ad_categories=c.get("special_ad_categories"))
    result["campaign"] = {"id": cid, "name": c["name"]}
    log(f"campaign {cid}  {c['name']}")

    media = {}
    for a in spec["adsets"]:
        aid = meta.create_adset(acct, cid, a["name"], a["targeting"],
                                budget_minor=a.get("daily_budget_minor"),
                                optimization_goal=a.get("optimization_goal", "LINK_CLICKS"),
                                billing_event=a.get("billing_event", "IMPRESSIONS"),
                                promoted_object=a.get("promoted_object"),
                                dsa_beneficiary=a.get("dsa_beneficiary") or d.get("dsa_beneficiary"),
                                dsa_payor=a.get("dsa_payor") or d.get("dsa_payor"),
                                start_time=a.get("start_time"), end_time=a.get("end_time"))
        result["adsets"].append({"id": aid, "name": a["name"]})
        log(f"  ad set {aid}  {a['name']}")

        for ad in a["ads"]:
            blob = creatives.get(ad["creative"])
            if blob is None:
                result["skipped"].append(f"{ad['name']} (creative missing)"); continue
            key = hashlib.sha256(blob).hexdigest()[:16]
            if key not in media:
                media[key] = meta.upload_image_bytes(acct, blob, ad["creative"], ad["name"])
            pick = lambda k, dv=None: ad.get(k) or d.get(k) or dv
            creative = meta.image_creative(
                pick("page_id"), media[key], link=pick("link"), body=ad.get("body", ""),
                headline=ad.get("headline", ""), description=ad.get("description"),
                cta=pick("cta", "LEARN_MORE"), ig_user_id=pick("instagram_user_id"),
                url_tags=pick("url_tags"))
            try:
                ad_id = meta.create_ad(acct, aid, ad["name"], creative, pixel_id=d.get("pixel_id"))
            except Exception as e:
                raise PartialBuild(f"Failed creating ad '{ad['name']}': {e}", result)
            result["ads"].append({"id": ad_id, "name": ad["name"], "adset": a["name"]})
            log(f"    ad {ad_id}  {ad['name']}")
    return result
