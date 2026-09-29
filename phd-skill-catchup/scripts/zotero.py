#!/usr/bin/env python3
"""Read a Zotero library for the phd-skill-catchup skill (Python 3.8+, standard library only).

Sources (pick one):
  --file PATH      an export from Zotero: BibTeX/BibLaTeX (.bib), RIS (.ris), CSL JSON or
                   Zotero JSON (.json), or CSV (.csv)
  --sqlite [PATH]  the local Zotero database (default: auto-detect ~/Zotero/zotero.sqlite).
                   A temporary copy is read, so Zotero may stay open. Nothing leaves the machine.
  --local          the local API of a running Zotero 7+ desktop app
                   (Settings > Advanced > "Allow other applications on this computer to communicate with Zotero")
  --user-id ID / --group-id ID
                   the Zotero web API. Private libraries need an API key in the ZOTERO_API_KEY
                   environment variable, or as ZOTERO_API_KEY=... in the skill folder's `.config`
                   file (or --api-key). Create one at https://www.zotero.org/settings/keys

Prints a short summary and writes {"source":..., "items":[{title, doi, year, abstract, tags,
venue, authors, date_added, collections}]} to --out. Items are ordered newest-added first.
"""
import argparse
import csv
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

SKIP_TYPES = {"attachment", "note", "annotation"}


