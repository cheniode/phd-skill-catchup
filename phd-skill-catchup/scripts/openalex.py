#!/usr/bin/env python3
"""OpenAlex helper for the phd-skill-catchup skill (Python 3.8+, standard library only).

Subcommands
  author   Load a researcher's publications from an ORCID iD and print an interest digest.
  resolve  Match a list of titles/DOIs (CV, Zotero, PDFs) to OpenAlex works and print a digest.
  digest   Re-print the interest digest of a saved library file.
  subset   Keep only part of a library, e.g. to drop works of other people with the same name.
  recent   Find recent publications for one topic (keyword, semantic, topic-id and/or
           cited-by search).

Every subcommand prints a compact, human-readable report to stdout and, with --out,
saves the full data as JSON. No API key is needed. A free OpenAlex key makes searches
faster. It is looked up in this order: the OPENALEX_API_KEY environment variable, the
--key-file option, a line OPENALEX_API_KEY=... in the `.config` file of the skill folder.
"""
import argparse
import datetime as dt
import difflib
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

BASE = "https://api.openalex.org"
USER_AGENT = "phd-skill-catchup-skill/1.0"
CACHE_DIR = os.path.join(tempfile.gettempdir(), "phd-skill-catchup-cache")
CACHE_TTL = 12 * 3600
MAX_WAIT = 90  # longest throttle (seconds) worth waiting for
WORK_FIELDS = (
    "id,doi,title,publication_date,publication_year,type,language,primary_topic,topics,"
    "keywords,primary_location,authorships,cited_by_count,open_access,"
    "abstract_inverted_index,relevance_score,is_retracted"
)
DEFAULT_TYPES = "article|preprint|review"
ORCID_RE = re.compile(r"(\d{4}-\d{4}-\d{4}-\d{3}[\dXx])")

_budget = {}  # last seen rate-limit headers
_spent = {"requests": 0, "cached": 0, "usd": 0.0, "waited": 0}


class ApiError(Exception):
    pass


# ----------------------------------------------------------------------------- HTTP

_key_file = {"path": None}


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


def api_key():
    """The user's OpenAlex key (optional): environment variable, then --key-file, then the
    `.config` file in the skill folder."""
    if _key_file.get("rejected"):
        return ""
    key = os.environ.get("OPENALEX_API_KEY", "").strip()
    if not key and _key_file["path"]:
        try:
            with open(_key_file["path"], "r", encoding="utf-8-sig") as fh:
                # accept a bare key or a line such as "OpenAlex key: abc123"
                key = fh.read().strip().split()[-1].strip("\"'`<>")
        except (OSError, IndexError):
            print("  (could not read a key from %s; continuing without one)" % _key_file["path"],
                  file=sys.stderr)
            _key_file["path"] = None
    return key or config_value("OPENALEX_API_KEY")


def _cache_path(url):
    return os.path.join(CACHE_DIR, hashlib.sha256(url.encode("utf-8")).hexdigest() + ".json")


def http_get_json(url, headers=None, use_cache=True, retries=5):
    """GET a URL and parse JSON, with an on-disk cache and polite retries."""
    path = _cache_path(url)
    if use_cache and os.path.exists(path) and time.time() - os.path.getmtime(path) < CACHE_TTL:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                _spent["cached"] += 1
                return json.load(fh)
        except (OSError, ValueError):
            pass

    full_url = url
    key = api_key()
    if key and url.startswith(BASE):
        full_url += ("&" if "?" in url else "?") + "api_key=" + urllib.parse.quote(key)
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    hdrs.update(headers or {})

    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(full_url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=60) as resp:
                for h in ("X-RateLimit-Remaining-USD", "X-RateLimit-Limit-USD", "X-RateLimit-Cost-USD"):
                    if resp.headers.get(h) is not None:
                        _budget[h] = resp.headers.get(h)
                try:
                    _spent["usd"] += float(resp.headers.get("X-RateLimit-Cost-USD") or 0)
                except ValueError:
                    pass
                _spent["requests"] += 1
                data = json.loads(resp.read().decode("utf-8"))
            time.sleep(1.1)  # OpenAlex allows roughly one search per second
            if use_cache:
                try:
                    os.makedirs(CACHE_DIR, exist_ok=True)
                    with open(path, "w", encoding="utf-8") as fh:
                        json.dump(data, fh)
                except OSError:
                    pass
            return data
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:500]
            if e.code == 404:
                raise ApiError("404 not found: " + url)
            if e.code == 429:
                # Two different things answer 429: a short throttle (wait and retry) and an
                # exhausted daily allowance (retrying is pointless).
                try:
                    wait = float(e.headers.get("Retry-After") or json.loads(body).get("retryAfter") or 5)
                except (ValueError, AttributeError):
                    wait = 5
                if wait <= MAX_WAIT and attempt < retries - 1:
                    print("  (OpenAlex is throttling; waiting %ds and retrying)" % (wait + 1), file=sys.stderr)
                    time.sleep(wait + 1)
                    _spent["waited"] += int(wait + 1)
                    continue
                raise ApiError(
                    "OpenAlex refused the request (HTTP 429): either the daily allowance is used up "
                    "or searches are throttled for longer than this script waits. A free OpenAlex "
                    "key (https://openalex.org/settings/api) lifts both; see 'Afterwards' in "
                    "SKILL.md for how to offer it to the user. " + body
                )
            if e.code in (401, 403) and full_url != url:
                # a mistyped or expired key should not stop the run
                print("  (OpenAlex did not accept the key; continuing without one)", file=sys.stderr)
                _key_file["rejected"] = True
                full_url = url
                continue
            if e.code in (400, 401, 403):
                raise ApiError("HTTP %d for %s: %s" % (e.code, url, body))
            last_err = "HTTP %d: %s" % (e.code, body)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = str(e)
        time.sleep(1.5 * (attempt + 1))
    raise ApiError("Request failed after %d attempts (%s): %s" % (retries, last_err, url))


