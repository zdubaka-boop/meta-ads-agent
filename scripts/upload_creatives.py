#!/usr/bin/env python3
"""Push a folder of creatives into the ad account's media library, once.

Meta stores every image and video ever uploaded to an ad account. Once a
creative is in there, a sheet can reference it BY NAME and no file needs to be
attached again - so campaign after campaign is a single .xlsx, and videos work
(they are far too big to attach).

  python3 scripts/upload_creatives.py act_123 ~/Desktop/creatives
  python3 scripts/upload_creatives.py act_123 ~/Desktop/creatives --dry-run

Already-uploaded names are skipped, so re-running a folder is safe and cheap.
"""
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "lib"))
import meta

meta.load_env()
IMG = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
VID = {".mp4", ".mov", ".m4v"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("account")
    ap.add_argument("folder")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    acct = meta.account(args.account)
    folder = Path(args.folder).expanduser()
    if not folder.is_dir():
        sys.exit(f"Not a folder: {folder}")

    files = sorted(p for p in folder.rglob("*")
                   if p.is_file() and p.suffix.lower() in (IMG | VID)
                   and not p.name.startswith("."))
    if not files:
        sys.exit(f"No images or videos found in {folder}")

    have_img = meta.account_images(acct)
    have_vid = meta.account_videos(acct)

    todo, skip = [], []
    for f in files:
        key = f.name.lower()
        stem = key.rsplit(".", 1)[0]
        if key in have_img or stem in have_img or key in have_vid or stem in have_vid:
            skip.append(f.name)
        else:
            todo.append(f)

    print("=" * 70)
    print(f"UPLOAD CREATIVES  ->  {acct}")
    print(f"  {len(files)} file(s) in {folder}")
    print(f"  {len(skip)} already in the account, {len(todo)} to upload")
    print("=" * 70)
    for f in todo:
        print(f"  + {f.name}")
    for n in skip[:10]:
        print(f"  = {n}  (already there)")
    if len(skip) > 10:
        print(f"  = ... and {len(skip)-10} more already there")
    if not todo:
        print("\nNothing to do — every file is already in the account.")
        return
    if args.dry_run:
        print("\nDRY RUN — nothing uploaded.")
        return

    ok, failed = [], []
    for f in todo:
        try:
            if f.suffix.lower() in VID:
                vid, _ = meta.upload_video(acct, f, f.name)
                ok.append((f.name, vid))
            else:
                ok.append((f.name, meta.upload_image(acct, f, f.name)))
            print(f"  uploaded  {f.name}")
        except Exception as e:
            failed.append((f.name, str(e)[:110]))
            print(f"  FAILED    {f.name}: {str(e)[:110]}")

    print("\n" + "=" * 70)
    print(f"{len(ok)} uploaded, {len(failed)} failed, {len(skip)} already there.")
    if failed:
        print("\nFailed:")
        for n, e in failed:
            print(f"  {n}: {e}")
    print("\nFrom now on the workbook can name these files in creative_file and you")
    print("only need to send the .xlsx — no image files.")


if __name__ == "__main__":
    main()
