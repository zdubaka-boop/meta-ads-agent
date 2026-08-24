#!/usr/bin/env python3
"""Preflight — run this FIRST, every time, on a fresh clone.

Checks everything that could block work and prints a single checklist, then
lists the ad accounts you can reach. Fully read-only: it never writes to Meta.

  python3 scripts/preflight.py
"""
import os, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "lib"))
import meta


TOKEN_TUTORIAL = """
  You need a Meta access token. ~5 minutes, one time. All links below.

  STEP 1 — Create the app
    https://developers.facebook.com/apps/create/
    When it asks what you want to do, pick:

        "Create and manage ads with Marketing API"

    That choice matters - it sets the app up for ads access. If you pick
    anything else the permissions you need will not be offered later.
    Name it anything (e.g. "Ads Agent"), attach your Business account.

  STEP 2 — Fill in the Privacy Policy URL
    Your app  ->  App settings  ->  Basic
    Paste ANY working privacy policy URL, then "Save changes".
    It genuinely does not matter which one. The app stays in Development
    mode, is never reviewed, and is never public - the field just has to be
    non-empty before Meta will hand out ads permissions. Any public page:
      https://www.iubenda.com/privacy-policy/7787549

  STEP 3 — Open the use case, then Customize
    In your app's left sidebar click  "Use cases"
    On "Create and manage ads with Marketing API" click  "Customize"
    Wait for it to load.

    (Do NOT use the old Graph API Explorer - the permissions you need are
     granted from inside the use case, not there.)

  STEP 4 — Go to Tools, then Get access token
    Inside the Customize screen, open the  "Tools"  tab.
    Click  "Get access token".

    Direct link - swap in your own app id from the browser address bar:
      https://developers.facebook.com/apps/YOUR_APP_ID/use_cases/customize/tools/?use_case_enum=MARKETING_API_ADS_MANAGEMENT&selected_tab=tools&product_route=marketing-api

  STEP 5 — Select every permission, then generate
    TICK EVERY BOX in the permissions list, including:
        ads_read
        ads_management
        business_management
        pages_read_engagement
        pages_show_list
    Select them all - miss one and the tools fail later with a confusing
    error. Click "Get token" and approve the Facebook login prompt.
    A long string starting with "EAA..." appears. Copy it.

  STEP 6 — Hand it over
    A box will open on your screen. Paste the token into it and press Save.
    That is the whole step.

    >>> Do NOT paste the token into the Claude chat window. <<<
    Chat is saved in the transcript. The box keeps it in a local .env only
    you can read. Pasted one by accident? Revoke it here:
      https://www.facebook.com/settings?tab=business_tools

  STEP 7 — Done
    Your ad accounts appear and you can start working.

  TROUBLESHOOTING
    "0 ad accounts found"
        Token works, but your Facebook user has no ad account access.
        An admin adds you here:
          https://business.facebook.com/settings/people
    Token expires in ~60 days.
        For a team, use a System User token instead - never expires, belongs
        to the business rather than one person, same permissions:
          https://business.facebook.com/settings/system-users
"""

OK, WARN, BAD, SKIP = "[ OK ]", "[WARN]", "[FAIL]", "[ -- ]"
lines, blockers, notes = [], [], []


def row(status, label, detail=""):
    lines.append(f"  {status}  {label:<34} {detail}")


ROOT = meta.load_env()
print("=" * 74)
print("  META ADS AGENT — PREFLIGHT")
print("=" * 74)

# 1. runtime -----------------------------------------------------------------
v = sys.version_info
row(OK if v >= (3, 9) else BAD, "Python 3.9+", f"{v.major}.{v.minor}.{v.micro}")
if v < (3, 9):
    blockers.append("Python 3.9 or newer is required.")

# 2. credentials -------------------------------------------------------------
env_file = ROOT / ".env"
tok = os.getenv("META_ACCESS_TOKEN")
if not env_file.exists():
    row(BAD, ".env file", "missing")
    blockers.append("No Meta token yet — tell Claude: save my token")
elif not tok:
    row(BAD, ".env file", "present, but META_ACCESS_TOKEN is empty")
    blockers.append("No Meta token yet — tell Claude: save my token")
else:
    row(OK, ".env file", f"present ({oct(env_file.stat().st_mode)[-3:]} perms)")

# 3. live API checks (only if we have a token) --------------------------------
accounts = []
if tok:
    try:
        me = meta.whoami()
        row(OK, "Token authenticates", f"{me.get('name')} ({me.get('id')})")
    except Exception as e:
        row(BAD, "Token authenticates", str(e)[:44])
        blockers.append("Meta rejected this token — issue a new one, then tell Claude: save my token")
        tok = None