def oa_url(path, **params):
    q = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
    return BASE + path + ("?" + q if q else "")


def budget_line():
    parts = ["%d request(s), %d from cache" % (_spent["requests"], _spent["cached"])]
    if _spent["usd"]:
        parts.append("cost $%.4f" % _spent["usd"])
    if "X-RateLimit-Remaining-USD" in _budget:
        parts.append("daily budget left $%s of $%s" % (
            _budget["X-RateLimit-Remaining-USD"], _budget.get("X-RateLimit-Limit-USD", "?")))
    if _key_file.get("rejected"):
        parts.append("the OpenAlex key was NOT accepted (tell the user it may be mistyped or expired); "
                     "ran on the anonymous allowance")
    else:
        parts.append("using the user's OpenAlex key" if api_key() else "no OpenAlex key (anonymous allowance)")
    if _spent["waited"]:
        parts.append("waited %ds for OpenAlex throttling" % _spent["waited"])
    return "OpenAlex usage: " + "; ".join(parts)


# ----------------------------------------------------------------------------- works

def short_id(url):
    return (url or "").rsplit("/", 1)[-1]


def abstract_text(inv):
    if not inv:
        return ""
    pos = []
    for word, idxs in inv.items():
        for i in idxs:
            pos.append((i, word))
    pos.sort()
    return re.sub(r"\s+", " ", " ".join(w for _, w in pos)).strip()


def slim(work):
    """Reduce an OpenAlex work to the fields the agent needs."""
    loc = work.get("primary_location") or {}
    src = loc.get("source") or {}
    auths = work.get("authorships") or []
    names = [(a.get("author") or {}).get("display_name") or a.get("raw_author_name") or "?" for a in auths]
    insts = []
    for a in auths:
        for i in a.get("institutions") or []:
            n = i.get("display_name")
            if n and n not in insts:
                insts.append(n)
    pt = work.get("primary_topic") or {}
    kws = sorted(work.get("keywords") or [], key=lambda k: -(k.get("score") or 0))
    return {
        "id": short_id(work.get("id")),
        "doi": (work.get("doi") or "").replace("https://doi.org/", "") or None,
        "title": re.sub(r"\s+", " ", work.get("title") or "").strip(),
        "date": work.get("publication_date"),
        "year": work.get("publication_year"),
        "type": work.get("type"),
        "language": work.get("language"),
        "venue": src.get("display_name"),
        "authors": names,
        "author_ids": [short_id((a.get("author") or {}).get("id")) for a in auths],
        "institutions": insts[:5],
        "primary_topic": pt.get("display_name"),
        "primary_topic_id": short_id(pt.get("id")) or None,
        "subfield": (pt.get("subfield") or {}).get("display_name"),
        "field": (pt.get("field") or {}).get("display_name"),
        "topics": [{"id": short_id(t.get("id")), "name": t.get("display_name")}
                   for t in (work.get("topics") or [])[:3]],
        "keywords": [k.get("display_name") for k in kws[:6] if (k.get("score") or 0) >= 0.35],
        "cited_by_count": work.get("cited_by_count"),
        "is_oa": (work.get("open_access") or {}).get("is_oa"),
        "oa_url": (work.get("open_access") or {}).get("oa_url"),
        "url": work.get("doi") or loc.get("landing_page_url") or work.get("id"),
        "abstract": abstract_text(work.get("abstract_inverted_index")),
        "relevance_score": work.get("relevance_score"),
    }


def author_str(names, n=3):
    if not names:
        return "unknown authors"
    s = ", ".join(names[:n])
    return s + (" et al. (%d authors)" % len(names) if len(names) > n else "")