def config_value(name):
    """Read NAME=value from the optional `.config` file in the skill folder."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".config")
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip().replace("export ", "") == name:
                    return v.strip().strip("\"'")
    except OSError:
        pass
    return ""


def year_of(s):
    m = re.search(r"(1[89]|20)\d{2}", str(s or ""))
    return int(m.group(0)) if m else None


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def item(title, doi=None, year=None, abstract=None, tags=None, venue=None, authors=None,
         date_added=None, collections=None, item_type=None):
    doi = clean(doi)
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", doi, flags=re.I) or None
    return {"title": clean(title), "doi": doi, "year": year, "abstract": clean(abstract) or None,
            "tags": [clean(t) for t in (tags or []) if clean(t)], "venue": clean(venue) or None,
            "authors": authors or [], "date_added": date_added, "collections": collections or [],
            "item_type": item_type}


# ----------------------------------------------------------------------------- export files

def strip_tex(s):
    s = re.sub(r"\\[a-zA-Z]+\s*\{([^{}]*)\}", r"\1", s or "")
    s = re.sub(r"\\.", "", s)
    return clean(s.replace("{", "").replace("}", ""))


def parse_bibtex(text):
    items = []
    for m in re.finditer(r"@(\w+)\s*\{", text):
        kind = m.group(1).lower()
        if kind in ("comment", "string", "preamble"):
            continue
        depth, i = 1, m.end()
        while i < len(text) and depth:
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        body = text[m.end():i - 1]
        fields, pos = {}, body.find(",") + 1
        fre = re.compile(r"\s*([\w-]+)\s*=\s*")
        while True:
            fm = fre.match(body, pos)
            if not fm:
                break
            j = fm.end()
            if j < len(body) and body[j] == "{":
                d, k = 1, j + 1
                while k < len(body) and d:
                    d += {"{": 1, "}": -1}.get(body[k], 0)
                    k += 1
                val, pos = body[j + 1:k - 1], k
            elif j < len(body) and body[j] == '"':
                k = j + 1
                while k < len(body) and not (body[k] == '"' and body[k - 1] != "\\"):
                    k += 1
                val, pos = body[j + 1:k], k + 1
            else:
                k = body.find(",", j)
                k = len(body) if k < 0 else k
                val, pos = body[j:k], k
            fields[fm.group(1).lower()] = val
            nxt = body.find(",", pos)
            if nxt < 0:
                break
            pos = nxt + 1
        if fields.get("title"):
            items.append(item(
                strip_tex(fields["title"]), fields.get("doi"),
                year_of(fields.get("year") or fields.get("date")), strip_tex(fields.get("abstract", "")),
                [t for t in re.split(r"[;,]", strip_tex(fields.get("keywords", "")))],
                strip_tex(fields.get("journal") or fields.get("journaltitle") or fields.get("booktitle") or ""),
                [strip_tex(a) for a in re.split(r"\s+and\s+", fields.get("author", "")) if a.strip()],
                item_type=kind))
    return items


def parse_ris(text):
    items, cur = [], None
    for line in text.splitlines():
        m = re.match(r"^([A-Z][A-Z0-9])\s\s-\s?(.*)$", line)
        if not m:
            continue
        tag, val = m.group(1), m.group(2).strip()
        if tag == "TY":
            cur = {"kw": [], "au": [], "type": val}
        elif cur is None:
            continue
        elif tag == "ER":
            if cur.get("title"):
                items.append(item(cur["title"], cur.get("doi"), cur.get("year"), cur.get("ab"),
                                  cur["kw"], cur.get("venue"), cur["au"], item_type=cur.get("type")))
            cur = None
        elif tag in ("TI", "T1") and not cur.get("title"):
            cur["title"] = val
        elif tag == "DO":
            cur["doi"] = val
        elif tag in ("AB", "N2") and not cur.get("ab"):
            cur["ab"] = val
        elif tag in ("PY", "Y1", "DA") and not cur.get("year"):
            cur["year"] = year_of(val)
        elif tag == "KW":
            cur["kw"].append(val)
        elif tag in ("AU", "A1"):
            cur["au"].append(val)
        elif tag in ("JO", "JF", "T2") and not cur.get("venue"):
            cur["venue"] = val
    return items


def parse_json(text):
    data = json.loads(text)
    if isinstance(data, dict):
        data = data.get("items") or data.get("references") or [data]
    items = []
    for d in data:
        if not isinstance(d, dict):
            continue
        d = d.get("data", d)  # Zotero API wraps fields in "data"
        if d.get("itemType") in SKIP_TYPES or not d.get("title"):
            continue
        issued = d.get("issued") or {}
        year = None
        if isinstance(issued, dict) and issued.get("date-parts"):
            year = year_of(issued["date-parts"][0][0])
        year = year or year_of(d.get("date") or (issued.get("raw") if isinstance(issued, dict) else issued))
        authors = []
        for a in d.get("author") or d.get("creators") or []:
            if isinstance(a, dict):
                authors.append(clean("%s %s" % (a.get("given") or a.get("firstName") or "",
                                                a.get("family") or a.get("lastName") or a.get("name") or "")))
        tags = d.get("tags") or d.get("keyword") or []
        if isinstance(tags, str):
            tags = re.split(r"[;,]", tags)
        tags = [t.get("tag") if isinstance(t, dict) else t for t in tags]
        venue = d.get("container-title") or d.get("publicationTitle") or d.get("proceedingsTitle")
        items.append(item(d["title"], d.get("DOI") or d.get("doi"), year,
                          d.get("abstract") or d.get("abstractNote"), tags, venue, authors,
                          d.get("dateAdded"), item_type=d.get("type") or d.get("itemType")))
    return items


def parse_csv(text):
    items = []
    for row in csv.DictReader(text.splitlines()):
        low = {(k or "").strip().lower(): v for k, v in row.items()}
        if not low.get("title") or (low.get("item type") or "").lower() in SKIP_TYPES:
            continue
        tags = re.split(r";", (low.get("manual tags") or "") + ";" + (low.get("automatic tags") or ""))
        items.append(item(low["title"], low.get("doi"), year_of(low.get("publication year") or low.get("date")),
                          low.get("abstract note"), tags, low.get("publication title"),
                          [a for a in re.split(r";\s*", low.get("author") or "") if a],
                          low.get("date added"), item_type=low.get("item type")))
    return items


def read_file(path):
    with open(path, "rb") as fh:
        text = fh.read().decode("utf-8-sig", "replace")
    ext = os.path.splitext(path)[1].lower()
    head = text.lstrip()[:200]
    if ext in (".bib", ".bibtex") or head.startswith("@"):
        return parse_bibtex(text)
    if ext == ".ris" or re.match(r"TY\s\s-", head):
        return parse_ris(text)
    if ext == ".json" or head[:1] in "[{":
        return parse_json(text)
    if ext in (".csv", ".tsv"):
        return parse_csv(text)
    raise SystemExit("Unrecognised export format: %s (use .bib, .ris, .json or .csv)" % path)


# ----------------------------------------------------------------------------- local database

def find_sqlite():
    home = os.path.expanduser("~")
    cands = [os.path.join(home, "Zotero", "zotero.sqlite"),
             os.path.join(home, "Documents", "Zotero", "zotero.sqlite"),
             os.path.join(home, "snap", "zotero-snap", "common", "Zotero", "zotero.sqlite"),
             os.path.join(home, ".var", "app", "org.zotero.Zotero", "data", "Zotero", "zotero.sqlite")]
    for c in cands:
        if os.path.exists(c):
            return c
    return None


def read_sqlite(path, collection=None):
    path = path or find_sqlite()
    if not path or not os.path.exists(path):
        raise SystemExit("Zotero database not found. Pass its path: --sqlite /path/to/zotero.sqlite "
                         "(see Zotero > Settings > Advanced > Files and Folders > Data Directory Location).")
    tmpdir = tempfile.mkdtemp(prefix="zotero-copy-")
    try:
        copy = os.path.join(tmpdir, "zotero.sqlite")
        shutil.copy2(path, copy)  # Zotero locks the live database while it is running
        con = sqlite3.connect(copy)
        cur = con.cursor()
        rows = cur.execute(
            "SELECT i.itemID, it.typeName, i.dateAdded FROM items i "
            "JOIN itemTypes it ON i.itemTypeID = it.itemTypeID "
            "WHERE it.typeName NOT IN ('attachment','note','annotation') "
            "AND i.itemID NOT IN (SELECT itemID FROM deletedItems)").fetchall()
        meta = {r[0]: {"type": r[1], "added": r[2]} for r in rows}
        fields = {}
        for iid, name, val in cur.execute(
                "SELECT d.itemID, f.fieldName, v.value FROM itemData d "
                "JOIN fields f ON d.fieldID = f.fieldID "
                "JOIN itemDataValues v ON d.valueID = v.valueID "
                "WHERE f.fieldName IN ('title','abstractNote','DOI','date','publicationTitle',"
                "'proceedingsTitle','bookTitle')"):
            fields.setdefault(iid, {})[name] = val
        tags = {}
        for iid, tag in cur.execute("SELECT it.itemID, t.name FROM itemTags it JOIN tags t ON it.tagID = t.tagID"):
            tags.setdefault(iid, []).append(tag)
        colls = {}
        for iid, name in cur.execute(
                "SELECT ci.itemID, c.collectionName FROM collectionItems ci "
                "JOIN collections c ON ci.collectionID = c.collectionID"):
            colls.setdefault(iid, []).append(name)
        authors = {}
        try:
            for iid, first, last in cur.execute(
                    "SELECT ic.itemID, c.firstName, c.lastName FROM itemCreators ic "
                    "JOIN creators c ON ic.creatorID = c.creatorID ORDER BY ic.itemID, ic.orderIndex"):
                authors.setdefault(iid, []).append(clean("%s %s" % (first or "", last or "")))
        except sqlite3.Error:
            pass
        con.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    items = []
    for iid, m in meta.items():
        f = fields.get(iid, {})
        if not f.get("title"):
            continue
        if collection and not any(collection.lower() in c.lower() for c in colls.get(iid, [])):
            continue
        items.append(item(f["title"], f.get("DOI"), year_of(f.get("date")), f.get("abstractNote"),
                          tags.get(iid), f.get("publicationTitle") or f.get("proceedingsTitle") or f.get("bookTitle"),
                          authors.get(iid), m["added"], colls.get(iid), m["type"]))
    return items


# ----------------------------------------------------------------------------- APIs

def read_api(base, prefix, api_key, limit):
    items, start = [], 0
    while len(items) < limit:
        url = "%s/%s/items/top?%s" % (base, prefix, urllib.parse.urlencode({
            "format": "json", "limit": min(100, limit - len(items)), "start": start,
            "sort": "dateAdded", "direction": "desc"}))
        headers = {"Zotero-API-Version": "3", "User-Agent": "phd-skill-catchup-skill/1.0"}
        if api_key:
            headers["Zotero-API-Key"] = api_key
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as resp:
                batch = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            hint = ""
            if e.code == 403:
                hint = (" - the library is private or the key lacks access. Set ZOTERO_API_KEY "
                        "(create one at https://www.zotero.org/settings/keys with library read access).")
            raise SystemExit("Zotero API error HTTP %d%s" % (e.code, hint))
        except (urllib.error.URLError, OSError) as e:
            raise SystemExit("Could not reach Zotero at %s: %s" % (base, e))
        if not batch:
            break
        items.extend(parse_json(json.dumps(batch)))
        start += len(batch)
        if len(batch) < 100:
            break
    return items


# ----------------------------------------------------------------------------- main

def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--file")
    p.add_argument("--sqlite", nargs="?", const="", default=None)
    p.add_argument("--local", action="store_true")
    p.add_argument("--user-id")
    p.add_argument("--group-id")
    p.add_argument("--api-key", help="prefer the ZOTERO_API_KEY environment variable")
    p.add_argument("--collection", help="only items in collections whose name contains this text (--sqlite only)")
    p.add_argument("--limit", type=int, default=300, help="keep at most this many items, newest-added first")
    p.add_argument("--out", help="write the library JSON here")
    args = p.parse_args()

    key = args.api_key or os.environ.get("ZOTERO_API_KEY") or config_value("ZOTERO_API_KEY")
    if args.file:
        items, source = read_file(args.file), "zotero-export:" + os.path.basename(args.file)
    elif args.sqlite is not None:
        items, source = read_sqlite(args.sqlite or None, args.collection), "zotero-sqlite"
    elif args.local:
        items, source = read_api("http://localhost:23119/api", "users/0", None, args.limit), "zotero-local-api"
    elif args.user_id or args.group_id:
        prefix = "users/" + args.user_id if args.user_id else "groups/" + args.group_id
        items, source = read_api("https://api.zotero.org", prefix, key, args.limit), "zotero-web-api"
    else:
        p.error("choose one of --file, --sqlite, --local, --user-id, --group-id")

    items = [i for i in items if i["title"] and (i.get("item_type") or "") not in SKIP_TYPES]
    items.sort(key=lambda i: i.get("date_added") or "", reverse=True)
    total = len(items)
    items = items[:args.limit]

    print("Zotero source: %s | %d item(s)%s" % (
        source, total, " (kept the %d most recently added)" % len(items) if total > len(items) else ""))
    print("With DOI: %d | with abstract: %d" % (
        sum(1 for i in items if i["doi"]), sum(1 for i in items if i["abstract"])))
    tags = Counter(t for i in items for t in i["tags"])
    if tags:
        print("Top tags: " + "; ".join("%s (%d)" % tc for tc in tags.most_common(25)))
    colls = Counter(c for i in items for c in i["collections"])
    if colls:
        print("Collections: " + "; ".join("%s (%d)" % cc for cc in colls.most_common(25)))
    print("\nMost recently added:")
    for i in items[:30]:
        print("  - %s%s" % (i["title"], " [%s]" % i["year"] if i["year"] else ""))
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump({"source": source, "items": items}, fh, ensure_ascii=False, indent=1)
        print("\nSaved %d item(s) to: %s" % (len(items), args.out))


if __name__ == "__main__":
    main()
