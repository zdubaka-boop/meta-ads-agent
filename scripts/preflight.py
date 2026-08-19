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
  You need a Meta access token. ~5 minutes, one time. Every link you need:

  STEP 1 — Create or open an app
    Your apps:    https://developers.facebook.com/apps
    Create one:   https://developers.facebook.com/apps/create/
    Choose type "Business". An "app" here is just a container for API access -
    it stays in Development mode, is never submitted for review, and is never
    seen by the public.

  STEP 2 — Fill in the Privacy Policy URL
    App settings -> Basic:
      https://developers.facebook.com/apps/  ->  your app  ->  Settings  ->  Basic
    Paste ANY working privacy policy URL and click "Save changes".
    It genuinely does not matter which - the app never goes public and nobody
    reviews it. This field just has to be non-empty before Meta will hand out
    ads permissions. Your company's policy page, or any public one, is fine:
      https://www.iubenda.com/privacy-policy/7787549
    (If you have your own, use it - takes two seconds and is tidier.)

  STEP 3 — Open the Graph API Explorer
    https://developers.facebook.com/tools/explorer/
    Top right: choose your app in the "Meta App" dropdown.

  STEP 4 — Tick all five permissions
    In the "Permissions" box on the left, add each of these:
        ads_read
        ads_management
        business_management
        pages_read_engagement
        pages_show_list
    All five. Miss one and the tools fail later with a confusing error.

  STEP 5 — Generate the token
    Click "Generate Access Token" and approve the Facebook login prompt.
    A long string starting with "EAA..." appears. Copy it.

  STEP 6 — Hand it to this repo
    Run:   bash scripts/setup.sh
    Paste the token when asked. NOTHING APPEARS ON SCREEN as you paste - that
    is deliberate, not a bug. Press Enter. The next four questions are
    optional; press Enter to skip them.

    >>> Do NOT paste the token into the Claude chat window. <<<
    Chat is saved in the transcript. setup.sh keeps it in a local .env only
    you can read. Pasted one by accident? Revoke it here:
      https://www.facebook.com/settings?tab=business_tools

  STEP 7 — Confirm
    Run:   python3 scripts/preflight.py
    Expect READY, plus a list of every ad account you can reach.

  TROUBLESHOOTING
    "0 ad accounts found"
        The token works, but your Facebook user has no ad account access.
        An admin adds you here:
          https://business.facebook.com/settings/people
    Token expires in ~60 days.
        For a team, use a System User token instead - it never expires and
        belongs to the business, not to one person. Same five permissions:
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
    blockers.append("No .env — run: bash scripts/setup.sh")
elif not tok:
    row(BAD, ".env file", "present, but META_ACCESS_TOKEN is empty")
    blockers.append("META_ACCESS_TOKEN is empty — run: bash scripts/setup.sh")
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
        blockers.append("Token rejected by Meta — re-issue it, then rerun setup.sh")
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
    print("\n  Next, pick a job:")
    print("    audit an account      python3 scripts/discover.py act_<id>")
    print("                          python3 scripts/audit_enhancements.py act_<id>")
    print("    build a campaign      fill in spec/CAMPAIGN-TEMPLATE.xlsx, then")
    print("                          python3 scripts/xlsx_to_spec.py <file>.xlsx --out specs/<n>.json")
for n in notes:
    print(f"\n  note: {n}")
print("=" * 74)
sys.exit(1 if blockers else 0)
