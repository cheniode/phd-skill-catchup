#!/usr/bin/env python3
"""Scan a folder of PDFs for the phd-skill-catchup skill (Python 3.8+).

For each PDF, extracts a title guess, a DOI if one is printed in the paper, and the first
part of the text (usually title + abstract). Uses whichever extractor is available:
pypdf / PyPDF2 (pip install pypdf), or the `pdftotext` command (poppler). With neither,
it still reports file names and any metadata it can find, and the agent should read a
sample of the PDFs directly.

Writes {"source": "pdf-folder", "items": [{file, title, doi, excerpt, year}]} to --out.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>{}|\\^`\[\]]+)", re.I)


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def extractor():
    try:
        import pypdf  # noqa: F401
        return "pypdf"
    except ImportError:
        pass
    try:
        import PyPDF2  # noqa: F401
        return "PyPDF2"
    except ImportError:
        pass
    if shutil.which("pdftotext"):
        return "pdftotext"
    return None


def read_pdf(path, how, pages):
    """Return (text of first pages, metadata title)."""
    if how in ("pypdf", "PyPDF2"):
        mod = __import__(how)
        reader = mod.PdfReader(path)
        title = ""
        try:
            title = clean(str((reader.metadata or {}).get("/Title") or ""))
        except Exception:
            pass
        text = ""
        for i in range(min(pages, len(reader.pages))):
            try:
                text += (reader.pages[i].extract_text() or "") + "\n"
            except Exception:
                pass
        return text, title
    if how == "pdftotext":
        res = subprocess.run(["pdftotext", "-l", str(pages), "-enc", "UTF-8", path, "-"],
                             capture_output=True, timeout=60)
        return res.stdout.decode("utf-8", "replace"), ""
    # no extractor: look for an uncompressed /Title entry
    with open(path, "rb") as fh:
        raw = fh.read(400000)
    m = re.search(rb"/Title\s*\(([^)]{5,300})\)", raw)
    return "", clean(m.group(1).decode("latin-1", "replace")) if m else ""


def looks_like_title(s):
    if not (12 <= len(s) <= 250) or len(s.split()) < 3:
        return False
    if re.search(r"(?i)(doi\.org|https?://|©|copyright|arxiv:|\bvol\.|\bissn\b|downloaded|"
                 r"journal homepage|all rights reserved|@|received:|accepted:|published)", s):
        return False
    letters = sum(c.isalpha() for c in s)
    return letters / max(1, len(s)) > 0.6


def guess_title(text, meta_title, filename):
    bad_meta = re.search(r"(?i)(untitled|microsoft word|\.docx?$|\.pdf$|\.tex$|^\d+$)", meta_title or "")
    if meta_title and not bad_meta and looks_like_title(meta_title):
        return meta_title, "metadata"
    lines = [clean(l) for l in text.splitlines()[:40]]
    for i, l in enumerate(lines):
        if looks_like_title(l):
            # titles often wrap onto a second line
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            cont = (3 <= len(nxt) <= 120 and not re.search(r"[\d,@]", nxt)
                    and sum(c.isalpha() or c == " " for c in nxt) / len(nxt) > 0.9)
            if cont and len(l) + len(nxt) < 220:
                return l + " " + nxt, "first-page"
            return l, "first-page"
    stem = os.path.splitext(os.path.basename(filename))[0]
    return clean(re.sub(r"[_\-]+", " ", stem)), "filename"


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("folder")
    p.add_argument("--max-files", type=int, default=150, help="newest files first")
    p.add_argument("--pages", type=int, default=2, help="pages to read per PDF")
    p.add_argument("--excerpt-chars", type=int, default=1500)
    p.add_argument("--out")
    args = p.parse_args()

    folder = os.path.expanduser(args.folder)
    if not os.path.isdir(folder):
        raise SystemExit("Not a folder: " + folder)
    pdfs = []
    for root, _, files in os.walk(folder):
        for f in files:
            if f.lower().endswith(".pdf"):
                full = os.path.join(root, f)
                try:
                    pdfs.append((os.path.getmtime(full), full))
                except OSError:
                    pass
    pdfs.sort(reverse=True)
    total = len(pdfs)
    pdfs = pdfs[:args.max_files]
    how = extractor()

    items, failed = [], 0
    for _, path in pdfs:
        try:
            text, meta_title = read_pdf(path, how, args.pages)
        except Exception as e:  # damaged or encrypted files should not stop the scan
            text, meta_title = "", ""
            failed += 1
            print("  (could not read %s: %s)" % (os.path.basename(path), str(e)[:80]), file=sys.stderr)
        title, title_from = guess_title(text, meta_title, path)
        m = DOI_RE.search(text)
        doi = m.group(1).rstrip(".,;)") if m else None
        ym = re.search(r"\b(19[89]\d|20[0-3]\d)\b", text[:3000])
        items.append({"file": os.path.relpath(path, folder), "title": title, "title_from": title_from,
                      "doi": doi, "year": int(ym.group(1)) if ym else None,
                      "excerpt": clean(text)[:args.excerpt_chars] or None})

    print("PDF folder: %s | %d PDF(s) found%s" % (
        folder, total, ", scanned the %d newest" % len(pdfs) if total > len(pdfs) else ""))
    print("Text extractor: %s" % (how or "NONE - install `pypdf` (pip install pypdf) or poppler's pdftotext, "
                                         "or read a sample of the PDFs directly"))
    no_text = sum(1 for i in items if not i["excerpt"])
    print("With DOI: %d | without extractable text (scanned images?): %d | unreadable: %d" % (
        sum(1 for i in items if i["doi"]), no_text, failed))
    print("\nTitle guesses (check the ones marked 'filename' - they are unreliable):")
    for i in items:
        print("  - %s  [%s; %s]" % (i["title"], i["title_from"], i["file"]))
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump({"source": "pdf-folder", "folder": folder, "items": items}, fh, ensure_ascii=False, indent=1)
        print("\nSaved %d item(s) with excerpts to: %s" % (len(items), args.out))


if __name__ == "__main__":
    main()
