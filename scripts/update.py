#!/usr/bin/env python3
"""Pull the latest version of this tool. Safe to run any time.

  python3 scripts/update.py

Your token, your creatives, your spreadsheets and anything you have built are
never touched - they are not part of the tool. If a local edit would collide
with an update, this says so and stops rather than throwing your work away.
"""
import subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def git(*a, check=False):
    return subprocess.run(["git", "-C", str(ROOT), *a],
                          capture_output=True, text=True, check=check)


def main():
    if not (ROOT / ".git").exists():
        sys.exit("This folder is not a git checkout, so there is nothing to update.\n"
                 "Ask whoever set it up to re-clone it.")

    before = git("rev-parse", "--short", "HEAD").stdout.strip()

    print("Checking for updates…")
    f = git("fetch", "origin", "main")
    if f.returncode != 0:
        sys.exit("Could not reach GitHub. Check your internet, then try again.\n"
                 + f.stderr.strip()[:200])

    behind = git("rev-list", "--count", "HEAD..origin/main").stdout.strip() or "0"
    if behind == "0":
        print(f"Already up to date (version {before}). Nothing to do.")
        return

    # Local edits to tool files would be overwritten - stop instead.
    dirty = [l for l in git("status", "--porcelain").stdout.splitlines()
             if l and not l.startswith("??")]
    if dirty:
        print(f"\nThere are {behind} update(s), but you have local changes to the tool:")
        for l in dirty[:10]:
            print("   " + l.strip())
        sys.exit("\nNothing was changed. Those edits would be overwritten.\n"
                 "If you did not make them on purpose, say so and they can be "
                 "discarded before updating.")

    print(f"{behind} update(s) available. What changed:\n")
    for line in git("log", "--oneline", "--no-merges", "HEAD..origin/main"
                    ).stdout.splitlines()[:15]:
        print("   " + line)

    r = git("merge", "--ff-only", "origin/main")
    if r.returncode != 0:
        sys.exit("\nCould not update cleanly:\n" + r.stderr.strip()[:300] +
                 "\n\nNothing was changed. Send this message to whoever maintains it.")

    after = git("rev-parse", "--short", "HEAD").stdout.strip()
    print(f"\nUpdated: {before} -> {after}")

    # A broken update is worse than an old one - prove the tool still works.
    t = subprocess.run([sys.executable, str(ROOT / "scripts" / "selftest.py")],
                       capture_output=True, text=True)
    print(t.stdout.strip().splitlines()[-1] if t.stdout.strip() else "")
    if t.returncode != 0:
        print("\nWARNING: the self-test failed after updating. Tell the maintainer "
              "before building anything.")
        sys.exit(1)
    print("Self-test passed. You are good to go.")


if __name__ == "__main__":
    main()
