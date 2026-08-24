#!/usr/bin/env python3
"""Offline regression tests for the parsing layer. Touches no API, costs nothing.

Every test here exists because the bug it describes actually shipped. Run it
after changing anything in the reading/parsing path:

  python3 scripts/selftest.py
"""
import csv, io, json, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

PASS, FAIL = "  ok  ", "  FAIL"
results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(f"{PASS if cond else FAIL}  {name}" + (f"   {detail}" if detail and not cond else ""))


def build_sheet(rows_campaign, rows_adsets, rows_ads):
    """Write a throwaway workbook from the real template."""
    from fill_template import _openpyxl
    load_workbook, Font = _openpyxl()
    wb = load_workbook(ROOT / "spec" / "CAMPAIGN-TEMPLATE.xlsx")
    c = wb["Campaign"]
    for r in range(2, 27):
        c.cell(row=r, column=2).value = None
    for r, v in rows_campaign.items():
        c.cell(row=r, column=2, value=v)
    a = wb["Ad Sets"]
    for r in range(2, 40):
        for col in range(1, 30):
            a.cell(row=r, column=col).value = None
    for i, row in enumerate(rows_adsets, start=2):
        for col, v in row.items():
            a.cell(row=i, column=col, value=v)
    ads = wb["Ads"]
    for r in range(2, 60):
        for col in range(1, 13):
            ads.cell(row=r, column=col).value = None
    for i, row in enumerate(rows_ads, start=2):
        for col, v in row.items():
            ads.cell(row=i, column=col, value=v)
    fd, path = tempfile.mkstemp(suffix=".xlsx")
    import os
    os.close(fd)
    wb.save(path)
    return path


def parse(path):
    """Run the real converter and return its spec, or the problems."""
    import subprocess
    out = tempfile.mktemp(suffix=".json")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "xlsx_to_spec.py"),
                        path, "--out", out], capture_output=True, text=True)
    if Path(out).exists():
        return json.loads(Path(out).read_text()), r.stdout
    return None, r.stdout


CAMPAIGN = {2: "act_1", 3: "Selftest", 4: "OUTCOME_TRAFFIC", 6: "CBO", 7: 1000,
            17: "111", 21: "https://example.com/landing", 23: "LEARN_MORE"}
ADSET = [{1: "Set A", 4: "LINK_CLICKS", 5: "IMPRESSIONS", 8: "LT", 15: 18, 16: 65}]

print("=" * 66)
print("  SELF TEST — parsing regressions")
print("=" * 66)

# 1. Pipe-separated copy must become separate variants, never one string.
#    Shipped bug: ads went live reading "Hook one | Hook two | Hook three".
p = build_sheet(CAMPAIGN, ADSET, [{1: "Set A", 2: "ad-1", 3: "a.jpg",
                                   4: "One. | Two. | Three.", 5: "H1 | H2"}])
spec, log = parse(p)
ad = (spec or {}).get("adsets", [{}])[0].get("ads", [{}])[0] if spec else {}
check("pipe-separated bodies split into variants",
      ad.get("bodies") == ["One.", "Two.", "Three."], f"got {ad.get('bodies')}")
check("pipe-separated headlines split into variants",
      ad.get("headlines") == ["H1", "H2"], f"got {ad.get('headlines')}")
check("no literal pipe left in the primary text",
      "|" not in (ad.get("body") or ""), f"got {ad.get('body')!r}")

# 2. Commas inside copy must NOT be treated as separators.
p = build_sheet(CAMPAIGN, ADSET, [{1: "Set A", 2: "ad-1", 3: "a.jpg",
                                   4: "Fast, cheap, and good.", 5: "Buy, now"}])
spec, log = parse(p)
ad = (spec or {}).get("adsets", [{}])[0].get("ads", [{}])[0] if spec else {}
check("commas in copy are kept, not split",
      ad.get("body") == "Fast, cheap, and good." and not ad.get("bodies"),
      f"got {ad.get('body')!r} / {ad.get('bodies')}")

# 3. A real link containing "example.com" must not delete the row.
#    Shipped bug: every ad in a 20-ad sheet vanished, reported as "no ads found".
p = build_sheet(CAMPAIGN, ADSET, [{1: "Set A", 2: "ad-1", 3: "a.jpg",
                                   4: "Body", 5: "Head", 8: "https://example.com/x"}])
spec, log = parse(p)
n = len((spec or {}).get("adsets", [{}])[0].get("ads", [])) if spec else 0
check("an ad linking to example.com survives", n == 1, f"{n} ads parsed")

