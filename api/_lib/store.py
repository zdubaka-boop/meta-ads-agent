"""Per-user token storage: encrypted at rest, keyed by the user's login code.

The blob store holds only ciphertext. The decryption key is derived from the
user's own login code plus a server-side secret, so neither the store contents
alone nor the server secret alone is enough to read anyone's Meta token.

Layout:  u/<sha256(code + SECRET)[:40]>.bin  ->  Fernet(json{token, who, created})

Losing a code means losing that record — there is no recovery, by design. The
user registers again with a fresh token.
"""
import base64, hashlib, json, os, time, urllib.request, urllib.error, urllib.parse

from cryptography.fernet import Fernet, InvalidToken

BLOB_API = "https://blob.vercel-storage.com"
SECRET = os.getenv("META_SESSION_SECRET", "")


def _bt():
    t = os.getenv("BLOB_READ_WRITE_TOKEN")
    if not t:
        raise RuntimeError("BLOB_READ_WRITE_TOKEN is not set on the server")
    return t


def prefix_for(code):
    """Vercel Blob appends a random suffix to every upload, so the stored
    pathname is u/<hash>-<random>.bin. Look records up by this prefix."""
    h = hashlib.sha256((code + "|" + SECRET).encode()).hexdigest()[:40]
    return f"u/{h}"


def path_for(code):
    return prefix_for(code) + ".bin"


def _key(code):
    raw = hashlib.scrypt((code or "").encode(), salt=SECRET.encode(),
                         n=16384, r=8, p=1, dklen=32)
    return base64.urlsafe_b64encode(raw)


def _req(url, method="GET", data=None, headers=None):
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Authorization", f"Bearer {_bt()}")
    r.add_header("x-api-version", "7")
    for k, v in (headers or {}).items():
        r.add_header(k, v)
    return urllib.request.urlopen(r, timeout=30).read()


def save(code, token, who):
    blob = Fernet(_key(code)).encrypt(json.dumps(
        {"token": token, "who": who, "created": int(time.time())}).encode())
    _req(f"{BLOB_API}/{path_for(code)}", "PUT", blob,
         {"Content-Type": "application/octet-stream"})


class StoreUnavailable(RuntimeError):
    """The store could not be reached. NOT the same as 'no such code' — a
    transient blip must never be reported to the user as a bad session."""


def load(code):
    """-> dict, or None if the code genuinely has no record.

    Raises StoreUnavailable on transport trouble, so callers can keep the
    session alive instead of signing someone out over a dropped packet.
    """
    prefix = prefix_for(code)
    listing = None
    last = None
    for attempt in range(3):
        try:
            listing = json.loads(_req(f"{BLOB_API}/?prefix={urllib.parse.quote(prefix)}&limit=1"))
            break
        except urllib.error.HTTPError as e:
            if e.code in (400, 401, 403, 404):
                return None            # a real "not there"
            last = e
        except Exception as e:
            last = e
        time.sleep(0.4 * (attempt + 1))
    if listing is None:
        raise StoreUnavailable(str(last))

    blobs = listing.get("blobs") or []
    if not blobs:
        return None

    url = blobs[0].get("downloadUrl") or blobs[0].get("url")
    for attempt in range(3):
        try:
            raw = urllib.request.urlopen(url, timeout=30).read()
        except Exception as e:
            last = e
            time.sleep(0.4 * (attempt + 1))
            continue
        try:
            return json.loads(Fernet(_key(code)).decrypt(raw))
        except (InvalidToken, ValueError):
            return None                # wrong code for this record
    raise StoreUnavailable(str(last))


def new_code():
    import secrets, string
    al = string.ascii_lowercase + string.digits
    return "-".join("".join(secrets.choice(al) for _ in range(4)) for _ in range(3))
