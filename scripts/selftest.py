#!/usr/bin/env python3
"""Offline regression tests for the parsing layer. Touches no API, costs nothing.

Every test here exists because the bug it describes actually shipped. Run it
after changing anything in the reading/parsing path:

  python3 scripts/selftest.py
"""
import csv, io, json, sys, tempfile
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

print("=" * 66)
bad = results.count(False)
print(f"  {len(results)-bad}/{len(results)} passed" + ("" if not bad else f"   {bad} FAILING"))
sys.exit(1 if bad else 0)
