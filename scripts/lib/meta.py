"""Meta Marketing API layer with the team's safety rules enforced in code.

Hard guarantees (not conventions — these are unconditional):
  * Every campaign / ad set / ad is created PAUSED. There is no flag to
    create something ACTIVE. Activation happens in Ads Manager, by a human.
  * Object copies are forced to status_option=PAUSED.
  * No budget is ever defaulted, inferred, or scaled. If a spec omits a
    budget, the call fails loudly.
  * Creative enhancements default to fully OPT_OUT.

Credentials come from .env (never from chat, never from argv).
"""

import base64, json, os, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

API_VERSION = os.getenv("META_API_VERSION", "v23.0")
BASE = f"https://graph.facebook.com/{API_VERSION}"

# Every creative feature Meta currently exposes, all OPT_OUT. Meta expands this
# to its full internal list (~82 features) on write; verified by read-back.
ENHANCEMENTS_OFF = {f: {"enroll_status": "OPT_OUT"} for f in [
    "advantage_plus_creative", "creative_stickers", "cv_transformation", "enhance_cta",
    "generate_cta", "image_animation", "image_brightness_and_contrast", "image_templates",
    "image_touchups", "inline_comment", "pac_relaxation", "product_extensions",
    "replace_media_text", "reveal_details_over_time", "show_destination_blurbs",
    "show_summary", "site_extensions", "text_optimizations", "text_translation",
    "video_auto_crop", "video_filtering", "video_uncrop",
]}

DOF_OFF = {"degrees_of_freedom_type": "USER_ENROLLED",
           "creative_features_spec": ENHANCEMENTS_OFF}


class MetaError(RuntimeError):
    def __init__(self, op, err):
        self.op, self.err = op, err
        super().__init__(f"{op}: {err.get('error_user_title') or err.get('message')} "
                         f"(code {err.get('code')}/{err.get('error_subcode')})")


def load_env(root=None):
    """Read .env from the repo root into os.environ. Values are never printed."""
    root = Path(root or Path(__file__).resolve().parents[2])
    f = root / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))
    return root


def token():
    t = os.getenv("META_ACCESS_TOKEN")
    if not t:
        raise RuntimeError("META_ACCESS_TOKEN not set. Run: bash scripts/setup.sh")
    return t


def account(acct=None):
    a = acct or os.getenv("META_AD_ACCOUNT_ID")
    if not a:
        raise RuntimeError("META_AD_ACCOUNT_ID not set. Run: bash scripts/setup.sh")
    return a if str(a).startswith("act_") else f"act_{a}"


def _request(path, params, post, op, retries=4):
    params = dict(params)
    params["access_token"] = token()
    body = urllib.parse.urlencode(params).encode()
    for attempt in range(1, retries + 1):
        try:
            if post:
                req = urllib.request.Request(f"{BASE}/{path}", data=body)
            else:
                req = urllib.request.Request(f"{BASE}/{path}?{body.decode()}")
            return json.loads(urllib.request.urlopen(req, timeout=300).read())
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read()).get("error", {})
            except Exception:
                err = {"message": f"HTTP {e.code}"}
            transient = err.get("is_transient") or e.code in (429, 500, 502, 503, 504)
            if transient and attempt < retries:
                time.sleep(min(60, 5 * 2 ** (attempt - 1)))
                continue
            raise MetaError(op, err)
        except urllib.error.URLError:
            if attempt < retries:
                time.sleep(5 * attempt)
                continue
            raise
    raise MetaError(op, {"message": "retries exhausted"})


def get(path, fields=None, **extra):
    p = dict(extra)
    if fields:
        p["fields"] = fields
    return _request(path, p, post=False, op=f"GET {path}")


def post(path, params, op=None):
    return _request(path, params, post=True, op=op or f"POST {path}")


def get_all(path, fields=None, limit=200, cap=5000, **extra):
    """Follow pagination. Returns a flat list.

    **extra passes through additional query params (level, date_preset, ...);
    without it an insights call raises TypeError and looks like 'no data'.
    """
    out, after = [], None
    while len(out) < cap:
        p = {"limit": limit, **extra}
        if fields:
            p["fields"] = fields
        if after:
            p["after"] = after
        r = _request(path, p, post=False, op=f"GET {path}")
        out.extend(r.get("data", []))
        after = (r.get("paging", {}).get("cursors", {}) or {}).get("after")
        if not after or not r.get("data"):
            break
    return out


# ---------------------------------------------------------------- discovery

def whoami():
    return get("me", "id,name")


def ad_accounts():
    return get_all("me/adaccounts",
                   "account_id,name,account_status,currency,timezone_name,amount_spent,business{id,name}")


