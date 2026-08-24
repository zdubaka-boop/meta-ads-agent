#!/usr/bin/env python3
"""Turn a folder of creatives + a pile of copy into a finished workbook.

Built for the real job: someone drops 200 images and a wall of text and says
"same settings as last month's campaign".

  python3 scripts/bulk_build.py \
      --creatives ~/Desktop/spring \
      --copy copy.json \
      --like 120250... \
      --name "Spring 2026 | EU" \
      --out ~/Desktop/SPRING.xlsx

--creatives  a folder. Grouping is worked out by scan_creatives.py: one
             sub-folder per ad set, or a shared part of the filename.
--copy       what to write on the ads (shape below).
--like       an existing campaign to take settings and targeting from. Optional,
             but it is how "same as last time" is answered.
--name       the new campaign's name. Must not already exist in the account.

copy.json — keyed by group, and optionally by the angle inside it:

  {
    "lt": {"bodies": ["...", "..."], "headlines": ["..."]},
    "pl": {
      "price": {"bodies": ["..."], "headlines": ["..."]},
      "_default": {"bodies": ["..."], "headlines": ["..."]}
    }
  }

Anything with no copy is reported, never invented.
"""
import argparse, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import meta
from scan_creatives import tokens, classify, IMG, VID

meta.load_env()


def load_locales():
    """Meta language id -> name, the same table the converter resolves against."""
    try:
        return json.loads((ROOT / "reference" / "data" / "locales.json").read_text())
    except OSError:
        return {}


def load_countries():
    p = ROOT / "reference" / "data" / "countries.json"
    try:
        return {c["c"].lower(): c["c"] for c in json.loads(p.read_text())}
    except OSError:
        return {}


def group_files(folder):
    """-> (basis, {group: [filenames]}). Same logic scan_creatives reports."""
    from collections import defaultdict, Counter
    files = sorted(p for p in folder.rglob("*")
                   if p.is_file() and p.suffix.lower() in (IMG | VID)
                   and not p.name.startswith("."))
    if not files:
        sys.exit(f"No creatives in {folder}")
    by_dir = defaultdict(list)
    for f in files:
        by_dir[str(f.parent.relative_to(folder))].append(f)
    if len(by_dir) > 1:
        return "folders", {k: v for k, v in sorted(by_dir.items())}

    toks = [tokens(f.name) for f in files]
    width = Counter(len(t) for t in toks).most_common(1)[0][0]
    for i in range(width):
        kind, _ = classify([t[i] if i < len(t) else "" for t in toks])
        if kind in ("market", "group"):
            g = defaultdict(list)
            for f, t in zip(files, toks):
                g[t[i] if i < len(t) else "?"].append(f)
            return f"part {i+1} of the filename", dict(sorted(g.items()))
    return None, {"all": files}


def angle_of(fname):
    from scan_creatives import ANGLE_WORDS
    for t in tokens(fname):
        if t in ANGLE_WORDS:
            return t
    return None


# Targeting keys Meta returns that are not audience narrowing - carrying them
# is meaningless, and warning about them would be noise.
TARGETING_NOISE = {
    "age_min", "age_max", "geo_locations", "excluded_geo_locations",
    "targeting_relaxation_types", "targeting_automation", "brand_safety_content_filter_levels",
    "brand_safety_content_severity_levels", "instream_video_skippable_excluded",
    "publisher_platforms", "device_platforms", "facebook_positions",
    "instagram_positions", "audience_network_positions", "messenger_positions",
    "threads_positions", "locales", "genders", "custom_audiences",
    "excluded_custom_audiences", "flexible_spec", "interests", "exclusions",
}
GENDER_NAME = {1: "Men", 2: "Women"}


def _names(v):
    """Meta returns [{id, name}] for interests and audiences; the sheet wants names."""
    out = []
    for x in v or []:
        n = x.get("name") if isinstance(x, dict) else x
        if n:
            out.append(str(n))
    return out


