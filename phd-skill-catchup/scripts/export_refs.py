#!/usr/bin/env python3
"""Write selected papers as a reference file for Zotero, EndNote, Mendeley or similar.

Reads the JSON saved by `openalex.py recent` (or `author`/`resolve`), keeps the papers you
name with --select, and writes BibTeX (.bib), RIS (.ris) and/or CSL JSON (.json).

Example
  python3 export_refs.py --input recent-1.json --input recent-2.json \
      --select W7168288578,W7171372165 --tag "catch-up 2026-09-30" \
      --format all --out /home/me/catchup-2026-09-30

Import into Zotero: File > Import… > pick the file > "Copy files to storage" is not needed.
Every entry carries the tag given with --tag, so the batch is easy to find afterwards.
"""
import argparse
import json
import os
import re
import sys

TEX = {"\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "%": r"\%",
       "&": r"\&", "$": r"\$", "#": r"\#", "_": r"\_"}
BIB_TYPE = {"article": "article", "review": "article", "book-chapter": "incollection",
            "book": "book", "dissertation": "phdthesis", "preprint": "misc",
            "paratext": "misc", "dataset": "misc"}
RIS_TYPE = {"article": "JOUR", "review": "JOUR", "book-chapter": "CHAP", "book": "BOOK",
            "dissertation": "THES", "preprint": "UNPB", "dataset": "DATA"}


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def tex(s):
    return "".join(TEX.get(c, c) for c in clean(s))


def split_name(n):
    """'Xiaobin Chen' -> ('Chen', 'Xiaobin'); 'Chen, Xiaobin' -> ('Chen', 'Xiaobin')."""
    n = clean(n)
    if "," in n:
        last, first = n.split(",", 1)
        return clean(last), clean(first)
    parts = n.split()
    return (parts[-1], " ".join(parts[:-1])) if len(parts) > 1 else (n, "")


def cite_key(w, used):
    last = split_name((w.get("authors") or ["anon"])[0])[0]
    last = re.sub(r"[^A-Za-z]", "", last) or "anon"
    word = ""
    for t in re.findall(r"[A-Za-z]{4,}", w.get("title") or ""):
        if t.lower() not in ("the", "and", "for", "with", "from", "that", "this", "into"):
            word = t.lower()
            break
    key = base = "%s%s%s" % (last.lower(), w.get("year") or "", word)
    i = 1
    while key in used:
        key = base + chr(ord("a") + i - 1)
        i += 1
    used.add(key)
    return key


def bibtex(works, tag, keywords=False):
    out, used = [], set()
    for w in works:
        kind = BIB_TYPE.get(w.get("type"), "misc")
        venue = w.get("venue")
        if kind == "article" and venue and re.search(r"(?i)proceedings|conference|workshop", venue):
            kind = "inproceedings"
        f = []
        f.append(("title", tex(w.get("title"))))
        if w.get("authors"):
            f.append(("author", " and ".join(
                "%s, %s" % (tex(a), tex(b)) if b else tex(a)
                for a, b in (split_name(x) for x in w["authors"]))))
        if w.get("year"):
            f.append(("year", str(w["year"])))
        if venue:
            f.append(({"inproceedings": "booktitle", "misc": "howpublished",
                       "incollection": "booktitle"}.get(kind, "journal"), tex(venue)))
        if w.get("doi"):
            f.append(("doi", w["doi"]))
        if w.get("url"):
            f.append(("url", w["url"]))
        if w.get("abstract"):
            f.append(("abstract", tex(w["abstract"])))
        kw = ([tag] if tag else []) + (list(w.get("keywords") or []) if keywords else [])
        if kw:
            f.append(("keywords", tex(", ".join(kw))))
        if w.get("date"):
            f.append(("date", w["date"]))
        if w.get("type") == "preprint":
            f.append(("note", "Preprint"))
        out.append("@%s{%s,\n%s\n}\n" % (
            kind, cite_key(w, used),
            ",\n".join("  %-12s = {%s}" % (k, v) for k, v in f)))
    return "\n".join(out)


def ris(works, tag, keywords=False):
    out = []
    for w in works:
        L = ["TY  - " + RIS_TYPE.get(w.get("type"), "GEN"), "TI  - " + clean(w.get("title"))]
        for a in w.get("authors") or []:
            last, first = split_name(a)
            L.append("AU  - " + (("%s, %s" % (last, first)) if first else last))
        if w.get("year"):
            L.append("PY  - %s" % w["year"])
        if w.get("date"):
            L.append("DA  - " + w["date"].replace("-", "/"))
        if w.get("venue"):
            L.append("JO  - " + clean(w["venue"]))
        if w.get("doi"):
            L.append("DO  - " + w["doi"])
        if w.get("url"):
            L.append("UR  - " + w["url"])
        if w.get("abstract"):
            L.append("AB  - " + clean(w["abstract"]))
        if tag:
            L.append("KW  - " + tag)
        for k in (w.get("keywords") or []) if keywords else []:
            L.append("KW  - " + clean(k))
        if w.get("language"):
            L.append("LA  - " + w["language"])
        L.append("ER  - ")
        out.append("\n".join(L))
    return "\n\n".join(out) + "\n"


