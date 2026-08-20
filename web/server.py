#!/usr/bin/env python3
"""Web UI for the Meta Ads Agent. Standard library only.

  python3 web/server.py                 # http://localhost:8770

It imports scripts/lib/meta.py rather than reimplementing the Graph API, so the
safety rules live in exactly one place and cannot drift between the CLI and the
browser: nothing is ever created ACTIVE, and no budget is ever inferred.

AUTH — two modes, chosen by env:

  META_WEB_MODE=own_token   (default, recommended)
      Each person pastes their own Meta token. It is held in server memory for
      that session only, never written to disk, and dropped on logout.
      Meta's audit log attributes every change to the real person.

  META_WEB_MODE=access_code
      One shared token from .env, unlocked with META_WEB_ACCESS_CODE.
      Convenient, but every action is attributed to the token's owner and one
      leaked code exposes every ad account that token can reach.
"""
import html, json, os, re, secrets, sys, threading, time, traceback
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts"))
import meta  # noqa: E402

meta.load_env()
MODE = os.getenv("META_WEB_MODE", "own_token")
ACCESS_CODE = os.getenv("META_WEB_ACCESS_CODE", "")
PORT = int(os.getenv("META_WEB_PORT", "8770"))

SESSIONS = {}           # sid -> {"token":..., "who":..., "seen": ts}
SESSION_TTL = 8 * 3600
_lock = threading.Lock()


def reap():
    now = time.time()
    with _lock:
        for sid in [s for s, v in SESSIONS.items() if now - v["seen"] > SESSION_TTL]:
            del SESSIONS[sid]


