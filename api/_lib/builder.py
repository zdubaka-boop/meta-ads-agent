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

# Countries Meta will not deliver to without a signed Universal Ads
# Declaration on the ad account. Worldwide targeting includes them, so a
# buyer must either sign the declaration in Business Manager or exclude them.
DECLARATION_COUNTRIES = {"Taiwan": "TW", "Singapore": "SG"}


def _locales():
    try:
        return json.loads(LOCALES_PATH.read_text())
    except Exception:
        return {}


def _csv(v):
    return [x.strip() for x in str(v or "").split(",") if x.strip()]


def _variants(v):
    """Split a cell into text variants.

    Buyers write several primary texts or headlines in one cell, separated by
    a newline or a pipe. Commas are NOT a separator here: ad copy is full of
    them. Meta accepts at most 5 of each.
    """
    raw = str(v or "")
    parts = [p.strip() for p in raw.replace("\r", "").split("\n")] if "\n" in raw \
            else [p.strip() for p in raw.split("|")]
    return [p for p in parts if p][:5]


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


def parse_workbook(xlsx_bytes, creatives, mode="campaign", inherit=None):
    """-> (spec, problems, resolved). Never writes anything to Meta.

    mode="campaign": building a new campaign, so the Campaign tab is required.
    mode="append":   adding into a campaign that already exists. The campaign's
                     own name / objective / budget mode come from Meta, so those
                     cells are ignored, and a blank page_id / link / cta is
                     inherited from the ads already in that campaign rather than
                     demanded again. One template serves both.
    """
    inherit = inherit or {}
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

    appending = (mode == "append")
    required = ("account_id", "page_id", "link", "cta") if appending else \
               ("account_id", "campaign_name", "objective", "budget_mode",
                "page_id", "link", "cta")

    defaults = {k: g(k) for k in ("page_id", "instagram_user_id", "pixel_id", "link", "cta",
                                  "url_tags", "dsa_beneficiary", "dsa_payor", "display_link") if g(k)}
    acct = g("account_id") or inherit.get("account_id", "")
    if appending:
        # Anything the sheet leaves blank comes from the campaign being added to.
        for k in ("page_id", "link", "cta", "pixel_id", "instagram_user_id",
                  "url_tags", "dsa_beneficiary"):
            if not defaults.get(k) and inherit.get(k):
                defaults[k] = inherit[k]

    for req in required:
        have_it = acct if req == "account_id" else defaults.get(req)
        if not have_it:
            problems.append(
                f"Campaign tab: '{req}' is empty and is required"
                if not appending else
                f"'{req}' is missing — put it on the Campaign tab, or set it on each ad row")

    mode_budget = (g("budget_mode") or (inherit.get("budget_mode") if appending else "")).upper()
    if not appending and mode_budget not in ("CBO", "ABO"):
        problems.append("Campaign tab: budget_mode must be CBO or ABO")
    camp_budget = _minor(g("daily_budget_minor"), "Campaign daily_budget_minor", problems)
    if not appending and mode_budget == "CBO" and not camp_budget:
        problems.append("Campaign tab: daily_budget_minor is required for CBO (e.g. 20000 = 200.00)")
    mode = mode_budget
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
        raw_countries = _csv(r.get("countries"))
        worldwide = any(c.strip().lower() in ("worldwide", "ww", "all", "global")
                        for c in raw_countries)
        countries = [c.upper() for c in raw_countries
                     if c.strip().lower() not in ("worldwide", "ww", "all", "global")]
        langs_present = bool(_csv(r.get("languages")))
        if worldwide or (not countries and langs_present):
            # Language-only targeting: Meta still needs a geography, so use its
            # worldwide country group. Common for "target Spanish speakers
            # anywhere" style buys.
            geo = {"country_groups": ["worldwide"]}
            if countries:
                geo["countries"] = countries
        elif countries:
            geo = {"countries": countries}
        else:
            problems.append(
                f"Ad set '{name}': needs a location. Put ISO codes in 'countries' "
                f"(e.g. GB,IE), or write 'worldwide', or set 'languages' and leave "
                f"countries blank to target that language everywhere.")
            geo = {"countries": []}
        if "countries" in geo:
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

        if geo.get("country_groups"):
            missing = [iso for iso in DECLARATION_COUNTRIES.values()
                       if iso not in [c.upper() for c in _csv(r.get("excluded_countries"))]]
            if missing:
                problems.append(
                    f"Ad set '{name}': worldwide targeting includes "
                    f"{', '.join(missing)}, which Meta will not deliver to without a signed "
                    f"Universal Ads Declaration. Put {','.join(missing)} in "
                    f"excluded_countries, or list your countries explicitly.")

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

    # Lazily fetched: only pay for the listing if a row needs it.
    lib = {"img": None, "vid": None}

    def resolve_creative(cf, problems, who):
        """-> ('upload'|'url'|'hash'|'video', reference) | (None, None)"""
        if meta.is_remote_url(cf):
            return "url", cf
        key = Path(cf).name.strip().lower()
        if key in have:
            if Path(key).suffix in VIDEO_EXT:
                problems.append(f"{who}: '{cf}' is a video. Upload it to the ad account "
                                f"once, then reference it by name here — browser uploads "
                                f"cap at ~4.5MB.")
                return None, None
            return "upload", have[key]
        if len(cf.strip()) == 32 and all(ch in "0123456789abcdef" for ch in cf.strip().lower()):
            return "hash", cf.strip().lower()          # an image hash, pasted directly
        if lib["img"] is None:
            try:
                lib["img"] = meta.account_images(acct)
                lib["vid"] = meta.account_videos(acct)
            except Exception:
                lib["img"], lib["vid"] = {}, {}
        stem = key.rsplit(".", 1)[0]
        if key in lib["img"] or stem in lib["img"]:
            return "hash", lib["img"].get(key) or lib["img"][stem]
        if key in lib["vid"] or stem in lib["vid"]:
            return "video", lib["vid"].get(key) or lib["vid"][stem]
        problems.append(f"{who}: '{cf}' is neither among the files you dropped in nor "
                        f"an image or video already in this ad account.")
        return None, None

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
        # Uniqueness is checked inside the creative loop below, since one row
        # can produce several ads.
        creatives_cell = _variants(r.get("creative_file"))
        if not creatives_cell:
            problems.append(f"Ad '{adn}': creative_file is empty")

        base = {}
        for k in ("cta", "link", "url_tags", "page_id", "instagram_user_id"):
            v = str(r.get(k, "")).strip()
            if v:
                base[k] = v
        for src, many in (("body", "bodies"), ("headline", "headlines"),
                          ("description", "descriptions")):
            vs = _variants(r.get(src))
            if vs:
                base[src] = vs[0]
                base[many] = vs
        if len(base.get("bodies", [])) > 5 or len(base.get("headlines", [])) > 5:
            problems.append(f"Ad '{adn}': Meta accepts at most 5 primary texts and "
                            f"5 headlines per ad.")
        if not (base.get("link") or defaults.get("link")):
            problems.append(f"Ad '{adn}': no link, and no Campaign-tab default")
        if not (base.get("page_id") or defaults.get("page_id")):
            problems.append(f"Ad '{adn}': no page_id, and no Campaign-tab default")

        # Several creatives in one row = one ad each, sharing the copy. Text
        # variants rotate inside an ad, so only creatives need separate ads.
        multi = len(creatives_cell) > 1
        for idx, cf in enumerate(creatives_cell, start=1):
            kind, ref = resolve_creative(cf, problems, f"Ad '{adn}'")
            nm = adn if not multi else f"{adn} {idx:02d}"[:80]
            if nm in seen:
                problems.append(f"Duplicate ad name '{nm}' — ad names must be unique")
            seen.add(nm)
            ad = dict(base)
            ad["name"] = nm
            ad["creative"] = ref if kind == "upload" else cf
            ad["_kind"], ad["_ref"] = kind, ref
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

    remote = [ad["_ref"] for a in spec["adsets"] for ad in a["ads"]
              if ad.get("_kind") == "url"]
    media = meta.upload_many(acct, remote, lanes=4, log=log) if remote else {}
    for a in spec["adsets"]:
      try:
        aid = meta.create_adset(acct, cid, a["name"], a["targeting"],
                                budget_minor=a.get("daily_budget_minor"),
                                optimization_goal=a.get("optimization_goal", "LINK_CLICKS"),
                                billing_event=a.get("billing_event", "IMPRESSIONS"),
                                promoted_object=a.get("promoted_object"),
                                dsa_beneficiary=a.get("dsa_beneficiary") or d.get("dsa_beneficiary"),
                                dsa_payor=a.get("dsa_payor") or d.get("dsa_payor"),
                                start_time=a.get("start_time"), end_time=a.get("end_time"))
      except Exception as e:
        msg = str(e)
        import re as _re
        m = _re.search(r"No ([A-Za-z ]+) Universal Ads Declaration", msg)
        if m:
            msg = (f"Ad set '{a['name']}': {m.group(1)} requires a Universal Ads Declaration "
                   f"that this ad account has not signed, and worldwide targeting includes it. "
                   f"Add {DECLARATION_COUNTRIES.get(m.group(1).strip(), '')} to "
                   f"excluded_countries (currently known: TW, SG), or list the countries you "
                   f"want explicitly instead of targeting worldwide.")
        raise PartialBuild(msg, result)
      else:
        result["adsets"].append({"id": aid, "name": a["name"]})
        log(f"  ad set {aid}  {a['name']}")

        for ad in a["ads"]:
            kind = ad.get("_kind")
            if kind == "hash":
                img_hash = ad["_ref"]
            elif kind == "url":
                m = media[meta.media_key(ad["_ref"])]
                video_id, thumb = m["video_id"], m["thumb"]
            elif kind == "video":
                video_id = ad["_ref"]
                thumb = meta.wait_for_video(video_id)
            else:
                blob = creatives.get(ad["creative"])
                if blob is None:
                    result["skipped"].append(f"{ad['name']} (creative missing)"); continue
                key = hashlib.sha256(blob).hexdigest()[:16]
                if key not in media:
                    media[key] = meta.upload_image_bytes(acct, blob, ad["creative"], ad["name"])
                img_hash = media[key]
            pick = lambda k, dv=None: ad.get(k) or d.get(k) or dv
            common = dict(link=pick("link"), body=ad.get("body", ""),
                          headline=ad.get("headline", ""), description=ad.get("description"),
                          cta=pick("cta", "LEARN_MORE"), ig_user_id=pick("instagram_user_id"),
                          url_tags=pick("url_tags"), bodies=ad.get("bodies"),
                          headlines=ad.get("headlines"), descriptions=ad.get("descriptions"))
            creative = (meta.video_creative(pick("page_id"), video_id, thumb, **common)
                        if kind in ("url", "video")
                        else meta.image_creative(pick("page_id"), img_hash, **common))
            try:
                ad_id = meta.create_ad(acct, aid, ad["name"], creative, pixel_id=d.get("pixel_id"))
            except Exception as e:
                raise PartialBuild(f"Failed creating ad '{ad['name']}': {e}", result)
            result["ads"].append({"id": ad_id, "name": ad["name"], "adset": a["name"]})
            log(f"    ad {ad_id}  {ad['name']}")
    return result