def account_assets(acct):
    a = account(acct)
    out = {}
    for key, edge, fields in [
        ("pages", "promote_pages", "id,name"),
        ("instagram", "instagram_accounts", "id,username"),
        ("pixels", "adspixels", "id,name"),
        ("audiences", "customaudiences", "id,name,subtype"),
    ]:
        try:
            out[key] = get_all(f"{a}/{edge}", fields, cap=200)
        except MetaError as e:
            out[key] = {"error": str(e)}

    # Catalogs hang off the BUSINESS, not the ad account — there is no
    # /act_<id>/product_catalogs edge. Resolve the owning business first.
    try:
        biz = (get(a, "business{id,name}").get("business") or {}).get("id")
        out["catalogs"] = get_all(f"{biz}/owned_product_catalogs", "id,name", cap=200) if biz else []
    except MetaError as e:
        out["catalogs"] = {"error": str(e)}
    return out


# ------------------------------------------------------------------ writes
# Every creator below is PAUSED-only by construction.

def create_campaign(acct, name, objective, budget_minor=None, special_ad_categories=None):
    """Create a PAUSED campaign.

    budget_minor: campaign daily budget in MINOR units (cents) for CBO, or
    None for ad-set budgets (ABO). Never defaulted — the caller must decide.
    """
    p = {
        "name": name,
        "objective": objective,
        "status": "PAUSED",
        "special_ad_categories": json.dumps(special_ad_categories or []),
    }
    if budget_minor is None:
        # Meta requires an explicit answer when the campaign holds no budget.
        p["is_adset_budget_sharing_enabled"] = "false"
    else:
        p["daily_budget"] = str(int(budget_minor))
        p["bid_strategy"] = "LOWEST_COST_WITHOUT_CAP"
    return post(f"{account(acct)}/campaigns", p, "create_campaign")["id"]


def create_adset(acct, campaign_id, name, targeting, *, budget_minor=None,
                 lifetime_budget_minor=None, bid_strategy="LOWEST_COST_WITHOUT_CAP",
                 bid_amount_minor=None,
                 optimization_goal="LINK_CLICKS", billing_event="IMPRESSIONS",
                 promoted_object=None, dsa_beneficiary=None, dsa_payor=None,
                 start_time=None, end_time=None):
    """Create a PAUSED ad set. budget_minor is required for ABO, omitted for CBO."""
    p = {
        "name": name,
        "campaign_id": campaign_id,
        "status": "PAUSED",
        "optimization_goal": optimization_goal,
        "billing_event": billing_event,
        "bid_strategy": bid_strategy,
        "targeting": json.dumps(targeting),
    }
    if budget_minor is not None:
        p["daily_budget"] = str(int(budget_minor))
    if lifetime_budget_minor is not None:
        p["lifetime_budget"] = str(int(lifetime_budget_minor))
    if bid_amount_minor is not None:
        p["bid_amount"] = str(int(bid_amount_minor))
    if promoted_object:
        p["promoted_object"] = json.dumps(promoted_object)
    # Required whenever the ad set can reach the EU.
    if dsa_beneficiary:
        p["dsa_beneficiary"] = dsa_beneficiary
        p["dsa_payor"] = dsa_payor or dsa_beneficiary
    if start_time:
        p["start_time"] = start_time
    if end_time:
        p["end_time"] = end_time
    return post(f"{account(acct)}/adsets", p, "create_adset")["id"]


def upload_image(acct, path, name=None):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"image not found: {path}")
    b64 = base64.b64encode(path.read_bytes()).decode()
    r = post(f"{account(acct)}/adimages",
             {"bytes": b64, "name": (name or path.stem)[:90]}, "upload_image")
    if "images" not in r:
        raise MetaError("upload_image", {"message": json.dumps(r)[:300]})
    return list(r["images"].values())[0]["hash"]


def upload_video(acct, path, name=None):
    """Uploads a video and waits for Meta to finish processing.

    Returns (video_id, thumbnail_url). Meta rejects video ad creation until
    processing completes, so this blocks — minutes, for a large file.
    """
    import mimetypes, uuid
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"video not found: {path}")
    boundary = uuid.uuid4().hex
    fields = {"access_token": token(), "name": name or path.name}
    body = b""
    for k, v in fields.items():
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode()
    ctype = mimetypes.guess_type(str(path))[0] or "video/mp4"
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"source\"; "
             f"filename=\"{path.name}\"\r\nContent-Type: {ctype}\r\n\r\n").encode()
    body += path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{BASE}/{account(acct)}/advideos", data=body)
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        vid = json.loads(urllib.request.urlopen(req, timeout=1800).read())["id"]
    except urllib.error.HTTPError as e:
        raise MetaError("upload_video", json.loads(e.read()).get("error", {}))
    return vid, wait_for_video(vid)