def norm_title(t):
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def same_paper(a, b):
    """True when two normalised titles are versions of one paper (preprint, proceedings,
    journal): identical, one is the other plus a subtitle, or near-identical."""
    if a == b:
        return True
    if min(len(a), len(b)) < 25:
        return False
    if a.startswith(b) or b.startswith(a):
        return True
    return abs(len(a) - len(b)) < 15 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.93


def find_same(title, seen):
    for t in seen:
        if same_paper(title, t):
            return t
    return None


def norm_doi(d):
    d = (d or "").strip()
    d = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", d, flags=re.I)
    return d.lower().rstrip(".,;") or None


def paged_works(filter_str, sort=None, max_items=200, search_params=None, use_cache=True,
                select=WORK_FIELDS):
    """Collect works with cursor paging."""
    out, cursor = [], "*"
    while cursor and len(out) < max_items:
        params = {"filter": filter_str, "select": select, "cursor": cursor,
                  "per-page": min(100, max(1, max_items - len(out)))}
        if sort:
            params["sort"] = sort
        params.update(search_params or {})
        data = http_get_json(oa_url("/works", **params), use_cache=use_cache)
        res = data.get("results") or []
        out.extend(res)
        cursor = (data.get("meta") or {}).get("next_cursor")
        if not res:
            break
    return out[:max_items], (data.get("meta") or {}).get("count")


# ----------------------------------------------------------------------------- digest