def parse_ads_only(file_bytes, filename, creatives, defaults):
    """Read ads from a CSV or the Ads tab of a workbook, for adding into an
    ad set that already exists. Returns (ads, problems)."""
    import csv as _csv, io, os, tempfile
    problems, rows = [], []
    if filename.lower().endswith((".xlsx", ".xlsm")):
        fd, tmp = tempfile.mkstemp(suffix=".xlsx")
        try:
            os.write(fd, file_bytes); os.close(fd)
            sheets = xlsx.sheets(tmp)
        finally:
            try: os.unlink(tmp)
            except OSError: pass
        if "Ads" not in sheets:
            return [], ["That workbook has no 'Ads' tab."]
        rows = xlsx.table(sheets["Ads"])
    else:
        rows = list(_csv.DictReader(io.StringIO(file_bytes.decode("utf-8-sig", "replace"))))

    have = {Path(k).name.lower(): k for k in creatives}
    ads, seen = [], set()
    for r in rows:
        r = {(k or "").strip(): (str(v).strip() if v is not None else "")
             for k, v in r.items() if k}
        name = r.get("ad_name") or r.get("name")
        cf = r.get("creative_file") or r.get("creative") or ""
        if not name or not cf:
            continue
        if name in seen:
            problems.append(f"Duplicate ad name '{name}' in the file")
        seen.add(name)
        key = Path(cf).name.lower()
        remote = meta.is_remote_url(cf)
        if key not in have and not remote:
            problems.append(f"Ad '{name}': '{cf}' was not among the files you dropped in")
        elif not remote and Path(key).suffix in VIDEO_EXT:
            problems.append(f"Ad '{name}': '{cf}' is a video — browser uploads cap at ~4.5MB, "
                            f"so videos go through the CLI.")
        ad = {"name": name, "creative": have.get(key, cf),
              "_kind": "url" if remote else "upload", "_ref": cf}
        for k in ("cta", "link", "url_tags", "page_id", "instagram_user_id"):
            if r.get(k):
                ad[k] = r[k]
        for src, many in (("body", "bodies"), ("headline", "headlines"),
                          ("description", "descriptions")):
            vs = _variants(r.get(src))
            if vs:
                ad[src] = vs[0]
                ad[many] = vs
        if not (ad.get("link") or defaults.get("link")):
            problems.append(f"Ad '{name}': no link, and no default on the account")
        if not (ad.get("page_id") or defaults.get("page_id")):
            problems.append(f"Ad '{name}': no page_id, and no default on the account")
        ads.append(ad)
    if not ads:
        problems.append("No ads found. Need columns ad_name and creative_file.")
    return ads, problems


