#!/usr/bin/env python3
"""Save a Meta token to .env without anyone touching a terminal.

Claude runs this for the user. A native password box appears, they paste the
token into it, and it lands in .env. The token never goes through the chat, so
it never ends up in a saved transcript.

  python3 scripts/save_token.py

Falls back to a normal hidden prompt if no window system is available.
"""
import os, subprocess, sys, urllib.parse, urllib.request, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"


def ask_macos(prompt, hidden=True):
    script = (f'display dialog "{prompt}" default answer "" '
              f'{"with hidden answer " if hidden else ""}'
              f'buttons {{"Cancel","Save"}} default button "Save" '
              f'with title "Meta Ads Agent"')
    try:
        r = subprocess.run(["osascript", "-e", script],
                           capture_output=True, text=True, timeout=600)
    except Exception:
        return None
    if r.returncode != 0:
        return None                      # cancelled
    out = r.stdout.strip()
    if "text returned:" in out:
        return out.split("text returned:", 1)[1].strip()
    return None


def ask_linux(prompt, hidden=True):
    for tool in (["zenity", "--entry", f"--text={prompt}", "--title=Meta Ads Agent"]
                 + (["--hide-text"] if hidden else []),
                 ["kdialog", "--password" if hidden else "--inputbox", prompt]):
        try:
            r = subprocess.run(tool, capture_output=True, text=True, timeout=600)
            if r.returncode == 0:
                return r.stdout.strip()
        except FileNotFoundError:
            continue
    return None


def ask(prompt, hidden=True):
    if sys.platform == "darwin":
        v = ask_macos(prompt, hidden)
    elif sys.platform.startswith("linux") and os.environ.get("DISPLAY"):
        v = ask_linux(prompt, hidden)
    else:
        v = None
    if v is not None:
        return v
    # No window system — fall back to a hidden terminal prompt.
    import getpass
    return (getpass.getpass(prompt + " ") if hidden else input(prompt + " ")).strip()


def check(token):
    """Confirm the token works and has the five permissions, before saving."""
    base = "https://graph.facebook.com/v23.0"
    q = urllib.parse.urlencode({"access_token": token, "fields": "id,name"})
    try:
        me = json.loads(urllib.request.urlopen(f"{base}/me?{q}", timeout=30).read())
    except Exception as e:
        return None, f"Meta rejected that token ({e})."
    q = urllib.parse.urlencode({"input_token": token, "access_token": token})
    try:
        d = json.loads(urllib.request.urlopen(f"{base}/debug_token?{q}",
                                              timeout=30).read()).get("data", {})
    except Exception:
        d = {}
    need = {"ads_read", "ads_management", "business_management",
            "pages_show_list", "pages_read_engagement"}
    missing = sorted(need - set(d.get("scopes", [])))
    if missing:
        return None, ("That token is missing permissions: " + ", ".join(missing)
                      + ".\nGo back to Meta, tick every box, and generate a new one.")
    return me.get("name"), None


def main():
    print("A box will appear on screen. Paste your Meta token into it.")
    print("(Nothing is typed here, and the token never goes through the chat.)\n")
    token = ask("Paste your Meta access token:")
    if not token:
        sys.exit("Cancelled — nothing was saved.")
    token = token.strip()
    if not token.startswith("EAA"):
        sys.exit("That does not look like a Meta token — they start with EAA. "
                 "Nothing was saved.")

    print("Checking it with Meta…")
    who, err = check(token)
    if err:
        sys.exit(err + "\nNothing was saved.")

    lines = []
    if ENV.exists():
        lines = [l for l in ENV.read_text().splitlines()
                 if not l.startswith("META_ACCESS_TOKEN=")]
    lines.insert(0, f"META_ACCESS_TOKEN={token}")
    if not any(l.startswith("META_API_VERSION=") for l in lines):
        lines.append("META_API_VERSION=v23.0")
    old = os.umask(0o077)
    try:
        ENV.write_text("\n".join(lines) + "\n")
    finally:
        os.umask(old)
    ENV.chmod(0o600)

    print(f"\nSaved. Signed in as {who}.")
    print(f"Stored in {ENV} — only you can read it, and it is never committed.")
    print("Run:  python3 scripts/preflight.py")


if __name__ == "__main__":
    main()
