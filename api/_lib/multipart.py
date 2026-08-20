"""Minimal multipart/form-data parser.

Python 3.13 removed the cgi module and Vercel's runtime has no third-party
parser available by default, so this reads the handful of parts we need:
one .xlsx plus a set of creative files.
"""
import re


def parse(body: bytes, content_type: str):
    """-> (fields: dict[str,str], files: dict[str,bytes])"""
    m = re.search(r'boundary="?([^";]+)"?', content_type or "")
    if not m:
        raise ValueError("no multipart boundary in Content-Type")
    sep = b"--" + m.group(1).encode()
    fields, files = {}, {}

    for chunk in body.split(sep):
        if not chunk or chunk in (b"--\r\n", b"--", b"\r\n"):
            continue
        if chunk.startswith(b"\r\n"):
            chunk = chunk[2:]
        head, _, data = chunk.partition(b"\r\n\r\n")
        if not _:
            continue
        data = data[:-2] if data.endswith(b"\r\n") else data
        headers = head.decode("utf-8", "replace")
        name = re.search(r'name="([^"]*)"', headers)
        if not name:
            continue
        fname = re.search(r'filename="([^"]*)"', headers)
        if fname and fname.group(1):
            files[fname.group(1)] = data
        else:
            fields[name.group(1)] = data.decode("utf-8", "replace")
    return fields, files