# 4. Rows below the table (the help notes) must not parse as ad sets.
p = build_sheet(CAMPAIGN,
                ADSET + [{1: "^ delete the grey example rows"}, {1: "countries: ISO codes"}],
                [{1: "Set A", 2: "ad-1", 3: "a.jpg", 4: "B", 5: "H"}])
spec, log = parse(p)
n = len((spec or {}).get("adsets", [])) if spec else 0
check("footer notes are not parsed as ad sets", n == 1, f"{n} ad sets parsed")

# 5. Several creatives in one cell make one ad each.
p = build_sheet(CAMPAIGN, ADSET, [{1: "Set A", 2: "ad", 3: "a.jpg | b.jpg | c.jpg",
                                   4: "B", 5: "H"}])
spec, log = parse(p)
n = len((spec or {}).get("adsets", [{}])[0].get("ads", [])) if spec else 0
check("3 creatives in one cell -> 3 ads", n == 3, f"{n} ads parsed")

# 6. A missing budget under ABO must be an error, never a default.
p = build_sheet({**CAMPAIGN, 6: "ABO", 7: None}, ADSET,
                [{1: "Set A", 2: "ad-1", 3: "a.jpg", 4: "B", 5: "H"}])
spec, log = parse(p)
check("ABO with no ad-set budget is rejected",
      spec is None and "budget" in log.lower(), log.strip()[:70])

# 7. An ad with no primary text must be rejected, not silently built.
p = build_sheet(CAMPAIGN, ADSET, [{1: "Set A", 2: "ad-1", 3: "a.jpg", 5: "H"}])
spec, log = parse(p)
check("an ad with no body is rejected",
      spec is None and "body" in log.lower(), log.strip()[:70])


# --- bulk folder -> workbook -------------------------------------------------
def bulk(folder, copy, extra=()):
    """Run the real bulk builder over a throwaway folder of creatives."""
    import os, subprocess
    d = Path(tempfile.mkdtemp())
    for n in folder:
        (d / n).write_bytes(b"\x89PNG\r\n\x1a\n")
    cj = d / "copy.json"
    cj.write_text(json.dumps(copy))
    out = tempfile.mktemp(suffix=".xlsx")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "bulk_build.py"),
                        "--creatives", str(d), "--copy", str(cj),
                        "--name", "T", "--account", "act_1", "--page", "1",
                        "--link", "https://example.org", "--budget", "10",
                        "--out", out, *extra],
                       capture_output=True, text=True)
    if r.returncode:
        return None, (r.stdout + r.stderr)
    sp = tempfile.mktemp(suffix=".json")
    r2 = subprocess.run([sys.executable, str(ROOT / "scripts" / "xlsx_to_spec.py"),
                         out, "--out", sp], capture_output=True, text=True)
    if r2.returncode:
        return None, (r2.stdout + r2.stderr)
    return json.loads(Path(sp).read_text()), r.stdout


FILES = [f"{m}-{a}.png" for m in ("lt", "pl") for a in ("price", "ugc")]

# 8. A folder of <market>-<angle> files becomes one ad set per market,
#    each targeting that country — the grouping is read, not guessed.
spec, log = bulk(FILES, {"lt": {"bodies": ["L"], "headlines": ["H"]},
                         "pl": {"bodies": ["P"], "headlines": ["H"]}})
got = sorted((spec or {}).get("adsets", []),
             key=lambda x: x["name"])
cc = [a["targeting"]["geo_locations"]["countries"] for a in got]
check("a market-named folder becomes one ad set per country",
      len(got) == 2 and cc == [["LT"], ["PL"]], f"{cc}")

# 9. Angle-specific copy lands on the matching creative, and _default fills
#    the rest. Pairing 200 files by hand is the thing this replaces.
spec, log = bulk(FILES, {"lt": {"price": {"bodies": ["CHEAP"], "headlines": ["H"]},
                                "_default": {"bodies": ["OTHER"], "headlines": ["H"]}},
                         "pl": {"bodies": ["P"], "headlines": ["H"]}})
body = {Path(ad["creative"]).name: ad.get("body")
        for st in (spec or {}).get("adsets", []) for ad in st["ads"]}
check("angle copy pairs with the matching creative",
      body.get("lt-price.png") == "CHEAP" and body.get("lt-ugc.png") == "OTHER",
      str(body))

# 10. Creatives outside the repo must be referenced by full path, or the
#     build looks for them in creatives/ and finds nothing.
import os
paths = [ad["creative"] for st in (spec or {}).get("adsets", []) for ad in st["ads"]]
check("creatives outside the repo keep a resolvable path",
      paths and all(os.path.exists(x) for x in paths),
      f"{len(paths)} path(s), missing: {[x for x in paths if not os.path.exists(x)][:2]}")

