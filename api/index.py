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
TTL = 30 * 24 * 3600      # 30 days; only Sign out ends a session
PUBLIC = Path(__file__).resolve().parent.parent / "public"


SIG_LEN = 32          # sha256 HMAC, always exactly 32 bytes


def sign(payload):
    """Sign a session payload.

    The signature is 32 RAW bytes and can contain any byte value, including
    b'.', so it must never be separated from the payload by a delimiter -
    that made roughly one cookie in nine fail its own check. The length is
    fixed, so the split is by position.
    """
    msg = payload.encode() if isinstance(payload, str) else str(payload).encode()
    sig = hmac.new(SECRET.encode(), msg, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(msg + sig).decode().rstrip("=")


def verify(cookie):
    """-> the login code carried by the cookie, or None."""
    if not cookie or not SECRET:
        return None
    try:
        raw = base64.urlsafe_b64decode(cookie + "=" * (-len(cookie) % 4))
        if len(raw) <= SIG_LEN:
            return None
        msg, sig = raw[:-SIG_LEN], raw[-SIG_LEN:]
        good = hmac.new(SECRET.encode(), msg, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, good):
            return None
        exp, code = msg.decode().split("|", 1)
        return code if int(exp) > time.time() else None
    except Exception:
        return None


def unpack_zip(files):
    """A .zip is one drag instead of many. Expand it so a folder can be zipped
    and dropped as a single file, and flatten paths so 'creatives/gold.png'
    still matches a workbook that just says 'gold.png'."""
    import io, zipfile
    out = {}
    for name, blob in files.items():
        if not name.lower().endswith(".zip"):
            out[name] = blob
            continue
        try:
            zf = zipfile.ZipFile(io.BytesIO(blob))
        except zipfile.BadZipFile:
            continue
        for info in zf.infolist():
            if info.is_dir():
                continue
            base = info.filename.rsplit("/", 1)[-1]
            if base.startswith(".") or "__MACOSX" in info.filename:
                continue
            if info.file_size > 12_000_000:
                continue
            out[base] = zf.read(info)
    return out


def _geo_label(targeting):
    """Human label for a targeting block. Worldwide targets carry no
    'countries' key, so this must not assume one."""
    geo = (targeting or {}).get("geo_locations", {}) or {}
    parts = list(geo.get("countries") or [])
    if geo.get("country_groups"):
        parts.append("worldwide")
    if geo.get("cities"):
        parts.append(f"{len(geo['cities'])} city/cities")
    return parts or ["—"]


def insights_by(edge, level, preset):
    """One insights call for a whole level -> {object_id: stats}."""
    out = {}
    key = {"campaign": "campaign_id", "adset": "adset_id", "ad": "ad_id"}[level]
    try:
        # The id field must be requested explicitly, otherwise every row comes
        # back without one and there is nothing to join the stats onto.
        rows = meta.get_all(edge,
            f"{key},spend,impressions,clicks,ctr,cpc,actions,cost_per_action_type",
            limit=200, cap=2000, level=level, date_preset=preset)
    except Exception:
        return out
    for r in rows:
        acts = {a["action_type"]: float(a["value"]) for a in (r.get("actions") or [])}
        cpa_map = {a["action_type"]: float(a["value"])
                   for a in (r.get("cost_per_action_type") or [])}
        pick = lambda m: (m.get("purchase") or m.get("offsite_conversion.fb_pixel_purchase")
                          or m.get("lead") or m.get("link_click"))
        cpa = pick(cpa_map)
        oid = r.get(key)
        if not oid:
            continue
        out[oid] = {"spend": float(r.get("spend") or 0),
                    "impressions": int(r.get("impressions") or 0),
                    "clicks": int(r.get("clicks") or 0),
                    "ctr": round(float(r.get("ctr") or 0), 2),
                    "cpc": round(float(r.get("cpc") or 0), 2),
                    "results": pick(acts) or 0,
                    "cpa": round(cpa, 2) if cpa else None}
    return out


class handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, payload, ctype="application/json", cookie=None, no_cache=False):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        if no_cache:
            self.send_header("Cache-Control", "no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
        if not cookie and getattr(self, "_renew", None):
            exp = int(time.time()) + TTL
            cookie = (f"ms={sign(str(exp) + '|' + self._renew)}; Path=/; HttpOnly; Secure; "
                      f"SameSite=Lax; Max-Age={TTL}")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def _fresh(self):
        self._renew = None

    def _code(self):
        self._fresh()
        m = re.search(r"ms=([A-Za-z0-9_\-]+)", self.headers.get("Cookie", "") or "")
        return verify(m.group(1)) if m else None

    def _need_auth(self):
        """Load this person's own Meta token from the encrypted store.

        A storage blip returns 503, never 401: only a genuinely absent record
        should ever end someone's session.
        """
        code = self._code()
        if not code:
            self._send(401, {"error": "not signed in"})
            return False
        import store
        try:
            rec = store.load(code)
        except store.StoreUnavailable as e:
            self._send(503, {"error": "Storage is briefly unavailable — you are still "
                                      "signed in, try that again in a moment.",
                             "transient": True, "detail": str(e)[:120]})
            return False
        if not rec:
            self._send(401, {"error": "your session is no longer valid — sign in again"})
            return False
        os.environ["META_ACCESS_TOKEN"] = rec["token"]
        self._who = rec.get("who")
        self._renew = code
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
                # The app shell changes on every deploy, and a cached copy makes
                # people think a fix never shipped. Never cache it.
                return self._send(200, (PUBLIC / "index.html").read_bytes(),
                                  "text/html; charset=utf-8",
                                  no_cache=True)
            if p.path == "/api/export":
                if not self._need_auth():
                    return
                return self._export_campaign((parse_qs(p.query).get("campaign") or [""])[0])

            if p.path == "/api/template" and (parse_qs(p.query).get("account") or [None])[0]:
                if not self._need_auth():
                    return
                return self._prefilled_template((parse_qs(p.query)["account"])[0])

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
                who, degraded = None, False
                if code:
                    import store
                    try:
                        rec = store.load(code)
                        who = rec.get("who") if rec else None
                    except store.StoreUnavailable:
                        # Cookie is valid and signed; storage is just slow.
                        who, degraded = "signed in", True
                return self._send(200, {"signed_in": bool(code and who), "mode": "code",
                                        "who": who, "degraded": degraded})
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
                preset = one("preset") or "last_7d"
                stats = insights_by(f"{meta.account(one('account'))}/insights", "campaign", preset)
                for c in camps:
                    c["stats"] = stats.get(c["id"])
                return self._send(200, {"campaigns": camps, "preset": preset,
                                        "has_stats": bool(stats)})

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
                preset = one("preset") or "last_7d"
                stats = insights_by(f"{one('campaign')}/insights", "adset", preset)
                for a in sets_:
                    a["stats"] = stats.get(a["id"])
                return self._send(200, {"adsets": sets_, "preset": preset,
                                        "has_stats": bool(stats)})

            if p.path == "/api/ads":
                if not self._need_auth():
                    return
                ads = meta.get_all(f"{one('adset')}/ads",
                    "id,name,status,effective_status,created_time", cap=500)
                # Merge performance so buyers can judge what to switch off
                # without leaving for Ads Manager.
                preset = one("preset") or "last_7d"
                stats = insights_by(f"{one('adset')}/insights", "ad", preset)
                stats_error = None
                for a in ads:
                    a["stats"] = stats.get(a["id"])
                return self._send(200, {"ads": ads, "preset": preset,
                                        "has_stats": bool(stats),
                                        "stats_error": stats_error})

            return self._send(404, {"error": "no such endpoint"})
        except meta.MetaError as e:
            return self._send(400, {"error": str(e)})
        except Exception as e:
            traceback.print_exc()
            return self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def _export_campaign(self, campaign_id):
        """Write an existing campaign back out as a workbook.

        Copying a winner and changing the copy is how buyers actually work, and
        it is Meta's own export/re-import pattern. Creatives come out as image
        hashes, so the re-upload needs no image files at all.
        """
        import io
        from openpyxl import load_workbook
        from openpyxl.styles import Font

        camp = meta.get(campaign_id, "name,objective,status,daily_budget,lifetime_budget,"
                                     "account_id,special_ad_categories")
        acct = meta.account(camp.get("account_id"))
        cbo = bool(camp.get("daily_budget") or camp.get("lifetime_budget"))
        locales = {v: k for k, v in (meta.load_locales() or {}).items()}

        wb = load_workbook(Path(__file__).parent / "_lib" / "CAMPAIGN-TEMPLATE.xlsx")
        blue = Font(name="Arial", size=10, color="0000FF")
        put = lambda ws, r, c, v: ws.cell(row=r, column=c, value=v).__setattr__("font", blue)

        c = wb["Campaign"]
        for row in range(2, 27):
            c.cell(row=row, column=2).value = None
        put(c, 2, 2, acct)
        put(c, 3, 2, f"{camp.get('name')} (copy)")
        put(c, 4, 2, camp.get("objective"))
        put(c, 6, 2, "CBO" if cbo else "ABO")
        if camp.get("daily_budget"):
            put(c, 7, 2, int(camp["daily_budget"]))
        if camp.get("lifetime_budget"):
            put(c, 8, 2, int(camp["lifetime_budget"]))

        a = wb["Ad Sets"]
        for row in range(2, 12):
            for col in range(1, 30):
                a.cell(row=row, column=col).value = None
        ads_ws = wb["Ads"]
        for row in range(2, 12):
            for col in range(1, 13):
                ads_ws.cell(row=row, column=col).value = None

        page_seen, ar, dr = None, 2, 2
        default_cta = default_link = None
        for aset in meta.get_all(f"{campaign_id}/adsets",
                "id,name,daily_budget,lifetime_budget,optimization_goal,billing_event,"
                "targeting,promoted_object,dsa_beneficiary", cap=200):
            t = aset.get("targeting") or {}
            geo = t.get("geo_locations") or {}
            countries = list(geo.get("countries") or [])
            if geo.get("country_groups"):
                countries = ["worldwide"] + countries
            put(a, ar, 1, aset.get("name"))
            if not cbo and aset.get("daily_budget"):
                put(a, ar, 2, int(aset["daily_budget"]))
            put(a, ar, 4, aset.get("optimization_goal"))
            put(a, ar, 5, aset.get("billing_event"))
            put(a, ar, 8, ",".join(countries))
            excl = ((t.get("excluded_geo_locations") or {}).get("countries") or [])
            if excl:
                put(a, ar, 9, ",".join(excl))
            names = [locales.get(x) for x in (t.get("locales") or []) if locales.get(x)]
            if names:
                put(a, ar, 13, ",".join(names))
            g = t.get("genders") or []
            put(a, ar, 14, "Men" if g == [1] else "Women" if g == [2] else "All")
            put(a, ar, 15, t.get("age_min")); put(a, ar, 16, t.get("age_max"))
            if t.get("publisher_platforms"):
                put(a, ar, 23, ",".join(t["publisher_platforms"]))
            if (aset.get("promoted_object") or {}).get("custom_event_type"):
                put(a, ar, 26, aset["promoted_object"]["custom_event_type"])
            if aset.get("dsa_beneficiary"):
                put(a, ar, 29, aset["dsa_beneficiary"])

            for ad in meta.get_all(f"{aset['id']}/ads",
                    "name,creative{object_story_spec,asset_feed_spec}", cap=500):
                cr = ad.get("creative") or {}
                oss = cr.get("object_story_spec") or {}
                ld = oss.get("link_data") or oss.get("video_data") or {}
                feed = cr.get("asset_feed_spec") or {}
                page_seen = page_seen or oss.get("page_id")
                bodies = [b["text"] for b in feed.get("bodies", [])] or \
                         ([ld.get("message")] if ld.get("message") else [])
                titles = [x["text"] for x in feed.get("titles", [])] or \
                         ([ld.get("name") or ld.get("title")] if (ld.get("name") or ld.get("title")) else [])
                cta = ((ld.get("call_to_action") or {}).get("type"))
                link = ld.get("link") or ((ld.get("call_to_action") or {})
                                          .get("value") or {}).get("link")
                put(ads_ws, dr, 1, aset.get("name"))
                put(ads_ws, dr, 2, ad.get("name"))
                put(ads_ws, dr, 3, ld.get("image_hash") or "")   # hash: no file needed
                put(ads_ws, dr, 4, " | ".join(x for x in bodies if x))
                put(ads_ws, dr, 5, " | ".join(x for x in titles if x))
                put(ads_ws, dr, 6, ld.get("description") or "")
                put(ads_ws, dr, 7, cta); put(ads_ws, dr, 8, link)
                default_cta = default_cta or cta
                default_link = default_link or link
                dr += 1
            ar += 1

        if page_seen:
            put(c, 17, 2, page_seen)
        if default_link:
            put(c, 21, 2, default_link)
        if default_cta:
            put(c, 23, 2, default_cta)

        buf = io.BytesIO(); wb.save(buf); data = buf.getvalue()
        safe = "".join(ch if ch.isalnum() else "-" for ch in (camp.get("name") or "campaign"))[:48]
        self.send_response(200)
        self.send_header("Content-Type",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.send_header("Content-Disposition", f'attachment; filename="{safe}.xlsx"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _prefilled_template(self, acct):
        """Hand back the workbook already filled in for THIS ad account.

        Hunting for account / Page / pixel IDs is the slowest part of filling
        the sheet in, and getting one wrong is the commonest failure. So they
        are written in, and the account's real Pages and pixels are listed on
        their own tab instead of leaving people to guess.
        """
        import io
        from openpyxl import load_workbook
        from openpyxl.styles import Font, PatternFill

        base = Path(__file__).parent / "_lib" / "CAMPAIGN-TEMPLATE.xlsx"
        wb = load_workbook(base)
        blue = Font(name="Arial", size=10, color="0000FF")

        info = meta.get(meta.account(acct), "name,currency,timezone_name")
        assets = meta.account_assets(acct)
        pages = assets.get("pages") if isinstance(assets.get("pages"), list) else []
        pixels = assets.get("pixels") if isinstance(assets.get("pixels"), list) else []
        igs = assets.get("instagram") if isinstance(assets.get("instagram"), list) else []

        c = wb["Campaign"]
        c.cell(row=2, column=2, value=meta.account(acct)).font = blue
        c.cell(row=3, column=2).value = None                      # they name the campaign
        if len(pages) == 1:
            c.cell(row=17, column=2, value=pages[0]["id"]).font = blue
        else:
            c.cell(row=17, column=2).value = None
        c.cell(row=18, column=2).value = igs[0]["id"] if len(igs) == 1 else None
        c.cell(row=19, column=2).value = pixels[0]["id"] if len(pixels) == 1 else None
        for row in (20, 21, 22, 24, 25, 26):                      # clear example copy
            c.cell(row=row, column=2).value = None

        ws = wb.create_sheet("Your account", 1)
        ws.column_dimensions["A"].width = 26
        ws.column_dimensions["B"].width = 30
        ws.column_dimensions["C"].width = 46
        hdr = Font(name="Arial", size=11, bold=True, color="FFFFFF")
        fill = PatternFill("solid", fgColor="1F3864")
        for i, t in enumerate(["What", "ID (copy this)", "Name"], start=1):
            cell = ws.cell(row=1, column=i, value=t); cell.font = hdr; cell.fill = fill
        r = 2
        ws.cell(row=r, column=1, value="Ad account"); ws.cell(row=r, column=2, value=meta.account(acct))
        ws.cell(row=r, column=3, value=f"{info.get('name')}  ({info.get('currency')}, "
                                       f"{info.get('timezone_name')})"); r += 2
        for label, rows_ in (("Page", pages), ("Instagram", igs), ("Pixel", pixels)):
            for x in rows_:
                ws.cell(row=r, column=1, value=label)
                ws.cell(row=r, column=2, value=x["id"])
                ws.cell(row=r, column=3, value=x.get("name") or x.get("username") or "")
                r += 1
            if not rows_:
                ws.cell(row=r, column=1, value=label)
                ws.cell(row=r, column=3, value="(none on this account)"); r += 1
            r += 1
        ws.cell(row=r, column=1, value="Budgets are in CENTS")
        ws.cell(row=r, column=3, value="2000 = 20.00 " + (info.get("currency") or "")); r += 1
        ws.cell(row=r, column=1, value="Already filled in")
        ws.cell(row=r, column=3, value="account_id" +
                (", page_id" if len(pages) == 1 else "") +
                (", pixel_id" if len(pixels) == 1 else ""))

        buf = io.BytesIO(); wb.save(buf); data = buf.getvalue()
        self.send_response(200)
        self.send_header("Content-Type",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.send_header("Content-Disposition",
            f'attachment; filename="CAMPAIGN-{meta.account(acct)}.xlsx"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _add_ads(self, do_create):
        """Add ads into an ad set that already exists."""
        import multipart, builder
        n = int(self.headers.get("Content-Length") or 0)
        if n > 4_300_000:
            return self._send(413, {"error": "Upload is too large (Vercel caps a request at "
                                             "~4.5MB). Send fewer or smaller images."})
        fields, files = multipart.parse(self.rfile.read(n), self.headers.get("Content-Type"))
        files = unpack_zip(files)
        adset_id = (fields.get("adset") or "").strip()
        acct = (fields.get("account") or "").strip()
        if not adset_id or not acct:
            return self._send(400, {"error": "missing ad set or account"})

        book = next(((k, v) for k, v in files.items()
                     if k.lower().endswith((".xlsx", ".xlsm", ".csv"))), None)
        if not book:
            return self._send(400, {"error": "Drop in a .csv or .xlsx listing the new ads."})
        creatives = {k: v for k, v in files.items() if k != book[0]}

        # Defaults come from the ad set's own campaign context where possible.
        defaults = {}
        try:
            pages = meta.get_all(f"{meta.account(acct)}/promote_pages", "id", cap=5)
            if len(pages) == 1:
                defaults["page_id"] = pages[0]["id"]
        except Exception:
            pass

        ads, problems = builder.parse_ads_only(book[1], book[0], creatives, defaults)
        if problems:
            return self._send(200, {"ok": False, "problems": problems})
        if not do_create:
            return self._send(200, {"ok": True, "preview": True,
                                    "ads": [a["name"] for a in ads],
                                    "count": len(ads)})
        log = []
        try:
            res = builder.add_ads_to_adset(acct, adset_id, ads, creatives, defaults, log.append)
        except Exception as e:
            return self._send(400, {"ok": False, "problems": [str(e)], "log": log})
        return self._send(200, {"ok": True, "created": True, **res, "log": log})

    def _workbook(self, do_create):
        """Parse an uploaded workbook + creatives. Preview, or actually build."""
        import multipart, builder
        n = int(self.headers.get("Content-Length") or 0)
        if n > 4_300_000:
            return self._send(413, {"error":
                "Upload is too large. Vercel caps a serverless request at ~4.5MB. "
                "Send fewer or smaller images, or use the CLI for this batch."})
        fields, files = multipart.parse(self.rfile.read(n), self.headers.get("Content-Type"))
        files = unpack_zip(files)   # a dropped .zip is expanded here

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
                                                "countries": _geo_label(a["targeting"]),
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
                           f"SameSite=Lax; Max-Age={TTL}")

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
                           f"SameSite=Lax; Max-Age={TTL}")

            if p.path == "/api/logout":
                return self._send(200, {"ok": True},
                                  cookie="ms=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0")

            if p.path in ("/api/add-preview", "/api/add-create"):
                if not self._need_auth():
                    return
                return self._add_ads(p.path.endswith("create"))

            if p.path in ("/api/preview", "/api/create"):
                if not self._need_auth():
                    return
                return self._workbook(p.path.endswith("create"))

            if p.path == "/api/status":
                if not self._need_auth():
                    return
                b = self._body()
                ids = [str(i) for i in (b.get("ids") or []) if i]
                want = (b.get("status") or "").upper()
                if want not in ("PAUSED", "ACTIVE"):
                    return self._send(400, {"error": "status must be PAUSED or ACTIVE"})
                if not ids:
                    return self._send(400, {"error": "no ads selected"})
                # Turning ads ON spends real money, so it needs its own explicit
                # confirmation. Turning them OFF never does and does not.
                if want == "ACTIVE" and not b.get("confirm_spend"):
                    return self._send(400, {"error": "Activating ads spends money. "
                                                     "confirm_spend must be true."})
                done, failed = [], []
                for i in ids:
                    try:
                        meta.post(i, {"status": want}, "set_status")
                        done.append(i)
                    except Exception as e:
                        failed.append({"id": i, "error": str(e)})
                return self._send(200, {"ok": not failed, "changed": done,
                                        "failed": failed, "status": want})

            if p.path == "/api/rename":
                if not self._need_auth():
                    return
                b = self._body()
                oid, name = str(b.get("id") or ""), (b.get("name") or "").strip()
                if not oid or not name:
                    return self._send(400, {"error": "id and name are required"})
                meta.post(oid, {"name": name}, "rename")
                return self._send(200, {"ok": True, "id": oid, "name": name})

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