def add_ads_to_adset(acct, adset_id, ads, creatives, defaults, log):
    """Create ads inside an ad set that already exists. PAUSED, dedup by name."""
    existing = {a.get("name") for a in meta.get_all(f"{adset_id}/ads", "id,name", cap=1000)}
    created, skipped, media = [], [], {}
    remote = [ad.get("_ref") or ad["creative"] for ad in ads
              if ad.get("_kind") == "url" or meta.is_remote_url(ad["creative"])]
    if remote:
        media.update(meta.upload_many(acct, remote, lanes=4, log=log))
    for ad in ads:
        if ad["name"] in existing:
            skipped.append(ad["name"]); continue
        is_video = ad.get("_kind") == "url" or meta.is_remote_url(ad["creative"])
        if is_video:
            key = meta.media_key(ad.get("_ref") or ad["creative"])
        else:
            blob = creatives.get(ad["creative"])
            if blob is None:
                skipped.append(f"{ad['name']} (creative missing)"); continue
            key = hashlib.sha256(blob).hexdigest()[:16]
            if key not in media:
                media[key] = meta.upload_image_bytes(acct, blob, ad["creative"], ad["name"])
        pick = lambda k, dv=None: ad.get(k) or defaults.get(k) or dv
        common = dict(link=pick("link"), body=ad.get("body", ""),
                      headline=ad.get("headline", ""), description=ad.get("description"),
                      cta=pick("cta", "LEARN_MORE"), ig_user_id=pick("instagram_user_id"),
                      url_tags=pick("url_tags"), bodies=ad.get("bodies"),
                      headlines=ad.get("headlines"), descriptions=ad.get("descriptions"))
        creative = (meta.video_creative(pick("page_id"), media[key]["video_id"],
                                        media[key]["thumb"], **common)
                    if is_video else meta.image_creative(pick("page_id"), media[key], **common))
        ad_id = meta.create_ad(acct, adset_id, ad["name"], creative,
                               pixel_id=defaults.get("pixel_id"))
        created.append({"id": ad_id, "name": ad["name"]})
        log(f"ad {ad_id}  {ad['name']}")
    return {"created": created, "skipped": skipped}