def settings_from(campaign_id):
    """Campaign-level settings and one representative ad set's targeting.

    Everything this cannot carry into the workbook is returned under
    "not_copied" and reported. Silently dropping a narrowed audience would
    turn "same settings as last month" into a much broader, costlier campaign.
    """
    c = meta.get(campaign_id, "name,objective,daily_budget,lifetime_budget,account_id")
    out = {"account_id": meta.account(c.get("account_id")),
           "objective": c.get("objective"),
           "cbo": bool(c.get("daily_budget") or c.get("lifetime_budget")),
           "daily_budget_minor": int(c.get("daily_budget") or 0) or None,
           "from": c.get("name"), "not_copied": []}
    sets_ = meta.get_all(f"{campaign_id}/adsets",
                         "name,daily_budget,optimization_goal,billing_event,targeting,"
                         "promoted_object,dsa_beneficiary", cap=5)
    if sets_:
        a = sets_[0]
        t = a.get("targeting") or {}
        out.update({
            "optimization_goal": a.get("optimization_goal"),
            "billing_event": a.get("billing_event"),
            "age_min": t.get("age_min"), "age_max": t.get("age_max"),
            "adset_budget_minor": int(a.get("daily_budget") or 0) or None,
            "dsa_beneficiary": a.get("dsa_beneficiary"),
            "custom_event_type": (a.get("promoted_object") or {}).get("custom_event_type"),
            "example_adset": a.get("name"),
        })
        # --- audience, carried by name so the converter can resolve it again ---
        ints = list(t.get("interests") or [])
        for blk in t.get("flexible_spec") or []:
            ints += blk.get("interests") or []
        out["interests"] = _names(ints)
        out["excluded_interests"] = _names((t.get("exclusions") or {}).get("interests"))
        out["custom_audiences"] = _names(t.get("custom_audiences"))
        out["excluded_custom_audiences"] = _names(t.get("excluded_custom_audiences"))
        g = t.get("genders") or []
        if len(g) == 1:
            out["genders"] = GENDER_NAME.get(g[0])
        rev = {v: k for k, v in load_locales().items()}
        out["languages"] = [rev[i] for i in (t.get("locales") or []) if i in rev]
        if t.get("locales") and not out["languages"]:
            out["not_copied"].append(f"locales {t['locales']} (no name for these language ids)")
        # --- placements ---
        for k in ("publisher_platforms", "device_platforms",
                  "facebook_positions", "instagram_positions"):
            if t.get(k):
                out[k] = t[k]
        # --- anything else that narrows the audience and we cannot express ---
        for k, v in t.items():
            if k not in TARGETING_NOISE and v not in (None, [], {}, ""):
                out["not_copied"].append(k)
    for a in meta.get_all(f"{campaign_id}/adsets", "id", cap=1):
        for ad in meta.get_all(f"{a['id']}/ads",
                               "creative{object_story_spec,url_tags}", cap=1):
            cr = ad.get("creative") or {}
            oss = cr.get("object_story_spec") or {}
            ld = oss.get("link_data") or oss.get("video_data") or {}
            cta = ld.get("call_to_action") or {}
            out["page_id"] = oss.get("page_id")
            out["link"] = ld.get("link") or (cta.get("value") or {}).get("link")
            out["cta"] = cta.get("type")
            out["url_tags"] = cr.get("url_tags")
    nc = out.pop("not_copied")
    out = {k: v for k, v in out.items() if v not in (None, "", [])}
    out["not_copied"] = nc
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--creatives", required=True)
    ap.add_argument("--copy", help="copy.json keyed by group")
    ap.add_argument("--like", help="campaign id to copy settings and targeting from")
    ap.add_argument("--name", help="name for the new campaign")
    ap.add_argument("--link"); ap.add_argument("--page"); ap.add_argument("--budget", type=float)
    ap.add_argument("--account", help="act_... — required unless --like supplies it")
    ap.add_argument("--out", required=True)
    ap.add_argument("--show-pairing", action="store_true",
                    help="print which copy lands on which creative, for review")
    ap.add_argument("--dry-run", action="store_true",
                    help="report the pairing without writing the workbook")
    args = ap.parse_args()

    folder = Path(args.creatives).expanduser()
    basis, groups = group_files(folder)
    copy = json.loads(Path(args.copy).read_text()) if args.copy else {}
    iso = load_countries()
    try:
        base = settings_from(args.like) if args.like else {}
    except Exception as e:
        sys.exit(f"\nCould not read campaign {args.like}: {e}\n"
                 f"Nothing was written. Run without --like to build from the "
                 f"folder alone, then fill the settings in by hand.")

    total = sum(len(v) for v in groups.values())
    print("=" * 74)
    print(f"  {total} creative(s), {len(groups)} group(s)"
          + (f", grouped by {basis}" if basis else ""))
    if base:
        print(f"  settings copied from: {base.get('from')}")
        carried = [k for k in ("interests", "custom_audiences", "languages", "genders",
                               "publisher_platforms") if base.get(k)]
        if carried:
            print("  targeting carried:     " + ", ".join(carried))
    print("=" * 74)

    problems, adsets, ads = [], [], []
    used_keys, used_angles = set(), set()   # copy that never lands is copy lost
    for gname, files in groups.items():
        key = gname.lower()
        cc = iso.get(key)
        aset = f"{args.name or 'Campaign'} | {gname.upper()}"
        row = {"name": aset,
               "countries": [cc] if cc else [],
               "age_min": base.get("age_min", 18), "age_max": base.get("age_max", 65),
               "optimization_goal": base.get("optimization_goal", "LINK_CLICKS"),
               "billing_event": base.get("billing_event", "IMPRESSIONS")}
        for k in ("interests", "excluded_interests", "custom_audiences",
                  "excluded_custom_audiences", "languages", "genders",
                  "publisher_platforms", "device_platforms",
                  "facebook_positions", "instagram_positions"):
            if base.get(k):
                row[k] = base[k]
        if base.get("dsa_beneficiary"):
            row["dsa_beneficiary"] = base["dsa_beneficiary"]
        if base.get("custom_event_type"):
            row["custom_event_type"] = base["custom_event_type"]
        if not base.get("cbo", True) and base.get("adset_budget_minor"):
            row["daily_budget_minor"] = base["adset_budget_minor"]
        if not cc:
            problems.append(f"group '{gname}': not a country code — say which country "
                            f"this ad set targets")
        adsets.append(row)

        gcopy = copy.get(gname) or copy.get(key) or {}
        if gcopy:
            used_keys.add(gname if gname in copy else key)
        used, pairs = 0, []
        for f in files:
            ang = angle_of(f.name)
            c = None
            if ang and isinstance(gcopy.get(ang), dict):
                c = gcopy[ang]
                used_angles.add(f"{gname}.{ang}")
            elif gcopy.get("_default"):
                c = gcopy["_default"]
                used_angles.add(f"{gname}._default")
            elif "bodies" in gcopy or "headlines" in gcopy:
                c = gcopy
            c = c or {}
            bodies = [b for b in (c.get("bodies") or []) if b][:5]
            heads = [h for h in (c.get("headlines") or []) if h][:5]
            if not bodies:
                problems.append(f"{f.name}: no copy for group '{gname}'"
                                + (f" / angle '{ang}'" if ang else ""))
            # Bare filename when the folder is the repo's own creatives/ dir
            # (the converter prefixes it); full path when it lives anywhere
            # else, or the build cannot find the file.
            ref = f.name if f.parent == ROOT / "creatives" else str(f.resolve())
            ads.append({"adset": aset,
                        "name": f"{args.name or 'AD'} {gname.upper()} {f.stem}"[:80],
                        "creative": ref, "bodies": bodies, "headlines": heads})
            used += 1
            pairs.append((f.name, bodies[0] if bodies else None))
        print(f"  {gname:<14} {used:>4} ad(s)"
              + (f"   -> {cc}" if cc else "   -> country unknown"))
        if args.show_pairing:
            # One line per distinct primary text, with the files that got it.
            byline = {}
            for fn, body in pairs:
                byline.setdefault(body, []).append(fn)
            for body, fns in byline.items():
                head = f"      {len(fns):>3} x  "
                print(head + (f'"{body[:52]}"' if body else "NO COPY"))
                print(" " * len(head) + ", ".join(fns[:4])
                      + (f" +{len(fns)-4} more" if len(fns) > 4 else ""))

    brief = {"account_id": args.account or base.get("account_id"),
             "campaign": {"name": args.name or "",
                          "objective": base.get("objective", "OUTCOME_TRAFFIC"),
                          "budget_mode": "CBO" if base.get("cbo", True) else "ABO"},
             "defaults": {k: v for k, v in {
                 "page_id": args.page or base.get("page_id"),
                 "link": args.link or base.get("link"),
                 "cta": base.get("cta", "LEARN_MORE"),
                 "url_tags": base.get("url_tags"),
                 "dsa_beneficiary": base.get("dsa_beneficiary")}.items() if v},
             "adsets": adsets, "ads": ads}
    if brief["campaign"]["budget_mode"] == "CBO":
        b = int(round(args.budget * 100)) if args.budget else base.get("daily_budget_minor")
        if b:
            brief["campaign"]["daily_budget_minor"] = b
        else:
            problems.append("no campaign budget — say what it should be")
    if not brief["campaign"]["name"]:
        problems.append("no campaign name — pass --name")
    if not brief["account_id"]:
        problems.append("no ad account — pass --account act_...")
    for k in copy:
        if k not in used_keys and k.lower() not in {x.lower() for x in used_keys}:
            problems.append(f"copy block '{k}' matched no group — that text was NOT used "
                            f"(groups are: {', '.join(groups)})")
    for k, blk in copy.items():
        if not isinstance(blk, dict):
            continue
        for ang in blk:
            if ang in ("bodies", "headlines", "descriptions"):
                continue
            if f"{k}.{ang}" not in used_angles and ang != "_default":
                problems.append(f"copy block '{k}.{ang}' matched no creative — "
                                f"no filename in group '{k}' contains '{ang}'")
    for k in base.get("not_copied", []):
        problems.append(f"'{k}' targeting on {base.get('from')!r} could NOT be copied — "
                        f"these ad sets will target more broadly than it does")
    for field, why in (("page_id", "which Facebook Page runs these ads"),
                       ("link", "the landing page URL")):
        if not brief["defaults"].get(field):
            problems.append(f"no {field} — {why}")

    if problems:
        print(f"\n  {len(problems)} thing(s) still needed:")
        for msg in problems[:14]:
            print("    - " + msg)
        if len(problems) > 14:
            print(f"    … and {len(problems)-14} more")

    print(f"\n  {len(adsets)} ad set(s), {len(ads)} ad(s)")
    if args.dry_run:
        print("\n  DRY RUN — nothing written.")
        return

    tmp = Path("/tmp/bulk_brief.json"); tmp.write_text(json.dumps(brief, ensure_ascii=False))
    import subprocess
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "fill_template.py"),
                        str(tmp), "--out", args.out], capture_output=True, text=True)
    print(r.stdout.strip())
    if r.returncode:
        sys.exit(r.stderr.strip()[:400])
    if problems:
        print(f"\n  The workbook is written, but {len(problems)} field(s) are still blank "
              f"on purpose.\n  Nothing was invented — fill them in before uploading.")


if __name__ == "__main__":
    main()
