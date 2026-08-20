"""Minimal read-only .xlsx reader — standard library only.

An .xlsx is a zip of XML. We need cell values from a handful of simple sheets,
so a full library would be overkill and would force the team through a pip
install. Reads shared strings, inline strings, and numbers. Ignores formulas
(returns their cached value if present) and formatting.
"""
import re, zipfile
from xml.etree import ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def _col(ref):
    """'BC12' -> 54 (1-indexed column number)."""
    letters = re.match(r"([A-Z]+)", ref).group(1)
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def sheets(path):
    """Return {sheet_name: [[cell, ...], ...]} with rows padded to equal width."""
    out = {}
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall(f"{NS}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{NS}t")))

        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        target = {r.get("Id"): r.get("Target") for r in rels}

        for sh in wb.find(f"{NS}sheets"):
            name = sh.get("name")
            t = target.get(sh.get(f"{REL}id"), "")
            part = ("xl/" + t.lstrip("/")).replace("xl/xl/", "xl/")
            if part not in z.namelist():
                continue
            rows = []
            sroot = ET.fromstring(z.read(part))
            for row in sroot.iter(f"{NS}row"):
                cells = {}
                for c in row.findall(f"{NS}c"):
                    ref, typ = c.get("r"), c.get("t")
                    v, is_ = c.find(f"{NS}v"), c.find(f"{NS}is")
                    if typ == "s" and v is not None:
                        val = shared[int(v.text)]
                    elif typ == "inlineStr" and is_ is not None:
                        val = "".join(t.text or "" for t in is_.iter(f"{NS}t"))
                    elif v is not None:
                        try:
                            f = float(v.text)
                            val = int(f) if f.is_integer() else f
                        except ValueError:
                            val = v.text
                    else:
                        val = ""
                    cells[_col(ref)] = val
                width = max(cells) if cells else 0
                rows.append([cells.get(i, "") for i in range(1, width + 1)])
            w = max((len(r) for r in rows), default=0)
            out[name] = [r + [""] * (w - len(r)) for r in rows]
    return out


def table(rows, header_row=0):
    """Rows -> list of dicts keyed by the header row. Blank rows dropped."""
    if not rows:
        return []
    head = [str(h).strip() for h in rows[header_row]]
    out = []
    for r in rows[header_row + 1:]:
        if not any(str(x).strip() for x in r):
            continue
        out.append({head[i]: r[i] for i in range(min(len(head), len(r))) if head[i]})
    return out