def add_adsets_to_campaign(acct, campaign_id, spec, creatives, log):
    """Create ONLY new ad sets (and their ads) inside a campaign that exists.

    Nothing about the campaign or its existing ad sets is changed. If an ad
    set name already exists, resume into it and add only ads whose names are
    missing. This repairs partial runs without duplicating anything.
    """
    camp = meta.get(campaign_id, "id,name,daily_budget,lifetime_budget,objective")
    cbo = bool(camp.get("daily_budget") or camp.get("lifetime_budget"))
    d = spec.get("defaults", {})
    existing = {a.get("name"): a.get("id") for a in
                meta.get_all(f"{campaign_id}/adsets", "id,name", cap=500)}

    result = {"campaign": {"id": campaign_id, "name": camp.get("name")},
              "adsets": [], "ads": [], "skipped": []}
    problems = []
    todo = []
    for a in spec.get("adsets", []):
        resumes = a["name"] in existing
        if not resumes and cbo and a.get("daily_budget_minor"):
            problems.append(f"Ad set '{a['name']}': this campaign holds the budget (CBO), "
                            f"so the ad set must not have one — clear daily_budget_minor.")
        if not resumes and not cbo and not a.get("daily_budget_minor"):
            problems.append(f"Ad set '{a['name']}': this campaign uses ad-set budgets (ABO), "
                            f"so a budget is required — it is never guessed.")
        todo.append(a)
    if problems:
        raise PartialBuild(" / ".join(problems), result)
    if not todo:
        return result

    for a in todo:
        aid = existing.get(a["name"])
        try:
            if not aid:
                aid = meta.create_adset(
                acct, campaign_id, a["name"], a["targeting"],
                budget_minor=a.get("daily_budget_minor"),
                optimization_goal=a.get("optimization_goal", "LINK_CLICKS"),
                billing_event=a.get("billing_event", "IMPRESSIONS"),
                promoted_object=a.get("promoted_object"),
                dsa_beneficiary=a.get("dsa_beneficiary") or d.get("dsa_beneficiary"),
                dsa_payor=a.get("dsa_payor") or d.get("dsa_payor"),
                start_time=a.get("start_time"), end_time=a.get("end_time"))
        except Exception as e:
            raise PartialBuild(f"Failed creating ad set '{a['name']}': {e}", result)
        result["adsets"].append({"id": aid, "name": a["name"],
                                 "resumed": a["name"] in existing})
        log(f"{'resumed' if a['name'] in existing else 'ad set'} {aid}  {a['name']}")
        res = add_ads_to_adset(acct, aid, a.get("ads", []), creatives, d, log)
        result["ads"].extend(res["created"])
        result["skipped"].extend(res["skipped"])
    return result