def print_digest(items, heading):
    """Print the material an agent needs to infer research interests."""
    uniq, seen = [], set()
    for w in items:  # preprint, published and repository copies count once
        nt = norm_title(w.get("title"))
        if find_same(nt, seen) is None:
            seen.add(nt)
            uniq.append(w)
    n_all, items = len(items), uniq
    resolved = [w for w in items if w.get("id")]
    print("=" * 78)
    print(heading)
    print("=" * 78)
    print("Items: %d distinct works (%d records including duplicate versions; %d matched to OpenAlex)"
          % (len(items), n_all, len(resolved)))
    years = Counter(w.get("year") for w in items if w.get("year"))
    if years:
        ys = sorted(years)
        print("Years: %s-%s | by year (recent first): %s" % (
            ys[0], ys[-1], ", ".join("%s:%d" % (y, years[y]) for y in sorted(years, reverse=True)[:8])))

    this_year = dt.date.today().year
    topics, recent_topics, names, kw, fields = Counter(), Counter(), {}, Counter(), Counter()
    for w in resolved:
        for rank, t in enumerate(w.get("topics") or []):
            weight = 1.0 if rank == 0 else 0.5
            topics[t["id"]] += weight
            names[t["id"]] = t["name"]
            if (w.get("year") or 0) >= this_year - 3:
                recent_topics[t["id"]] += weight
        for k in w.get("keywords") or []:
            kw[k] += 1
        if w.get("subfield"):
            fields["%s > %s" % (w.get("field"), w.get("subfield"))] += 1
    for w in items:
        for k in w.get("tags") or []:
            kw[k] += 1

    if fields:
        print("\nFields > subfields:")
        for f, c in fields.most_common(6):
            print("  %3d  %s" % (c, f))
        top = Counter()
        for f, c in fields.items():
            top[f.split(" > ")[0]] += c
        big = len([1 for c in top.values() if c >= 3])
        share = max(top.values()) / float(sum(top.values()))
        if len(top) >= 10 or (big >= 5 and share < 0.5):
            print("  NOTE: these works spread over %d fields and none dominates (largest: %d%%). This is\n"
                  "  either an interdisciplinary researcher or several people with the same name merged\n"
                  "  by OpenAlex. Run `digest --list` to see every work with its institution. If the\n"
                  "  titles do not belong together, ask the user which are theirs and make a cleaned\n"
                  "  library with `subset`." % (len(top), round(share * 100)))
    if topics:
        print("\nOpenAlex topics (weighted count; 'recent' = last 3 years). Topics are coarse -")
        print("use them as hints and as optional --topic-id filters, not as the final interest list:")
        for tid, c in topics.most_common(15):
            print("  %5.1f  (recent %4.1f)  %-8s %s" % (c, recent_topics.get(tid, 0), tid, names[tid]))
    if kw:
        print("\nFrequent keywords/tags: " + "; ".join("%s (%d)" % (k, c) for k, c in kw.most_common(30)))

    def line(w):
        extra = []
        if w.get("year"):
            extra.append(str(w["year"]))
        if w.get("venue"):
            extra.append(w["venue"])
        if w.get("cited_by_count"):
            extra.append("cited %d" % w["cited_by_count"])
        return "  - %s%s" % (w.get("title") or "(untitled)", " [%s]" % "; ".join(extra) if extra else "")

    by_date = sorted(items, key=lambda w: (w.get("date") or str(w.get("year") or ""), w.get("date_added") or ""),
                     reverse=True)
    print("\nMost recent items (weigh these most - they show current interests):")
    for w in by_date[:25]:
        print(line(w))
    cited = sorted(resolved, key=lambda w: -(w.get("cited_by_count") or 0))[:10]
    if cited and len(items) > 25:
        print("\nMost cited items:")
        for w in cited:
            print(line(w))
    if len(items) > 25:
        older = by_date[25:]
        step = max(1, len(older) // 15)
        print("\nSample of older items:")
        for w in older[::step][:15]:
            print(line(w))
    print()


def save(obj, path):
    if not path:
        return
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    print("Saved full data to: " + path)


def load_items(path):
    with open(path, "r", encoding="utf-8-sig") as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        data = data.get("items") or data.get("works") or data.get("results") or []
    items = []
    for it in data:
        if isinstance(it, str):
            it = {"title": it}
        if isinstance(it, dict):
            items.append(it)
    return items


# ----------------------------------------------------------------------------- author

def orcid_public_works(orcid):
    """Fallback: read titles/DOIs from the public ORCID record."""
    data = http_get_json("https://pub.orcid.org/v3.0/%s/works" % orcid,
                         headers={"Accept": "application/json"})
    items = []
    for g in data.get("group") or []:
        summ = (g.get("work-summary") or [{}])[0]
        title = (((summ.get("title") or {}).get("title") or {}).get("value") or "").strip()
        doi = None
        for ext in ((summ.get("external-ids") or {}).get("external-id") or []):
            if (ext.get("external-id-type") or "").lower() == "doi":
                doi = norm_doi(ext.get("external-id-value"))
                break
        year = ((summ.get("publication-date") or {}).get("year") or {}).get("value")
        if title:
            items.append({"title": title, "doi": doi, "year": int(year) if year and year.isdigit() else None})
    return items


def cmd_author(args):
    m = ORCID_RE.search(args.orcid or "")
    if not m:
        raise ApiError("'%s' does not look like an ORCID iD (expected 0000-0000-0000-0000)." % args.orcid)
    orcid = m.group(1).upper()
    # One ORCID can be attached to several OpenAlex author profiles, so list them all
    # and load works by ORCID rather than by a single author id.
    profiles = (http_get_json(oa_url(
        "/authors", filter="orcid:" + orcid, sort="works_count:desc",
        select="id,display_name,orcid,works_count,cited_by_count,last_known_institutions")).get("results") or [])

    if profiles:
        author = profiles[0]
        aids = [short_id(a["id"]) for a in profiles]
        works, total = paged_works("author.orcid:" + orcid, sort="publication_date:desc",
                                   max_items=args.max_works)
        items = [slim(w) for w in works]
        insts = ", ".join(i.get("display_name", "") for i in (author.get("last_known_institutions") or [])[:3])
        print("Author: %s | ORCID %s | OpenAlex author id(s): %s" % (
            author.get("display_name"), orcid, " ".join(aids)))
        print("Affiliation (last known): %s" % (insts or "unknown"))
        print("Works in OpenAlex: %s (loaded %d, newest first) | citations: %s" % (
            total, len(items), sum(a.get("cited_by_count") or 0 for a in profiles)))
        print("CONFIRM with the user that this is them before continuing.\n")
        if not items:
            print("OpenAlex lists no works for this author; trying the public ORCID record...")
        else:
            print_digest(items, "Publication digest for %s" % author.get("display_name"))
            save({"source": "openalex-author", "orcid": orcid, "author_ids": aids,
                  "author_name": author.get("display_name"), "items": items}, args.out)
            return
    else:
        print("No OpenAlex author is linked to ORCID %s; trying the public ORCID record..." % orcid)

    raw = orcid_public_works(orcid)
    if not raw:
        raise ApiError("No public works found for ORCID %s in OpenAlex or ORCID. Ask the user for "
                       "another source (Zotero, CV list, PDF folder)." % orcid)
    items = resolve_items(raw, args.max_title_lookups)
    print_digest(items, "Publication digest from ORCID record %s" % orcid)
    save({"source": "orcid-public", "orcid": orcid, "items": items}, args.out)


# ----------------------------------------------------------------------------- resolve

def resolve_items(raw, max_title_lookups=25):
    """Enrich {title, doi, ...} items with OpenAlex metadata. DOIs are cheap (batched);
    title lookups cost more, so they are capped."""
    out = [dict(it) for it in raw]
    by_doi = {}
    for it in out:
        it["doi"] = norm_doi(it.get("doi"))
        if it["doi"]:
            by_doi.setdefault(it["doi"], []).append(it)

    dois = list(by_doi)
    for i in range(0, len(dois), 40):
        chunk = [d for d in dois[i:i + 40] if "," not in d and "|" not in d]
        if not chunk:
            continue
        try:
            data = http_get_json(oa_url("/works", filter="doi:" + "|".join(chunk),
                                        select=WORK_FIELDS, **{"per-page": 100}))
        except ApiError as e:
            print("  (DOI batch lookup failed: %s)" % e, file=sys.stderr)
            continue
        for w in data.get("results") or []:
            s = slim(w)
            for it in by_doi.get((s.get("doi") or "").lower(), []):
                merge_resolved(it, s)

    lookups = 0
    pending = [it for it in out if not it.get("id") and len(norm_title(it.get("title"))) >= 12]
    for it in pending:
        if lookups >= max_title_lookups:
            break
        lookups += 1
        q = re.sub(r"[^\w\s-]", " ", it["title"], flags=re.UNICODE)
        q = re.sub(r"\s+", " ", q).strip()
        try:
            data = http_get_json(oa_url("/works", filter="title.search:" + q,
                                        select=WORK_FIELDS, **{"per-page": 5}))
        except ApiError as e:
            if "429" in str(e):
                print("  (stopping title lookups: %s)" % e, file=sys.stderr)
                break
            continue
        best, best_r = None, 0.0
        for w in data.get("results") or []:
            r = difflib.SequenceMatcher(None, norm_title(w.get("title")), norm_title(it["title"])).ratio()
            if r > best_r:
                best, best_r = w, r
        if best is not None and best_r >= 0.88:
            merge_resolved(it, slim(best))
    skipped = len(pending) - lookups
    if skipped > 0:
        print("Note: %d item(s) without DOI were not looked up (cap --max-title-lookups=%d); "
              "their titles are still used for the digest." % (skipped, max_title_lookups))
    return out


def merge_resolved(item, s):
    keep = {k: v for k, v in item.items() if v not in (None, "", [])}
    item.update(s)
    for k in ("tags", "date_added", "file", "collections"):
        if k in keep:
            item[k] = keep[k]
    if not item.get("abstract") and keep.get("abstract"):
        item["abstract"] = keep["abstract"]


def cmd_resolve(args):
    raw = load_items(args.input)
    if not raw:
        raise ApiError("No items found in " + args.input)
    if args.max_items and len(raw) > args.max_items:
        print("Input has %d items; using the first %d (--max-items)." % (len(raw), args.max_items))
        raw = raw[:args.max_items]
    items = resolve_items(raw, args.max_title_lookups)
    print_digest(items, "Library digest (%s)" % os.path.basename(args.input))
    save({"source": "resolved", "items": items}, args.out)


def cmd_subset(args):
    """Keep only part of a library, e.g. to drop works of namesakes."""
    with open(args.input, "r", encoding="utf-8-sig") as fh:
        data = json.load(fh)
    meta = data if isinstance(data, dict) else {}
    items = load_items(args.input)
    keep_rx = re.compile(args.keep_title, re.I) if args.keep_title else None
    drop_rx = re.compile(args.drop_title, re.I) if args.drop_title else None
    keep_ids = set(x for v in (args.keep_id or []) for x in re.split(r"[,\s]+", v) if x)
    drop_ids = set(x for v in (args.drop_id or []) for x in re.split(r"[,\s]+", v) if x)
    fields = [f.lower() for f in (args.keep_field or [])]
    out = []
    for w in items:
        title, wid = w.get("title") or "", w.get("id")
        where = ("%s > %s" % (w.get("field"), w.get("subfield"))).lower()
        if wid in drop_ids or (drop_rx and drop_rx.search(title)):
            continue
        selected = not (keep_rx or keep_ids or fields)
        if (wid in keep_ids or (keep_rx and keep_rx.search(title))
                or any(f in where for f in fields)):
            selected = True
        if selected:
            out.append(w)
    print("Kept %d of %d items." % (len(out), len(items)))
    for w in items:
        if w not in out:
            print("  dropped: %s [%s]" % ((w.get("title") or "")[:100], w.get("subfield") or "-"))
    print()
    meta = dict(meta)
    meta["items"] = out
    print_digest(out, "Digest of the cleaned library")
    save(meta, args.out)


def cmd_digest(args):
    items = load_items(args.input)
    if args.list:
        print("id | year | subfield | institutions | first authors | title")
        for w in sorted(items, key=lambda w: (w.get("subfield") or "", -(w.get("year") or 0))):
            print(" | ".join([w.get("id") or "-", str(w.get("year") or "-"), (w.get("subfield") or "-")[:30],
                              "; ".join((w.get("institutions") or [])[:2])[:60] or "-",
                              ", ".join((w.get("authors") or [])[:3])[:60], (w.get("title") or "")[:110]]))
        return
    print_digest(items, "Library digest (%s)" % os.path.basename(args.input))


# ----------------------------------------------------------------------------- recent

def clean_query(q):
    # commas separate filters and pipes mean OR in OpenAlex filter syntax
    return re.sub(r"\s+", " ", q.replace(",", " ").replace("|", " ")).strip()


def cmd_recent(args):
    today = dt.date.today()
    to_date = dt.date.fromisoformat(args.to_date) if args.to_date else today
    from_date = dt.date.fromisoformat(args.from_date) if args.from_date else to_date - dt.timedelta(days=args.days)
    if from_date > to_date:
        raise ApiError("--from date is after --to date")
    if not (args.query or args.semantic or args.topic_id or args.citing):
        raise ApiError("Give at least one --query, --semantic, --topic-id or --citing")

    base = ["from_publication_date:%s" % from_date, "to_publication_date:%s" % to_date, "is_retracted:false"]
    if args.types and args.types != "any":
        base.append("type:" + args.types)
    if args.language:
        base.append("language:" + args.language)
    topic_filter = None
    if args.topic_id:
        topic_filter = "topics.id:" + "|".join(short_id(t) for t in args.topic_id)
    sort = {"relevance": None, "date": "publication_date:desc", "cited": "cited_by_count:desc"}[args.sort]

    found, order, stats, failed = {}, [], [], []

    def add(works, label):
        n_new = 0
        for w in works:
            s = slim(w)
            if not s["title"] or not s["date"]:
                continue
            if not (str(from_date) <= s["date"] <= str(to_date)):
                continue
            if s["id"] not in found:
                s["matched"] = []
                found[s["id"]] = s
                order.append(s["id"])
                n_new += 1
            found[s["id"]]["matched"].append(label)
        return n_new

    for q in args.query or []:
        cq = clean_query(q)
        if len(re.findall(r"\b(AND|OR|NOT)\b", cq)) > 5:
            print("  note: query [%s] has more than 5 AND/OR/NOT operators; OpenAlex slows such "
                  "queries down. Two shorter queries usually find more." % q[:60])
        f = base + ["title_and_abstract.search:" + cq] + ([topic_filter] if topic_filter else [])
        try:
            works, total = paged_works(",".join(f), sort=sort, max_items=args.per_query)
            stats.append((q, total, add(works, q)))
        except ApiError as e:  # keep what the other searches found
            failed.append((q, str(e)[:300]))

    for path in args.citing or []:
        lib = [it for it in load_items(path) if re.match(r"^W\d+$", it.get("id") or "")]
        ids = [it["id"] for it in lib]
        titles = {it["id"]: it.get("title") or it["id"] for it in lib}
        if not ids:
            failed.append(("citing " + path, "no OpenAlex work ids in this file; run `resolve` on it first"))
            continue
        label, total_all, n_all = "cites a library item", 0, 0
        try:
            for i in range(0, len(ids), 50):
                f = base + ["cites:" + "|".join(ids[i:i + 50])] + ([topic_filter] if topic_filter else [])
                works, total = paged_works(",".join(f), sort=sort or "publication_date:desc",
                                           max_items=max(args.per_query, 200),
                                           select=WORK_FIELDS + ",referenced_works")
                total_all += total or 0
                n_all += add(works, label)
                for w in works:
                    s = found.get(short_id(w.get("id")))
                    if s is not None:
                        cited = [titles[short_id(r)] for r in (w.get("referenced_works") or [])
                                 if short_id(r) in titles]
                        s["cites_user_works"] = sorted(set(s.get("cites_user_works", []) + cited))
            stats.append(("papers citing items in %s" % os.path.basename(path), total_all, n_all))
        except ApiError as e:
            failed.append(("citing " + path, str(e)[:300]))

    for q in args.semantic or []:
        years = "|".join(str(y) for y in range(from_date.year, to_date.year + 1))
        f = ["publication_year:" + years]
        if args.types and args.types != "any":
            f.append("type:" + args.types)
        try:
            data = http_get_json(oa_url("/works", **{
                "search.semantic": q, "filter": ",".join(f), "select": WORK_FIELDS,
                "per-page": 50}))  # 50 is the most semantic search allows
            works = [w for w in (data.get("results") or []) if not w.get("is_retracted")]
            stats.append(("semantic: " + q, (data.get("meta") or {}).get("count"), add(works, "semantic: " + q)))
        except ApiError as e:
            failed.append(("semantic: " + q, str(e)[:300]))

    if topic_filter and not args.query:
        f = base + [topic_filter, "has_abstract:true"]
        try:
            works, total = paged_works(",".join(f), sort=sort or "cited_by_count:desc", max_items=args.per_query)
            stats.append(("topic " + topic_filter, total, add(works, topic_filter)))
        except ApiError as e:
            failed.append(("topic " + topic_filter, str(e)[:300]))

    # drop the user's own papers and things already in their library
    excl_authors = set(short_id(a) for a in (args.exclude_author or []))
    known_ids, known_dois, known_titles = set(), set(), set()
    for path in args.known or []:
        try:
            with open(path, "r", encoding="utf-8-sig") as fh:
                meta = json.load(fh)
            if isinstance(meta, dict):  # a library saved by `author` knows who the user is
                excl_authors.update(meta.get("author_ids") or [])
            for it in load_items(path):
                if it.get("id"):
                    known_ids.add(it["id"])
                if it.get("doi"):
                    known_dois.add(norm_doi(it["doi"]))
                if it.get("title"):
                    known_titles.add(norm_title(it["title"]))
        except (OSError, ValueError) as e:
            print("Could not read --known file %s: %s" % (path, e), file=sys.stderr)

    def name_key(n):
        # "David R. Liu", "D. Liu" and "Liu, David" all become ("liu", "d")
        n = (n or "").strip()
        if "," in n:
            last, first = [x.strip() for x in n.split(",", 1)]
            n = first + " " + last
        parts = norm_title(n).split()
        return (parts[-1], parts[0][:1]) if len(parts) >= 2 else None

    excl_names = set(k for k in (name_key(n) for n in (args.exclude_author_name or [])) if k)
    results, seen_titles, dropped = [], {}, Counter()
    for wid in order:
        s = found[wid]
        nt = norm_title(s["title"])
        if excl_authors & set(s["author_ids"]) or excl_names & set(name_key(a) for a in s["authors"]):
            dropped["by the user"] += 1
        elif wid in known_ids or (s["doi"] and s["doi"].lower() in known_dois) or nt in known_titles:
            dropped["already in library"] += 1
        elif find_same(nt, seen_titles) is not None:
            # preprint + published version: keep the published one, or the one with an abstract
            key = find_same(nt, seen_titles)
            prev = seen_titles[key]
            better = ((prev["type"] == "preprint" and s["type"] != "preprint")
                      or (not prev["abstract"] and s["abstract"]))
            if better:
                s["matched"] = prev["matched"] + s["matched"]
                results[results.index(prev)] = s
                seen_titles[key] = s
            dropped["duplicate versions"] += 1
        else:
            seen_titles[nt] = s
            results.append(s)

    label = args.label or "; ".join((args.query or []) + (args.semantic or [])) or topic_filter
    print("=" * 78)
    print("Recent publications | topic: %s" % label)
    print("Window: %s to %s (%d days)" % (from_date, to_date, (to_date - from_date).days))
    print("=" * 78)
    for q, total, n_new in stats:
        print("  search [%s] -> %s match(es) in OpenAlex, %d new candidate(s) fetched" % (q, total, n_new))
    for q, err in failed:
        print("  SEARCH FAILED [%s]: %s" % (q, err))
    if failed:
        print("  -> results below are incomplete. Re-run the same command to retry the failed "
              "searches (finished ones come from the cache at no cost).")
    if dropped:
        print("  removed: " + ", ".join("%d %s" % (c, k) for k, c in dropped.items()))
    print("  candidates to screen: %d" % len(results))
    if any(total and total > args.per_query for _, total, _ in stats):
        print("  (some searches have more matches than --per-query=%d; narrow the query or raise "
              "--per-query if coverage matters)" % args.per_query)
    print("\nThese are CANDIDATES from a keyword search. Read each abstract and keep only the ones "
          "that are really about the topic.\n")

    for i, s in enumerate(results, 1):
        print("[%d] %s | %s | %s | %s" % (i, s["id"], s["date"], s["type"], s["venue"] or "venue unknown"))
        print("    Title: " + s["title"])
        print("    Authors: " + author_str(s["authors"])
              + (" | " + "; ".join(s["institutions"][:2]) if s["institutions"] else ""))
        if s["primary_topic"]:
            print("    OpenAlex topic: " + s["primary_topic"])
        if s.get("cites_user_works"):
            print("    Cites from the library: " + "; ".join(t[:90] for t in s["cites_user_works"][:4]))
        link = "    Link: %s" % s["url"]
        if s["oa_url"] and s["oa_url"] != s["url"]:
            link += " | Open access: " + s["oa_url"]
        print(link + (" | cited by %d" % s["cited_by_count"] if s["cited_by_count"] else ""))
        ab = s["abstract"]
        if not ab:
            print("    Abstract: (none in OpenAlex - open the link before summarising, or mark as title-only)")
        elif args.abstract_chars and len(ab) > args.abstract_chars:
            # results usually sit at the end of an abstract, so keep both ends
            half = args.abstract_chars // 2
            print("    Abstract: " + ab[:half].rsplit(" ", 1)[0] + " [...] " + ab[-half:].split(" ", 1)[-1])
        else:
            print("    Abstract: " + ab)
        print()

    save({"topic": label, "from": str(from_date), "to": str(to_date),
          "searches": [{"query": q, "total_matches": t, "new_candidates": n} for q, t, n in stats],
          "items": results}, args.out)


# ----------------------------------------------------------------------------- main

def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--no-cache", action="store_true", help="ignore cached responses")
    p.add_argument("--key-file", help="file holding the user's OpenAlex key (optional; the "
                                      "OPENALEX_API_KEY environment variable takes precedence, and "
                                      "the skill folder's .config file is the fallback)")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("author", help="load publications for an ORCID iD")
    a.add_argument("--orcid", required=True, help="ORCID iD or ORCID URL")
    a.add_argument("--max-works", type=int, default=200)
    a.add_argument("--max-title-lookups", type=int, default=25)
    a.add_argument("--out", help="save the library JSON here")
    a.set_defaults(func=cmd_author)

    r = sub.add_parser("resolve", help="match titles/DOIs to OpenAlex works")
    r.add_argument("--input", required=True,
                   help='JSON list of {"title":..., "doi":...} (or the output of zotero.py / scan_pdfs.py)')
    r.add_argument("--max-items", type=int, default=300)
    r.add_argument("--max-title-lookups", type=int, default=25,
                   help="cap on title searches (each costs 10x a DOI batch)")
    r.add_argument("--out")
    r.set_defaults(func=cmd_resolve)

    d = sub.add_parser("digest", help="print the digest of a saved library")
    d.add_argument("--input", required=True)
    d.add_argument("--list", action="store_true",
                   help="list every work on one line with id, field, institutions and authors "
                        "(for telling namesakes apart)")
    d.set_defaults(func=cmd_digest)

    u = sub.add_parser("subset", help="keep part of a library (e.g. drop works of namesakes)")
    u.add_argument("--input", required=True)
    u.add_argument("--out", required=True)
    u.add_argument("--keep-title", help="regular expression; keep works whose title matches")
    u.add_argument("--keep-field", action="append",
                   help='keep works whose OpenAlex field or subfield contains this text, e.g. "Linguistics"')
    u.add_argument("--keep-id", action="append", help="OpenAlex work ids to keep (comma separated)")
    u.add_argument("--drop-title", help="regular expression; drop works whose title matches")
    u.add_argument("--drop-id", action="append", help="OpenAlex work ids to drop (comma separated)")
    u.set_defaults(func=cmd_subset)

    c = sub.add_parser("recent", help="find recent publications for ONE topic")
    c.add_argument("--label", help="name of the topic (for the report)")
    c.add_argument("--query", action="append",
                   help='title+abstract search; supports "exact phrases", AND, OR, NOT, parentheses. Repeatable.')
    c.add_argument("--semantic", action="append",
                   help="natural-language description for embedding search (optional, repeatable)")
    c.add_argument("--citing", action="append", metavar="LIBRARY_JSON",
                   help="also find papers that cite the works in this library file (cheap, not a text search)")
    c.add_argument("--topic-id", action="append", help="OpenAlex topic id (e.g. T10028) to restrict/browse")
    c.add_argument("--days", type=int, default=90, help="look-back window in days (default 90)")
    c.add_argument("--from", dest="from_date", help="YYYY-MM-DD (overrides --days)")
    c.add_argument("--to", dest="to_date", help="YYYY-MM-DD (default today)")
    c.add_argument("--per-query", type=int, default=40,
                   help="max results fetched per search (up to 100 costs the same as 1)")
    c.add_argument("--sort", choices=["relevance", "date", "cited"], default="relevance")
    c.add_argument("--types", default=DEFAULT_TYPES, help='e.g. "article|preprint|review" or "any"')
    c.add_argument("--language", help="ISO code, e.g. en")
    c.add_argument("--exclude-author", action="append", help="OpenAlex author id of the user (drop own papers)")
    c.add_argument("--exclude-author-name", action="append",
                   help='name of the user, e.g. "Jane Q. Doe" (drop own papers when no ORCID is '
                        "known). Matches on family name plus first initial, so it also drops "
                        "namesakes with the same initial")
    c.add_argument("--known", action="append", help="library JSON; items already in it (and, for a library saved by "
                                                 "`author`, the user's own papers) are dropped")
    c.add_argument("--abstract-chars", type=int, default=1400,
                   help="shorten printed abstracts to their first and last part (0 = full; "
                        "the saved JSON always has the full text)")
    c.add_argument("--out")
    c.set_defaults(func=cmd_recent)

    args = p.parse_args()
    _key_file["path"] = args.key_file
    if args.no_cache:
        global CACHE_TTL
        CACHE_TTL = 0
    try:
        args.func(args)
    except ApiError as e:
        print("ERROR: %s" % e, file=sys.stderr)
        print(budget_line(), file=sys.stderr)
        sys.exit(1)
    print(budget_line())


if __name__ == "__main__":
    main()