def wait_for_video(video_id, max_wait=900):
    waited = 0
    while waited < max_wait:
        time.sleep(10); waited += 10
        d = get(video_id, "status,picture,thumbnails{uri,is_preferred}")
        st = d.get("status", {})
        if st.get("processing_phase", {}).get("status") == "complete" and st.get("video_status") == "ready":
            thumbs = d.get("thumbnails", {}).get("data", [])
            pref = next((t for t in thumbs if t.get("is_preferred")), None)
            return (pref or {}).get("uri") or d.get("picture")
    raise MetaError("wait_for_video", {"message": f"processing timed out after {max_wait}s"})


def image_creative(page_id, image_hash, link, body, headline, description=None,
                   cta="LEARN_MORE", ig_user_id=None, url_tags=None,
                   enhancements_off=True, multi_advertiser_off=True):
    ld = {"link": link, "image_hash": image_hash, "message": body, "name": headline,
          "call_to_action": {"type": cta, "value": {"link": link}}}
    if description:
        ld["description"] = description
    oss = {"page_id": page_id, "link_data": ld}
    if ig_user_id:
        oss["instagram_user_id"] = ig_user_id
    c = {"object_story_spec": oss}
    if enhancements_off:
        c["degrees_of_freedom_spec"] = DOF_OFF
    if multi_advertiser_off:
        # NOTE: Meta does not return this field on read-back. Setting it is
        # best-effort; confirm in Ads Manager. See reference/gotchas.md.
        c["contextual_multi_ads"] = {"enroll_status": "OPT_OUT"}
    if url_tags:
        c["url_tags"] = url_tags
    return c


def video_creative(page_id, video_id, thumbnail_url, link, body, headline,
                   description=None, cta="LEARN_MORE", ig_user_id=None, url_tags=None,
                   enhancements_off=True, multi_advertiser_off=True):
    vd = {"video_id": video_id, "image_url": thumbnail_url, "message": body,
          "title": headline, "call_to_action": {"type": cta, "value": {"link": link}}}
    if description:
        vd["link_description"] = description
    oss = {"page_id": page_id, "video_data": vd}
    if ig_user_id:
        oss["instagram_user_id"] = ig_user_id
    c = {"object_story_spec": oss}
    if enhancements_off:
        c["degrees_of_freedom_spec"] = DOF_OFF
    if multi_advertiser_off:
        c["contextual_multi_ads"] = {"enroll_status": "OPT_OUT"}
    if url_tags:
        c["url_tags"] = url_tags
    return c


def create_ad(acct, adset_id, name, creative, pixel_id=None):
    """Create a PAUSED ad. There is deliberately no way to create it ACTIVE."""
    p = {"name": name, "adset_id": adset_id, "status": "PAUSED",
         "creative": json.dumps(creative)}
    if pixel_id:
        p["tracking_specs"] = json.dumps(
            [{"action.type": ["offsite_conversion"], "fb_pixel": [pixel_id]}])
    return post(f"{account(acct)}/ads", p, "create_ad")["id"]


def copy_object(object_id, kind, **params):
    """Copy a campaign / adset / ad. status_option is forced to PAUSED."""
    params["status_option"] = "PAUSED"
    r = post(f"{object_id}/copies", params, f"copy_{kind}")
    return r.get("copied_campaign_id") or r.get("copied_adset_id") or r.get("copied_ad_id") or r.get("id")


def rename(object_id, name):
    return post(object_id, {"name": name}, "rename")


# ------------------------------------------------------- targeting lookups
# Meta wants numeric IDs for cities, regions, interests and audiences. Buyers
# write names. These resolve names -> IDs and report exactly what matched, so
# a wrong match shows up in the preview rather than silently in a live ad.

def load_locales():
    import json as _j
    p = Path(__file__).resolve().parents[2] / "reference" / "data" / "locales.json"
    return _j.loads(p.read_text()) if p.exists() else {}


def search_geo(query, kind="city"):
    """kind: city | region. Returns the best match dict, or None."""
    r = get("search", None, type="adgeolocation", location_types=json.dumps([kind]),
            q=query, limit=10)
    for row in r.get("data", []):
        if (row.get("name") or "").lower() == query.lower():
            return row
    return (r.get("data") or [None])[0]


def search_interest(query):
    r = get("search", None, type="adinterest", q=query, limit=10)
    for row in r.get("data", []):
        if (row.get("name") or "").lower() == query.lower():
            return row
    return (r.get("data") or [None])[0]


def find_custom_audience(acct, name):
    for a in get_all(f"{account(acct)}/customaudiences", "id,name", cap=1000):
        if (a.get("name") or "").lower() == name.lower():
            return a
    return None


def upload_image_bytes(acct, data, filename, name=None):
    """Upload an image already held in memory (web upload path)."""
    b64 = base64.b64encode(data).decode()
    r = post(f"{account(acct)}/adimages",
             {"bytes": b64, "name": (name or filename)[:90]}, "upload_image")
    if "images" not in r:
        raise MetaError("upload_image", {"message": json.dumps(r)[:300]})
    return list(r["images"].values())[0]["hash"]
