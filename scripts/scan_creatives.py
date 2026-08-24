#!/usr/bin/env python3
"""Look at a folder of creatives and work out how they are organised.

Point this at 200 files and it tells you what the naming convention is and how
they group — so the pairing with copy can be proposed and confirmed, instead of
someone eyeballing 200 rows.

  python3 scripts/scan_creatives.py ~/Desktop/spring-creatives
  python3 scripts/scan_creatives.py ~/Desktop/spring --json

It never guesses silently: it reports what it found, how confident it is, and
what is ambiguous.
"""
import argparse, json, re, sys
from collections import Counter, defaultdict
from pathlib import Path

IMG = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
VID = {".mp4", ".mov", ".m4v"}
SPLIT = re.compile(r"[-_. ]+")

# Tokens that describe the creative rather than identify a group.
ANGLE_WORDS = {"price", "proof", "ugc", "offer", "hook", "testimonial", "demo", "before",
               "after", "review", "discount", "sale", "feature", "benefit", "social",
               "lifestyle", "product", "founder", "problem", "solution"}
RATIO_WORDS = {"1x1", "4x5", "9x16", "16x9", "square", "story", "reel", "feed", "vertical"}


def tokens(name):
    return [t.lower() for t in SPLIT.split(Path(name).stem) if t]


def classify(col):
    """What kind of column is this position in the filename?"""
    vals = [v for v in col if v]
    uniq = set(vals)
    if not uniq:
        return "empty", uniq
    if all(re.fullmatch(r"\d{1,3}", v) for v in uniq):
        return "index", uniq
    if uniq <= RATIO_WORDS:
        return "ratio", uniq
    if uniq & ANGLE_WORDS and len(uniq) <= 12:
        return "angle", uniq
    if all(len(v) == 2 and v.isalpha() for v in uniq) and len(uniq) <= 40:
        return "market", uniq
    if len(uniq) == 1:
        return "constant", uniq
    if len(uniq) <= max(2, len(vals) // 3):
        return "group", uniq
    return "varies", uniq


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = Path(args.folder).expanduser()
    if not root.is_dir():
        sys.exit(f"Not a folder: {root}")

    files = sorted(p for p in root.rglob("*")
                   if p.is_file() and p.suffix.lower() in (IMG | VID)
                   and not p.name.startswith("."))
    if not files:
        sys.exit(f"No images or videos in {root}")

    imgs = [f for f in files if f.suffix.lower() in IMG]
    vids = [f for f in files if f.suffix.lower() in VID]

    # Sub-folders are the strongest signal there is — if someone sorted them,
    # that IS the grouping and no filename guessing is needed.
    by_dir = defaultdict(list)
    for f in files:
        by_dir[str(f.parent.relative_to(root)) or "."].append(f.name)
    foldered = len(by_dir) > 1

    toks = [tokens(f.name) for f in files]
    width = Counter(len(t) for t in toks).most_common(1)[0][0]
    consistent = sum(1 for t in toks if len(t) == width)
    cols = []
    if consistent >= len(files) * 0.6:
        for i in range(width):
            col = [t[i] if i < len(t) else "" for t in toks]
            kind, uniq = classify(col)
            cols.append({"position": i + 1, "kind": kind,
                         "values": sorted(uniq)[:24], "distinct": len(uniq)})

    # Prefer folders; otherwise the first market/group column.
    groups = {}
    basis = None
    if foldered:
        basis = "folders"
        groups = {k: v for k, v in sorted(by_dir.items())}
    else:
        gi = next((c["position"] - 1 for c in cols if c["kind"] in ("market", "group")), None)
        if gi is not None:
            basis = f"part {gi+1} of the filename"
            g = defaultdict(list)
            for f, t in zip(files, toks):
                g[t[gi] if gi < len(t) else "?"].append(f.name)
            groups = dict(sorted(g.items()))

    out = {"folder": str(root), "total": len(files), "images": len(imgs), "videos": len(vids),
           "pattern": [c["kind"] for c in cols] or None,
           "grouped_by": basis, "groups": {k: len(v) for k, v in groups.items()},
           "columns": cols,
           "sample": [f.name for f in files[:6]]}
    if args.json:
        out["group_files"] = groups
        print(json.dumps(out, indent=1, ensure_ascii=False))
        return

    print("=" * 72)
    print(f"  {len(files)} creative(s) in {root}")
    print("=" * 72)
    print(f"  {len(imgs)} image(s), {len(vids)} video(s)")
    print(f"  e.g. {', '.join(f.name for f in files[:4])}")
    if cols:
        print(f"\n  Filenames look like:  " +
              "-".join(f"<{c['kind']}>" for c in cols))
        for c in cols:
            if c["kind"] in ("market", "group", "angle", "ratio"):
                shown = ", ".join(c["values"][:12])
                more = f" … +{c['distinct']-12}" if c["distinct"] > 12 else ""
                print(f"     part {c['position']} ({c['kind']}, {c['distinct']}): {shown}{more}")
    else:
        print("\n  No consistent naming pattern — filenames vary too much to group "
              "automatically.")

    if groups:
        print(f"\n  Grouped by {basis} — {len(groups)} group(s):")
        for k, v in list(groups.items())[:20]:
            print(f"     {k:<24} {len(v):>4} creative(s)")
        if len(groups) > 20:
            print(f"     … and {len(groups)-20} more")
        print("\n  If that grouping is right, each group becomes one ad set.")
    else:
        print("\n  Could not work out a grouping. Either sort them into one folder per "
              "\n  ad set, or say how they should be split.")
    if vids:
        print(f"\n  {len(vids)} video(s) found. Videos must already be in the ad account, "
              f"\n  or be uploaded to it first — they cannot be attached per campaign.")
    print("\n  Nothing was created. This only looked at filenames.")


if __name__ == "__main__":
    main()