if tok:
    try:
        d = meta.get("debug_token", None, input_token=meta.token()).get("data", {})
        import datetime
        exp = d.get("expires_at", 0)
        when = "never" if not exp else datetime.datetime.fromtimestamp(exp).strftime("%Y-%m-%d")
        days = None if not exp else (datetime.datetime.fromtimestamp(exp) - datetime.datetime.now()).days
        if days is not None and days < 0:
            row(BAD, "Token not expired", f"EXPIRED {when}")
            blockers.append("Token has expired — issue a new one.")
        elif days is not None and days < 7:
            row(WARN, "Token not expired", f"expires {when} ({days}d left)")
            notes.append(f"Token expires in {days} days — plan to re-issue.")
        else:
            row(OK, "Token not expired", f"expires {when}" + (f" ({days}d)" if days else ""))

        have = set(d.get("scopes", []))
        need = {"ads_read", "ads_management", "business_management",
                "pages_show_list", "pages_read_engagement"}
        missing = need - have
        if missing:
            row(BAD, "Required permissions", f"missing: {', '.join(sorted(missing))}")
            blockers.append(f"Token is missing {', '.join(sorted(missing))} — re-issue with all five ticked.")
        else:
            row(OK, "Required permissions", "all 5 present")
        if "catalog_management" not in have:
            notes.append("No catalog_management scope — catalog discovery will be skipped "
                         "(only needed for Advantage+ shopping / catalog campaigns).")
    except Exception as e:
        row(WARN, "Token introspection", str(e)[:44])

    try:
        accounts = meta.ad_accounts()
        row(OK if accounts else WARN, "Ad accounts reachable", f"{len(accounts)} found")
        if not accounts:
            blockers.append("Token works but reaches 0 ad accounts — check the user has "
                            "access in Business Manager.")
    except Exception as e:
        row(BAD, "Ad accounts reachable", str(e)[:44])
        blockers.append("Could not list ad accounts.")
else:
    for lbl in ("Token not expired", "Required permissions", "Ad accounts reachable"):
        row(SKIP, lbl, "skipped — no token")

# 4. defaults ----------------------------------------------------------------
for key, label in [("META_AD_ACCOUNT_ID", "Default ad account"),
                   ("META_PAGE_ID", "Default Page"),
                   ("META_PIXEL_ID", "Default pixel")]:
    val = os.getenv(key)
    row(OK if val else SKIP, label, val or "not set (optional — a spec can supply it)")

# 4b. is the tool itself out of date? ----------------------------------------
try:
    import subprocess as _sp
    _g = lambda *a: _sp.run(["git", "-C", str(ROOT), *a], capture_output=True,
                            text=True, timeout=20).stdout.strip()
    if (ROOT / ".git").exists():
        _sp.run(["git", "-C", str(ROOT), "fetch", "-q", "origin", "main"],
                capture_output=True, timeout=25)
        _behind = _g("rev-list", "--count", "HEAD..origin/main") or "0"
        if _behind != "0":
            row(WARN, "Tool version", f"{_behind} update(s) available — "
                                      f"say: update the tool")
            notes.append(f"There are {_behind} update(s). Say 'update the tool' to get them.")
        else:
            row(OK, "Tool version", "up to date")
except Exception:
    pass

# 5. workspace ---------------------------------------------------------------
tpl = ROOT / "spec" / "CAMPAIGN-TEMPLATE.xlsx"
row(OK if tpl.exists() else BAD, "Excel template", "spec/CAMPAIGN-TEMPLATE.xlsx" if tpl.exists() else "MISSING")

creatives = [p for p in (ROOT / "creatives").glob("*") if p.is_file() and p.name != ".gitkeep"]
row(OK if creatives else SKIP, "Creatives staged",
    f"{len(creatives)} file(s)" if creatives else "none yet — needed only when building")

specs = [p for p in (ROOT / "specs").glob("*") if p.suffix in (".xlsx", ".json", ".yaml", ".yml")]
row(OK if specs else SKIP, "Campaign specs",
    ", ".join(p.name for p in specs[:3]) if specs else "none yet")

print("\n".join(lines))

# 6. accounts ----------------------------------------------------------------
if accounts:
    S = {1: "ACTIVE", 2: "DISABLED", 3: "UNSETTLED", 7: "PENDING", 8: "CLOSING",
         9: "GRACE", 100: "CLOSED", 101: "ANY_ACTIVE", 201: "ANY_CLOSED"}
    print("\n" + "-" * 74)
    print(f"  AD ACCOUNTS YOU CAN REACH ({len(accounts)})")
    print("-" * 74)
    for a in accounts:
        biz = (a.get("business") or {}).get("name") or "-"
        print(f"  act_{a['account_id']:<19} {(a.get('name') or '')[:30]:<30} "
              f"{S.get(a.get('account_status'), '?'):<10} {a.get('currency', ''):<4} {biz[:20]}")

# 7. verdict -----------------------------------------------------------------
print("\n" + "=" * 74)
if blockers:
    print(f"  BLOCKED — {len(blockers)} thing(s) to fix:\n")
    for b in blockers:
        print(f"    * {b}")
    # A missing/invalid token is the only blocker a new user will normally hit,
    # so print the whole walkthrough here rather than pointing at a doc.
    if any(k in " ".join(blockers) for k in ("No .env", "META_ACCESS_TOKEN", "Token rejected",
                                             "expired", "missing ads", "is missing")):
        print(TOKEN_TUTORIAL)
else:
    print("  READY — everything needed to start is in place.")
    print("\n  What do you want to do?\n")
    print("    1  Create a NEW campaign")
    print("         fill in spec/CAMPAIGN-TEMPLATE.xlsx, then")
    print("         python3 scripts/xlsx_to_spec.py <file>.xlsx --out specs/<name>.json")
    print("         python3 scripts/build_campaign.py --spec specs/<name>.json")
    print()
    print("    2  Add to an EXISTING campaign   (new ads, or a new ad set)")
    print("         python3 scripts/add_to_campaign.py --account act_<id> --list")
    print()
    print("    3  Audit an account              (read-only)")
    print("         python3 scripts/discover.py act_<id>")
    print("         python3 scripts/audit_enhancements.py act_<id>")
for n in notes:
    print(f"\n  note: {n}")
print("=" * 74)
sys.exit(1 if blockers else 0)