class Api(BaseHTTPRequestHandler):
    server_version = "MetaAdsAgent"

    # ---------------------------------------------------------------- plumbing
    def log_message(self, fmt, *a):
        sys.stderr.write("  %s\n" % (fmt % a))

    def _send(self, code, payload, ctype="application/json", extra=None):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}):
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n))
        except Exception:
            return {}

    def _sid(self):
        m = re.search(r"sid=([A-Za-z0-9_-]+)", self.headers.get("Cookie", "") or "")
        return m.group(1) if m else None

    def _session(self):
        reap()
        sid = self._sid()
        with _lock:
            s = SESSIONS.get(sid)
            if s:
                s["seen"] = time.time()
        return s

    def _auth(self):
        """Returns the session, or sends 401 and returns None."""
        s = self._session()
        if not s:
            self._send(401, {"error": "not signed in"})
            return None
        os.environ["META_ACCESS_TOKEN"] = s["token"]
        return s

    # ---------------------------------------------------------------- routes
    def do_GET(self):
        p = urlparse(self.path)
        if p.path in ("/", "/index.html"):
            f = Path(__file__).parent / "index.html"
            return self._send(200, f.read_bytes(), "text/html; charset=utf-8")
        if p.path == "/api/session":
            s = self._session()
            return self._send(200, {"signed_in": bool(s), "mode": MODE,
                                    "who": (s or {}).get("who")})
        try:
            return self._api_get(p)
        except meta.MetaError as e:
            return self._send(400, {"error": str(e)})
        except Exception as e:
            traceback.print_exc()
            return self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def _api_get(self, p):
        q = parse_qs(p.query)
        one = lambda k: (q.get(k) or [None])[0]

        if p.path == "/api/accounts":
            if not self._auth():
                return
            accounts = meta.ad_accounts()
            S = {1: "ACTIVE", 2: "DISABLED", 3: "UNSETTLED", 7: "PENDING", 9: "GRACE",
                 100: "CLOSED", 101: "ANY_ACTIVE", 201: "ANY_CLOSED"}
            return self._send(200, {"accounts": [{
                "id": f"act_{a['account_id']}", "name": a.get("name") or a["account_id"],
                "status": S.get(a.get("account_status"), "?"), "currency": a.get("currency"),
                "business": (a.get("business") or {}).get("name") or "",
            } for a in accounts]})

        if p.path == "/api/assets":
            if not self._auth():
                return
            acct = one("account")
            info = meta.get(meta.account(acct), "name,currency,timezone_name,min_daily_budget")
            assets = meta.account_assets(acct)
            clean = lambda v: [] if isinstance(v, dict) else v
            return self._send(200, {
                "account": info,
                "pages": clean(assets.get("pages")),
                "instagram": clean(assets.get("instagram")),
                "pixels": clean(assets.get("pixels")),
                "audiences": clean(assets.get("audiences")),
            })

        if p.path == "/api/campaigns":
            if not self._auth():
                return
            import add_to_campaign as atc
            return self._send(200, {"campaigns": atc.list_campaigns(one("account"))})

        if p.path == "/api/adsets":
            if not self._auth():
                return
            import add_to_campaign as atc
            return self._send(200, {"adsets": atc.list_adsets(one("campaign"))})

        if p.path == "/api/ads":
            if not self._auth():
                return
            ads = meta.get_all(f"{one('adset')}/ads",
                               "id,name,status,effective_status,creative{id}", cap=500)
            return self._send(200, {"ads": ads})

        return self._send(404, {"error": "no such endpoint"})

    def do_POST(self):
        p = urlparse(self.path)
        try:
            if p.path == "/api/login":
                return self._login()
            if p.path == "/api/logout":
                sid = self._sid()
                with _lock:
                    SESSIONS.pop(sid, None)
                return self._send(200, {"ok": True})
            if p.path == "/api/audit":
                if not self._auth():
                    return
                b = self._body()
                return self._audit(b.get("account"), b.get("campaign"))
            return self._send(404, {"error": "no such endpoint"})
        except meta.MetaError as e:
            return self._send(400, {"error": str(e)})
        except Exception as e:
            traceback.print_exc()
            return self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def _login(self):
        b = self._body()
        if MODE == "access_code":
            supplied = (b.get("code") or "").strip()
            if not ACCESS_CODE:
                return self._send(500, {"error": "META_WEB_ACCESS_CODE is not set on the server"})
            if not secrets.compare_digest(supplied, ACCESS_CODE):
                time.sleep(1)          # blunt the guessing rate
                return self._send(401, {"error": "wrong access code"})
            token = os.getenv("META_ACCESS_TOKEN", "")
            if not token:
                return self._send(500, {"error": "server has no META_ACCESS_TOKEN in .env"})
        else:
            token = (b.get("token") or "").strip()
            if not token.startswith("EAA"):
                return self._send(400, {"error": "that does not look like a Meta token "
                                                 "(they start with EAA)"})

        os.environ["META_ACCESS_TOKEN"] = token
        try:
            me = meta.whoami()
        except Exception as e:
            return self._send(401, {"error": f"Meta rejected that token: {e}"})

        d = meta.get("debug_token", None, input_token=token).get("data", {})
        have = set(d.get("scopes", []))
        need = {"ads_read", "ads_management", "business_management",
                "pages_show_list", "pages_read_engagement"}
        missing = sorted(need - have)
        if missing:
            return self._send(403, {"error": "token is missing permissions: " + ", ".join(missing),
                                    "missing": missing})

        sid = secrets.token_urlsafe(24)
        with _lock:
            SESSIONS[sid] = {"token": token, "who": me.get("name"), "seen": time.time()}
        exp = d.get("expires_at", 0)
        return self._send(200, {"ok": True, "who": me.get("name"), "expires_at": exp},
                          extra=[("Set-Cookie",
                                  f"sid={sid}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_TTL}")])

    def _audit(self, account, campaign):
        edge = f"{campaign}/ads" if campaign else f"{meta.account(account)}/ads"
        ads = meta.get_all(edge, "id,name,status,effective_status,adset{name},campaign{name},"
                                 "creative{id,degrees_of_freedom_spec}", limit=100, cap=2000)
        rows = []
        for a in ads:
            cfs = ((a.get("creative") or {}).get("degrees_of_freedom_spec") or {}) \
                    .get("creative_features_spec", {}) or {}
            on = sorted(k for k, v in cfs.items() if v.get("enroll_status") == "OPT_IN")
            rows.append({"id": a["id"], "name": a.get("name", ""),
                         "status": a.get("effective_status", ""),
                         "campaign": (a.get("campaign") or {}).get("name", ""),
                         "adset": (a.get("adset") or {}).get("name", ""),
                         "on": on})
        return self._send(200, {"total": len(rows),
                                "flagged": sum(1 for r in rows if r["on"]),
                                "ads": rows})


def main():
    if MODE not in ("own_token", "access_code"):
        sys.exit(f"META_WEB_MODE must be own_token or access_code, got {MODE!r}")
    print("=" * 66)
    print("  META ADS AGENT — web UI")
    print("=" * 66)
    print(f"  http://localhost:{PORT}")
    print(f"  auth mode: {MODE}")
    if MODE == "access_code":
        if not ACCESS_CODE:
            print("  WARNING: META_WEB_ACCESS_CODE is not set — nobody can sign in.")
        print("  NOTE: every action will be attributed to the .env token's owner.")
    else:
        print("  Each person signs in with their own Meta token. Nothing is stored on disk.")
    print("  Read-only browsing + audit. Creating is still done from the CLI.")
    print("=" * 66)
    ThreadingHTTPServer(("127.0.0.1", PORT), Api).serve_forever()


if __name__ == "__main__":
    main()