def csljson(works, tag, keywords=False):
    out = []
    for w in works:
        d = {"id": w.get("id") or w.get("doi") or clean(w.get("title"))[:40],
             "type": {"preprint": "article", "book-chapter": "chapter", "book": "book",
                      "dissertation": "thesis"}.get(w.get("type"), "article-journal"),
             "title": clean(w.get("title"))}
        if w.get("authors"):
            d["author"] = [{"family": a, "given": b} for a, b in
                           (split_name(x) for x in w["authors"])]
        parts = [int(x) for x in (w.get("date") or "").split("-") if x.isdigit()]
        if parts:
            d["issued"] = {"date-parts": [parts]}
        elif w.get("year"):
            d["issued"] = {"date-parts": [[w["year"]]]}
        for src, dst in (("venue", "container-title"), ("doi", "DOI"), ("url", "URL"),
                         ("abstract", "abstract"), ("language", "language")):
            if w.get(src):
                d[dst] = clean(w[src]) if src != "doi" else w[src]
        kw = ([tag] if tag else []) + (list(w.get("keywords") or []) if keywords else [])
        if kw:
            d["keyword"] = ", ".join(kw)
        if w.get("type") == "preprint":
            d["note"] = "Preprint"
        out.append(d)
    return json.dumps(out, ensure_ascii=False, indent=1) + "\n"


def load(paths):
    items, seen = [], set()
    for p in paths:
        with open(p, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        got = data.get("items", data) if isinstance(data, dict) else data
        for w in got if isinstance(got, list) else []:
            if not isinstance(w, dict) or not w.get("title"):
                continue
            k = w.get("id") or (w.get("doi") or "").lower() or clean(w["title"]).lower()
            if k not in seen:
                seen.add(k)
                items.append(w)
    return items


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", action="append", required=True,
                   help="JSON saved by openalex.py (repeatable)")
    p.add_argument("--select", action="append",
                   help="OpenAlex ids or DOIs of the papers to export, comma or space "
                        "separated (repeatable). Omit to export everything in --input")
    p.add_argument("--exclude", action="append", help="ids or DOIs to leave out")
    p.add_argument("--format", default="bib", choices=["bib", "ris", "csljson", "all"],
                   help="bib for Zotero/JabRef, ris for EndNote/Mendeley, csljson, or all")
    p.add_argument("--tag", help='tag added to every entry, e.g. "catch-up 2026-09-30"')
    p.add_argument("--keywords", action="store_true",
                   help="also copy the automatic OpenAlex keywords as tags. They are noisy "
                        "(\"Set (abstract data type)\"), so they are left out by default")
    p.add_argument("--out", required=True,
                   help="output path; the right extension is added if missing")
    args = p.parse_args()

    items = load(args.input)

    def keys(vals):
        out = set()
        for v in vals or []:
            for x in re.split(r"[,\s]+", v):
                x = x.strip().replace("https://doi.org/", "").replace("https://openalex.org/", "")
                if x:
                    out.add(x.lower())
        return out

    want, skip = keys(args.select), keys(args.exclude)
    chosen, missing = [], set(want)
    for w in items:
        ids = {(w.get("id") or "").lower(), (w.get("doi") or "").lower()} - {""}
        if ids & skip:
            continue
        if want:
            hit = ids & want
            if not hit:
                continue
            missing -= hit
        chosen.append(w)
    if missing:
        print("WARNING: not found in the input files: %s" % ", ".join(sorted(missing)),
              file=sys.stderr)
    if not chosen:
        print("Nothing to export: no paper matched --select.", file=sys.stderr)
        sys.exit(1)

    stem = args.out
    for ext in (".bib", ".ris", ".json"):
        if stem.lower().endswith(ext):
            stem = stem[:-len(ext)]
    d = os.path.dirname(os.path.abspath(stem))
    if d:
        os.makedirs(d, exist_ok=True)
    formats = ["bib", "ris", "csljson"] if args.format == "all" else [args.format]
    written = []
    for fmt in formats:
        text, ext = {"bib": (bibtex, ".bib"), "ris": (ris, ".ris"),
                     "csljson": (csljson, ".json")}[fmt]
        path = stem + ext
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text(chosen, args.tag, args.keywords))
        written.append(path)

    print("Exported %d paper(s)%s." % (len(chosen), " tagged '%s'" % args.tag if args.tag else ""))
    for path in written:
        print("  %s" % path)
    print("\nTell the user: in Zotero, File > Import… and pick this file. EndNote, Mendeley,\n"
          "Papers and JabRef import the same formats.")


if __name__ == "__main__":
    main()