# 11. Copy keyed to a group that does not exist is copy the user thinks is
#     live. It used to vanish without a word.
spec, log = bulk(FILES, {"lt": {"bodies": ["L"], "headlines": ["H"]},
                         "pl": {"bodies": ["P"], "headlines": ["H"]},
                         "poland": {"bodies": ["LOST"], "headlines": ["H"]}})
check("copy matching no group is reported", "poland" in log and "NOT used" in log,
      log.strip()[-90:])

# 12. Same for an angle key that matches no filename ('pricing' vs 'price').
spec, log = bulk(FILES, {"lt": {"pricing": {"bodies": ["X"], "headlines": ["H"]},
                                "_default": {"bodies": ["D"], "headlines": ["H"]}},
                         "pl": {"bodies": ["P"], "headlines": ["H"]}})
check("an angle matching no creative is reported",
      "pricing" in log and "matched no creative" in log, log.strip()[-90:])

# 13. fill_template joins long values with a pipe; the reader split only on
#     commas, so any interest or language name over 12 chars came back mangled.
from fill_template import joined
_sep = lambda raw: "|" if "|" in raw else ","
_split = lambda raw: [x.strip() for x in raw.split(_sep(raw)) if x.strip()]
pairs = [["Physical fitness", "Running"], ["LT", "PL"], ["Portuguese (Brazil)", "Spanish"]]
check("long list values survive the sheet's own separator",
      all(_split(joined(v)) == v for v in pairs),
      str([(_split(joined(v)), v) for v in pairs if _split(joined(v)) != v]))

# 14. Re-filling a workbook must drop the previous tail. It cleared a fixed 400
#     rows, so a 500-ad sheet re-filled with 3 kept 497 ads nobody asked for.
def fill(brief, out):
    import subprocess
    Path("/tmp/_st_brief.json").write_text(json.dumps(brief))
    subprocess.run([sys.executable, str(ROOT / "scripts" / "fill_template.py"),
                    "/tmp/_st_brief.json", "--out", out], capture_output=True)
    from fill_template import _openpyxl
    load_workbook, _ = _openpyxl()
    wb = load_workbook(out)
    sh = wb["Ads"]
    return sum(1 for r in range(2, sh.max_row + 1) if sh.cell(r, 2).value)

BIG = {"account_id": "act_1",
       "campaign": {"name": "B", "objective": "OUTCOME_TRAFFIC",
                    "budget_mode": "CBO", "daily_budget_minor": 1000},
       "defaults": {"page_id": "1", "link": "https://example.org", "cta": "LEARN_MORE"},
       "adsets": [{"name": "S", "countries": ["LT"]}],
       "ads": [{"adset": "S", "name": f"ad{i}", "creative": "a.jpg",
                "bodies": ["b"], "headlines": ["h"]} for i in range(500)]}
_out = tempfile.mktemp(suffix=".xlsx")
first = fill(BIG, _out)
second = fill({**BIG, "ads": BIG["ads"][:3]}, _out)
check("re-filling a workbook drops the old rows",
      first == 500 and second == 3, f"{first} then {second}")

# --- Meta rate limiting ------------------------------------------------------
# A whole night was lost to blind backoff on an account whose own response
# headers said exactly how long to wait, and what the real problem was.
import meta as _meta

# 15. The usage header must be read, and pct is the WORST of the three numbers.
_meta.USAGE.update(pct=0, tier=None, regain_at=0.0, waited=0.0, warned=True)
_meta._read_usage({"x-business-use-case-usage":
    '{"221":[{"type":"ads_management","call_count":1,"total_cputime":8,'
    '"total_time":51,"estimated_time_to_regain_access":0,'
    '"ads_api_access_tier":"development_access"}]}'})
check("the rate-limit header is read, worst of the three wins",
      _meta.USAGE["pct"] == 51 and _meta.USAGE["tier"] == "development_access",
      f"pct={_meta.USAGE['pct']} tier={_meta.USAGE['tier']}")

# 16. When Meta says how many minutes, use that instead of guessing.
_meta.USAGE.update(pct=0, regain_at=0.0)
_meta._read_usage({"x-business-use-case-usage":
    '{"a":[{"call_count":100,"total_cputime":100,"total_time":100,'
    '"estimated_time_to_regain_access":3}]}'})
left = _meta.USAGE["regain_at"] - time.time()
check("a stated wait is honoured to the minute", 175 < left < 185, f"{left:.0f}s")

# 17. Pace before the wall, not after hitting it.
import os as _os
_os.environ["META_PACE"] = "1"
_meta.USAGE.update(regain_at=0.0, waited=0.0)
naps = {}
for pct in (10, 75, 85):
    _meta.USAGE["pct"] = pct
    t0 = time.time(); _meta._pace(); naps[pct] = round(time.time() - t0, 1)
