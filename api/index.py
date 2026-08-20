"""Vercel serverless entrypoint for the Meta Ads Agent console.

Serverless functions are stateless, so there is no in-memory session store.
Instead the cookie carries only an HMAC-signed "you are signed in" flag; the
Meta token stays in the Vercel environment and never reaches the browser.

That means this deployment runs in ACCESS CODE mode only. The own_token mode
(each buyer pastes their own token) stays local-only, because it would require
holding someone else's token in a cookie.

Required env in Vercel:
  META_ACCESS_TOKEN      the Meta token every action runs as
  META_WEB_ACCESS_CODE   the code the team types in
  META_SESSION_SECRET    any long random string; signs the session cookie
"""
import hashlib, hmac, json, os, re, base64, time, traceback, sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).parent / "_lib"))
import meta  # noqa: E402

SECRET = os.getenv("META_SESSION_SECRET", "")
CODE = os.getenv("META_WEB_ACCESS_CODE", "")
TTL = 8 * 3600
PUBLIC = Path(__file__).resolve().parent.parent / "public"


def sign(payload):
    msg = payload.encode() if isinstance(payload, str) else str(payload).encode()
    sig = hmac.new(SECRET.encode(), msg, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(msg + b"." + sig).decode().rstrip("=")


def verify(cookie):
    """-> the login code carried by the cookie, or None."""
    if not cookie or not SECRET:
        return None
    try:
        raw = base64.urlsafe_b64decode(cookie + "=" * (-len(cookie) % 4))
        msg, sig = raw.rsplit(b".", 1)
        good = hmac.new(SECRET.encode(), msg, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, good):
            return None
        exp, code = msg.decode().split("|", 1)
        return code if int(exp) > time.time() else None
    except Exception:
        return None


class handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, payload, ctype="application/json", cookie=None):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def _code(self):
        m = re.search(r"ms=([A-Za-z0-9_\-]+)", self.headers.get("Cookie", "") or "")
        return verify(m.group(1)) if m else None

    def _need_auth(self):
        """Load this person's own Meta token from the encrypted store."""
        code = self._code()
        if not code:
            self._send(401, {"error": "not signed in"})
            return False
        import store
        rec = store.load(code)
        if not rec:
            self._send(401, {"error": "your session is no longer valid — sign in again"})
            return False
        os.environ["META_ACCESS_TOKEN"] = rec["token"]
        self._who = rec.get("who")
        return True

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n)) if n else {}
        except Exception:
            return {}

    # ------------------------------------------------------------------ GET
    def do_GET(self):
        p = urlparse(self.path)
        try:
            if p.path in ("/", "/index.html"):
                return self._send(200, (PUBLIC / "index.html").read_bytes(),
                                  "text/html; charset=utf-8")
            if p.path in ("/api/template", "/CAMPAIGN-TEMPLATE.xlsx"):
                # Read BEFORE sending any header: a read failure after the
                # status line is written kills the whole invocation.
                data = None
                for cand in (Path(__file__).parent / "_lib" / "CAMPAIGN-TEMPLATE.xlsx",
                             PUBLIC / "CAMPAIGN-TEMPLATE.xlsx"):
                    try:
                        data = cand.read_bytes(); break
                    except OSError:
                        continue
                if data is None:
                    return self._send(500, {"error": "template file is missing from the deployment"})
                self.send_response(200)
                self.send_header("Content-Type",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                self.send_header("Content-Disposition",
                    'attachment; filename="CAMPAIGN-TEMPLATE.xlsx"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

            if p.path == "/api/session":
                code = self._code()
                who = None
                if code:
                    import store
                    rec = store.load(code)
                    who = rec.get("who") if rec else None
                return self._send(200, {"signed_in": bool(who), "mode": "code", "who": who})
            q = parse_qs(p.query)
            one = lambda k: (q.get(k) or [None])[0]

            if p.path == "/api/accounts":
                if not self._need_auth():
                    return
                S = {1: "ACTIVE", 2: "DISABLED", 3: "UNSETTLED", 7: "PENDING", 9: "GRACE",
                     100: "CLOSED", 101: "ANY_ACTIVE", 201: "ANY_CLOSED"}
                return self._send(200, {"accounts": [{
                    "id": f"act_{a['account_id']}", "name": a.get("name") or a["account_id"],
                    "status": S.get(a.get("account_status"), "?"),
                    "currency": a.get("currency"),
                    "business": (a.get("business") or {}).get("name") or "",
                } for a in meta.ad_accounts()]})

            if p.path == "/api/campaigns":
                if not self._need_auth():
                    return
                camps = meta.get_all(f"{meta.account(one('account'))}/campaigns",
                    "id,name,objective,status,effective_status,daily_budget,"
                    "lifetime_budget,created_time")
                for c in camps:
                    c["budget_mode"] = "CBO" if (c.get("daily_budget") or c.get("lifetime_budget")) else "ABO"
                camps.sort(key=lambda c: c.get("created_time") or "", reverse=True)
                return self._send(200, {"campaigns": camps})

            if p.path == "/api/adsets":
                if not self._need_auth():
                    return
                sets_ = meta.get_all(f"{one('campaign')}/adsets",
                    "id,name,status,effective_status,daily_budget,lifetime_budget,"
                    "optimization_goal,targeting")
                for a in sets_:
                    geo = (a.get("targeting") or {}).get("geo_locations", {}) or {}
                    a["countries"] = geo.get("countries") or []
                    a.pop("targeting", None)
                    try:
                        a["ad_count"] = len(meta.get_all(f"{a['id']}/ads", "id", cap=500))
                    except Exception:
                        a["ad_count"] = None
                return self._send(200, {"adsets": sets_})

            if p.path == "/api/ads":
                if not self._need_auth():
                    return
                return self._send(200, {"ads": meta.get_all(f"{one('adset')}/ads",
                    "id,name,status,effective_status", cap=500)})

            return self._send(404, {"error": "no such endpoint"})
        except meta.MetaError as e:
            return self._send(400, {"error": str(e)})
        except Exception as e:
            traceback.print_exc()
            return self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def _workbook(self, do_create):
        """Parse an uploaded workbook + creatives. Preview, or actually build."""
        import multipart, builder
        n = int(self.headers.get("Content-Length") or 0)
        if n > 4_300_000:
            return self._send(413, {"error":
                "Upload is too large. Vercel caps a serverless request at ~4.5MB. "
                "Send fewer or smaller images, or use the CLI for this batch."})
        fields, files = multipart.parse(self.rfile.read(n), self.headers.get("Content-Type"))

        book = next(((k, v) for k, v in files.items() if k.lower().endswith((".xlsx", ".xlsm"))), None)
        if not book:
            return self._send(400, {"error": "No .xlsx found. Drop the campaign workbook in too."})
        creatives = {k: v for k, v in files.items() if k is not book[0]
                     and not k.lower().endswith((".xlsx", ".xlsm"))}

        spec, problems, resolved = builder.parse_workbook(book[1], creatives)
        if problems:
            return self._send(200, {"ok": False, "problems": problems, "resolved": resolved})

        counts = {"adsets": len(spec["adsets"]),
                  "ads": sum(len(a["ads"]) for a in spec["adsets"])}
        if not do_create:
            return self._send(200, {"ok": True, "preview": True, "resolved": resolved,
                                    "campaign": spec["campaign"], "counts": counts,
                                    "adsets": [{"name": a["name"],
                                                "countries": a["targeting"]["geo_locations"]["countries"],
                                                "ads": [x["name"] for x in a["ads"]]}
                                               for a in spec["adsets"]]})
        log_lines = []
        try:
            res = builder.build(spec, creatives, log_lines.append)
        except builder.PartialBuild as e:
            return self._send(400, {"ok": False, "problems": [str(e)], "log": log_lines,
                                    "partial": e.result})
        except Exception as e:
            return self._send(400, {"ok": False, "problems": [str(e)], "log": log_lines})
        return self._send(200, {"ok": True, "created": True, "result": res,
                                "log": log_lines, "counts": counts})

    # ----------------------------------------------------------------- POST
    def do_POST(self):
        p = urlparse(self.path)
        try:
            if p.path == "/api/register":
                if not SECRET:
                    return self._send(500, {"error": "META_SESSION_SECRET is not set"})
                import store
                token = (self._body().get("token") or "").strip()
                if not token.startswith("EAA"):
                    return self._send(400, {"error": "That does not look like a Meta token "
                                                     "(they start with EAA)."})
                os.environ["META_ACCESS_TOKEN"] = token
                try:
                    me = meta.whoami()
                except Exception as e:
                    return self._send(401, {"error": f"Meta rejected that token: {e}"})
                d = meta.get("debug_token", None, input_token=token).get("data", {})
                need = {"ads_read", "ads_management", "business_management",
                        "pages_show_list", "pages_read_engagement"}
                missing = sorted(need - set(d.get("scopes", [])))
                if missing:
                    return self._send(403, {"error": "That token is missing permissions: "
                                                     + ", ".join(missing)})
                code = store.new_code()
                store.save(code, token, me.get("name"))
                exp = int(time.time()) + TTL
                return self._send(200, {"ok": True, "code": code, "who": me.get("name"),
                                        "expires_at": d.get("expires_at", 0)},
                    cookie=f"ms={sign(str(exp) + '|' + code)}; Path=/; HttpOnly; Secure; "
                           f"SameSite=Strict; Max-Age={TTL}")

            if p.path == "/api/login":
                if not SECRET:
                    return self._send(500, {"error": "META_SESSION_SECRET is not set"})
                import store
                code = (self._body().get("code") or "").strip().lower()
                rec = store.load(code)
                if not rec:
                    time.sleep(1)
                    return self._send(401, {"error": "No account for that code. "
                                                     "If this is your first time, register instead."})
                exp = int(time.time()) + TTL
                return self._send(200, {"ok": True, "who": rec.get("who")},
                    cookie=f"ms={sign(str(exp) + '|' + code)}; Path=/; HttpOnly; Secure; "
                           f"SameSite=Strict; Max-Age={TTL}")

            if p.path == "/api/logout":
                return self._send(200, {"ok": True},
                                  cookie="ms=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0")

            if p.path in ("/api/preview", "/api/create"):
                if not self._need_auth():
                    return
                return self._workbook(p.path.endswith("create"))

            if p.path == "/api/audit":
                if not self._need_auth():
                    return
                b = self._body()
                edge = (f"{b['campaign']}/ads" if b.get("campaign")
                        else f"{meta.account(b.get('account'))}/ads")
                ads = meta.get_all(edge, "id,name,status,effective_status,adset{name},"
                                         "campaign{name},creative{id,degrees_of_freedom_spec}",
                                   limit=100, cap=1000)
                rows = []
                for a in ads:
                    cfs = ((a.get("creative") or {}).get("degrees_of_freedom_spec") or {}) \
                            .get("creative_features_spec", {}) or {}
                    rows.append({"id": a["id"], "name": a.get("name", ""),
                                 "status": a.get("effective_status", ""),
                                 "campaign": (a.get("campaign") or {}).get("name", ""),
                                 "adset": (a.get("adset") or {}).get("name", ""),
                                 "on": sorted(k for k, v in cfs.items()
                                              if v.get("enroll_status") == "OPT_IN")})
                return self._send(200, {"total": len(rows),
                                        "flagged": sum(1 for r in rows if r["on"]),
                                        "ads": rows})
            return self._send(404, {"error": "no such endpoint"})
        except meta.MetaError as e:
            return self._send(400, {"error": str(e)})
        except Exception as e:
            traceback.print_exc()
            return self._send(500, {"error": f"{type(e).__name__}: {e}"})