check("pacing kicks in as the budget fills",
      naps[10] == 0.0 and 1.3 < naps[75] < 1.8 and 3.7 < naps[85] < 4.4, str(naps))

# 18. It must be possible to turn off.
_os.environ["META_PACE"] = "0"
_meta.USAGE["pct"] = 99
t0 = time.time(); _meta._pace(); off = time.time() - t0
_os.environ["META_PACE"] = "1"
check("META_PACE=0 disables pacing", off < 0.2, f"{off:.2f}s")

# 19. Listing ad sets must not fetch ad counts nobody asked for — that was one
#     paginated /ads call per ad set before a single ad got created.
import inspect, add_to_campaign
src = inspect.getsource(add_to_campaign.list_adsets)
uses = inspect.getsource(add_to_campaign).count("list_adsets(campaign_id, with_counts=False)")
check("the duplicate-name check skips ad counts",
      "with_counts" in src and uses >= 1, f"with_counts in signature={('with_counts' in src)}")

# 20. Turbo Mode printed "turbo mode" while creating ads strictly one at a
#     time. The label was the only thing it changed.
_ui = (ROOT / "web" / "index.html").read_text()
_loop = _ui[_ui.index("const makeAd"):_ui.index("const mine=ads.filter")+4000] \
        if "const makeAd" in _ui else ""
check("turbo actually overlaps ad creation",
      "const lanes = $(\"#turbo\").checked ? 4 : 1" in _ui
      and "await Promise.all(Array.from({length:Math.min(lanes" in _ui,
      "the create loop is sequential again")

# 21. web/ and public/ are served from different places; a fix in one only is
#     a fix nobody sees.
check("the deployed copy matches the source copy",
      _ui == (ROOT / "public" / "index.html").read_text(),
      "web/index.html and public/index.html have diverged")

# --- bulk media upload -------------------------------------------------------
# A 24-ad build spent its time uploading one creative at a time, inside the ad
# loop, re-sending files it had already sent on an earlier run.
import os as _os, time as _time, meta as _m

_d = Path(tempfile.mkdtemp())
(_d / "a.png").write_bytes(b"AAA")
(_d / "b.png").write_bytes(b"BBB")
(_d / "same-bytes.png").write_bytes(b"AAA")
_os.environ["META_MEDIA_CACHE"] = str(_d / "cache.json")
_files = [_d / "a.png", _d / "b.png", _d / "same-bytes.png", _d / "a.png"]

_calls = []
_real_upload, _real_account = _m.upload_image, _m.account
_m.upload_image = lambda acct, path, name=None: (
    _calls.append(Path(path).name), _time.sleep(0.4), "h_" + Path(path).stem)[-1]
_m.account = lambda a=None: "act_test"

_t0 = _time.time(); _got = _m.upload_many("act_test", _files, lanes=4, log=lambda m: None)
_elapsed = _time.time() - _t0

# 20. The same bytes under two names is one upload, not two.
check("identical creatives upload once", len(_calls) == 2 and len(_got) == 2,
      f"{len(_calls)} call(s): {sorted(_calls)}")

# 21. Uploads overlap. Serially this is 0.8s; concurrently about 0.4s.
check("creatives upload concurrently", _elapsed < 0.7, f"{_elapsed:.2f}s — ran serially")

# 22. A creative uploaded on an earlier run is not sent again. This is the only
#     change here that reduces the rate-limit budget rather than just latency.
_calls.clear()
_again = _m.upload_many("act_test", _files, lanes=4, log=lambda m: None)
check("a second run re-uploads nothing", _calls == [] and _again == _got, str(_calls))

# 23. The build loop and the uploader must agree on how a file is keyed, or
#     every creative uploads twice and neither notices.
import build_campaign as _bc
check("build and upload key creatives the same way",
      "meta.file_key(p)" in inspect.getsource(_bc), "build_campaign hashes differently")
_m.upload_image, _m.account = _real_upload, _real_account

# 24. Verification ran one call PER AD, each expanding three nested creative
#     objects. Meta's binding limit is processing time, not call count, so
#     that was the most expensive thing in a build — and it runs every time.
_v = (ROOT / "scripts" / "verify.py").read_text()
_per_adset = 'meta.get_all(\n            f"{aid}/ads"' in _v
check("verification fetches ads per ad set, not per ad", _per_adset,
      "verify.py is back to one call per ad")

print("=" * 66)
bad = results.count(False)
print(f"  {len(results)-bad}/{len(results)} passed" + ("" if not bad else f"   {bad} FAILING"))
sys.exit(1 if bad else 0)
