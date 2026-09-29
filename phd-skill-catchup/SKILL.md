---
name: phd-skill-catchup
description: Personalised literature catch-up for researchers. Learns the user's research interests from their ORCID iD, Zotero library, a publication list pasted from a CV, or a folder of PDFs, lets them pick topics, then finds recent publications (last 90 days by default) on OpenAlex, screens them for relevance, and presents each with a one-sentence summary of its main findings and why it matters to the user. Use this skill whenever a researcher, PhD student, postdoc or academic wants to stay up to date, catch up on the literature, see what's new or what they missed in their field, get a reading digest or literature alert, or find recent papers related to their own work - even if they don't mention OpenAlex, ORCID or Zotero.
compatibility: Works best with a shell and Python 3.8+ (standard library only) and internet access to api.openalex.org. No API keys are required. Without code execution, falls back to fetching OpenAlex URLs with any web-fetch tool (see references/openalex-api.md).
---

# Research catch-up

Help a researcher find out what has been published recently in the areas they care about.
The user is an expert in their field and short on time. What they value: nothing important
missed, nothing irrelevant shown, and summaries they can trust without re-checking.

The workflow has five steps:

1. Ask for a source that shows what they work on
2. Read the source
3. Derive research interests and let the user choose topics
4. Search OpenAlex for recent publications on each chosen topic
5. Screen for relevance and present the results

Steps 1 and 3 are conversations with the user: ask, then wait for the answer. Do not guess
a source or pick topics on their behalf. If your environment has a structured question tool,
use it; otherwise ask in plain text.

## Setup

The helper scripts live in `scripts/` next to this file. They need only Python 3.8+ and no
packages. Run them with `python3` (on Windows usually `python` or `py`). Use the absolute
path of this skill's folder, written `<skill>` below. Save intermediate files in a temporary
or scratch folder (`<work>` below), not in the user's project.

Each script prints a compact report for you to read and saves the full data with `--out`.

**OpenAlex limits.** OpenAlex meters usage, and without an API key it is restrictive in two
ways: the daily allowance is small (about 100 text searches, enough for one normal run), and
text searches are throttled when the service is busy. The scripts wait and retry by
themselves, so a search can take a minute or two. Let it run rather than interrupting it.
Every run ends with a usage line; keep an eye on it. Costs: each `--query`, `--semantic`
and title lookup in `resolve` is one text search ($0.001). Everything else (`author`,
`--citing`, `--topic-id` alone, DOI matching) costs a tenth of that.

**The OpenAlex key is optional.** Everything works without one, so do not ask for a key at
the start and never make one a condition for continuing. Many users are researchers without
technical training, and being asked for an "API key" before anything has happened puts
them off.

Use a key when one is already there. Look in this order:

1. The `OPENALEX_API_KEY` environment variable, or a line `OPENALEX_API_KEY=...` in the
   file `.config` in this skill's folder. The scripts pick up both by themselves, and the
   usage line at the end of each run says whether a key was used. Do not open or print
   `.config`.
2. Your instructions for this conversation: project instructions, custom instructions or
   a memory, where the user may have stored a line such as `OpenAlex key: abc123`. Save
   the key to a file in `<work>` and pass that file to every `openalex.py` call:

   ```bash
   python3 <skill>/scripts/openalex.py --key-file <work>/openalex.key recent ...
   ```

Do not repeat a key in your replies, and do not write it into the digest or the saved
profile. It is enough to say "I'm using your OpenAlex key".

Bring up the key only after the results are delivered, and only if the run was slow (the
script reported waiting for OpenAlex) or the daily allowance ran out. Then offer it as a
convenience, in plain language, using the text under "Afterwards" at the end of this file.

Responses are cached for 12 hours, so repeating a command costs nothing. If a report says
a search failed, re-run the same command: finished searches come from the cache and only
the failed ones are retried.

**No code execution?** Read `references/openalex-api.md` and do the same steps by fetching
the URLs described there.

**Returning user?** If a file named `phd-skill-catchup-profile.md` exists in the working
folder, read it. It holds the topics and queries from a previous run. Offer to reuse it
(covering the time since the last run) instead of starting from scratch.

## Step 1: Ask for a source

Ask the user to share one or more of the following, and mention that combining sources
gives a better picture (publications show what they write about, a reading library shows
what they currently follow):

- **ORCID iD** (e.g. `0000-0002-1825-0097`): their publications are loaded from OpenAlex
- **Zotero library**: a file exported from Zotero
- **Publication list**: pasted from their CV or website
- **PDFs**: a folder, or attached files, of papers they have read or written

None of these needs an account, a password or a key. Then wait for their reply.

## Step 2: Read the source

### ORCID

```bash
python3 <skill>/scripts/openalex.py author --orcid 0000-0002-1825-0097 --out <work>/library.json
```

The report starts with the author's name and affiliation. Confirm with the user that this
is the right person before relying on it, since a mistyped ORCID resolves to a stranger.
Ask only about the name. Do not compare it with account details such as an email address:
people legitimately run this for a supervisor, a collaborator or a group.

OpenAlex sometimes attaches the works of other people with the same name to an ORCID. The
sign is titles that cannot belong to one person, such as language teaching next to
battery chemistry. The digest prints a note when works spread over many fields, but that
also happens with interdisciplinary researchers, so judge by the titles. To look closer,
list every work with its institutions and co-authors:

```bash
python3 <skill>/scripts/openalex.py digest --input <work>/library.json --list
```

If works of other people are mixed in, tell the user, ask which group is theirs, and make
a cleaned library. Use the cleaned file everywhere a library is needed:

```bash
python3 <skill>/scripts/openalex.py subset --input <work>/library.json --out <work>/mine.json \
  --keep-title "language|learner|readab" --keep-id W111,W222 --drop-id W123,W456
```

A work is kept if it matches any `--keep` option and no `--drop` option. `--keep-field`
exists too, but namesakes often share a broad field such as computer science, so titles
and ids are more precise. The report lists what was dropped; check it, and tell the user
about works you were unsure of.

If OpenAlex
has no works for the ORCID, the script falls back to the public ORCID record by itself. If
both are empty, ask for another source.

### Zotero

**Recommended: an export file.** It needs no key and works everywhere, including web apps.
If the user has not exported before, give them these steps:

> 1. Open the Zotero app on your computer.
> 2. To share everything, choose **File > Export Library…** in the menu. To share one
>    collection, right-click it in the left panel and choose **Export Collection…**
> 3. In the **Format** list choose **CSV**. Leave the other boxes as they are and click **OK**.
> 4. Save the file, then attach it to this chat (or tell me where you saved it).

CSV is the best choice because it includes the date each item was added. BibTeX, RIS and
CSL JSON exports work too.

```bash
python3 <skill>/scripts/zotero.py --file "My Library.csv" --out <work>/zotero.json
```

**If you run on the user's own computer** (a terminal or desktop agent, not a web app),
you can read the Zotero database directly and spare them the export. Offer it, and fall
back to the export file if it is not found:

```bash
python3 <skill>/scripts/zotero.py --sqlite --out <work>/zotero.json
```

This reads a temporary copy, so it is safe while Zotero is open. Add `--collection NAME`
to focus on one collection.

**Advanced routes**, for users who ask for them: a running Zotero 7+ with its local API
enabled (`--local`), or the zotero.org web API (`--user-id` or `--group-id`), which needs
a Zotero API key for private libraries. Do not suggest the web API to a user who has not
asked for it; the export file gives the same result. If a user does want it, the key is
read from the `ZOTERO_API_KEY` environment variable or a line `ZOTERO_API_KEY=...` in the
skill's `.config` file, and it should be created as read-only. See `scripts/zotero.py --help`.

Items come out newest-added first, capped at 300, because recent additions say the most
about current interests.

### Publication list from a CV

Parse the pasted text yourself into a JSON list, one object per publication, and save it
as `<work>/cv.json`:

```json
[{"title": "Full title of the paper", "doi": "10.1234/abcd", "year": 2024}]
```

Include `doi` only when it appears in the text. Titles and venues alone are usually enough
to see what someone works on, so the next step is optional enrichment.

### PDFs

In a web app the user attaches the files to the chat; treat the folder they land in as the
PDF folder.

```bash
python3 <skill>/scripts/scan_pdfs.py "/path/to/folder" --out <work>/pdfs.json
```

This extracts the first pages of each PDF (newest 150 files). The title guesses are rough
heuristics. Read the `excerpt` fields in the saved JSON to see real titles and abstracts.
If the report says no text extractor is available, either install one (`pip install pypdf`)
or read a sample of 15 to 20 PDFs directly with your own file-reading ability.

### Optional: enrich with OpenAlex metadata

For Zotero, CV and PDF sources you can attach OpenAlex topics, keywords and abstracts:

```bash
python3 <skill>/scripts/openalex.py resolve --input <work>/zotero.json --out <work>/library.json
```

Items with a DOI are matched in cheap batches. Each item with only a title costs one text
search, so they are capped (`--max-title-lookups`, default 25, which is a quarter of the
daily allowance without a key). Set it to 0 to match DOIs only. Do this when many items have
DOIs or when the titles alone leave the interests unclear. Skip it when the titles and
abstracts you already have paint a clear picture.

## Step 3: Derive interests and let the user choose

Read the digest(s) and form your own view of what this person works on. Aim for 5 to 8
research interests.

What makes a good interest:

- **Specific enough to search.** "Natural language processing" is a field, not an
  interest. "Automatic readability assessment for language learners" is an interest. The
  OpenAlex topic labels in the digest are coarse. Treat them as hints and look at the
  actual titles to find the specific threads.
- **Grounded in evidence.** Each interest should be backed by several items. Name two or
  three of them when you present it, so the user sees why you proposed it.
- **Weighted towards the present.** A topic they published on ten years ago and never
  since is probably not what they want to catch up on. Recent papers and recently added
  library items count most.
- **Distinct.** Merge near-duplicates. If two interests would return the same papers,
  they are one interest.

Present the interests as a numbered list, each with a one-line description and its
evidence. Then ask the user which ones they want to catch up on. Let them choose several,
reword any, or add topics that are not in the list. Also confirm the time window: the
default is the last 90 days, and they can ask for a longer or different period.

Wait for their answer before searching.

## Step 4: Search OpenAlex

Run one search per chosen topic. For each topic, write 2 to 4 queries that approach it from
different angles: the field's own terminology, common synonyms and abbreviations, and
neighbouring communities that use different words for the same thing. One narrow query
misses papers. Several complementary ones catch them, and the script removes duplicates.

```bash
python3 <skill>/scripts/openalex.py recent \
  --label "LLM feedback on second language writing" \
  --query '"second language writing" AND (LLM OR ChatGPT OR "large language model")' \
  --query '("L2 writing" OR "EFL writing") AND "automated feedback"' \
  --known <work>/library.json \
  --out <work>/recent-1.json
```

Query syntax: searches titles and abstracts. Use `"quoted phrases"`, `AND`, `OR`, `NOT`
(uppercase) and parentheses. Unquoted words are stemmed and all must appear. Count the
words `AND`, `OR` and `NOT` in a query and keep them to 5 or fewer: OpenAlex slows down
queries with more, and several short queries find more than one long one anyway.

Terms of art often mean something else in another field ("twin prime" is also number
theory, "PEmax" is also respiratory medicine). When off-field papers show up, add
`--topic-id` with one or two OpenAlex topic ids from the library digest. That restricts
the query to the user's field.

**Papers that cite the user.** When the library holds the user's own publications (ORCID
or CV), also run one search for new papers that cite them:

```bash
python3 <skill>/scripts/openalex.py recent --label "Cites your work" \
  --citing <work>/library.json --known <work>/library.json --per-query 50 \
  --out <work>/recent-citing.json
```

This is cheap, is not throttled, and finds follow-up work that uses different vocabulary
from the user's. It needs a library with OpenAlex ids (from `author` or `resolve`).

When the library is a reading collection (Zotero or PDFs), the papers in it are not the
user's own. Do not say that anything "cites your work". The search is still useful in a
narrower form: make a `subset` of the library items that belong to the chosen topics and
pass that to `--citing`, otherwise one popular paper on a side topic floods the results.
Present the hits as "cites a paper in your library" and name the paper.

Many
citing papers mention the user's work only in passing, so screen them like any other
candidate. The report names the works of the user that each paper cites; use that in the
relevance sentence. To screen: keep those that fall under a chosen topic and show them there, marked as citing
the user. If a paper builds directly on the user's work but fits no chosen topic, list it
in a short final section "Also citing your work" (for a reading library: "Also citing
papers in your library").

Useful options:

| Option | Purpose |
|---|---|
| `--days 90` | look-back window. Or use `--from 2026-01-01 --to 2026-03-31` for a fixed period |
| `--known FILE` | drop papers already in the user's library and, for an ORCID library, the user's own papers. Repeatable. Also accepts the `--out` file of an earlier search, so a later search does not return the same papers again |
| `--exclude-author-name "Jane Q. Doe"` | drop the user's own new papers when the source was not an ORCID. Matches family name plus first initial, so "J. Doe" is covered |
| `--per-query 40` | results fetched per query. Up to 100 costs the same as one search, so raise it freely when a query has more matches than were fetched. Re-running a query with a different number counts as a new search |
| `--abstract-chars 0` | print full abstracts. By default long abstracts are shortened to their first and last part. The saved JSON always has the full text |
| `--semantic "plain description of the topic"` | adds a meaning-based search. Useful when the topic is hard to express in keywords. It can only be limited by year, not by date, so in a short window it may return little |
| `--topic-id T11587` | restrict to an OpenAlex topic from the digest. Useful when a query term is ambiguous across fields |
| `--sort date` or `--sort cited` | default is relevance |
| `--types "article\|preprint\|review"` | the default. Use `any` to include book chapters, theses, datasets |

The reports are long, because screening needs the abstracts. If your tool output is
limited, redirect the report to a file in `<work>` and read it in parts.

Read the search statistics at the top of the report and adjust:

- **Hundreds of matches**: the query is too broad. Add a constraining term, or use
  `--topic-id`.
- **More matches than were fetched** (say 160 matches, 40 fetched): in a busy field, start
  with `--per-query 100`. If there are still more, split the topic into narrower queries.
  Tell the user in the notes when coverage is partial.
- **Zero or very few matches**: loosen it. Queries that combine three or more specific
  concepts with `AND` often return nothing in a 90-day window; two concepts are usually
  enough, since you screen the results anyway. Drop a term, add synonyms with `OR`, or try
  `--semantic`. If the topic is simply quiet, that is a valid finding. Say so rather than
  padding the list with loosely related papers.

## Step 5: Screen and present

### Screen every candidate

The search matches words, so the candidates include papers that mention the right terms
while being about something else. Read each abstract and keep a paper only if the topic is
what the paper is actually about. A paper on ChatGPT in medical education that mentions
"language" in passing does not belong under second language writing.

Also drop what slipped through the filters: the user's own papers, duplicates, conference
front matter, and items with no real content. Be cautious with papers from venues that look
predatory, and leave them out if the abstract is low quality.

If many papers survive for one topic, show the 10 to 15 most relevant and tell the user
how many more there are. Rank by relevance to this user first, then by venue and recency.

### Write the entries

Each paper gets one sentence on what it found and one on why this user should care.

**The findings sentence** states the main result, not the topic. "Examines LLM feedback on
essays" says what the paper is about. "LLM feedback improved revision quality as much as
teacher feedback in a 12-week classroom study with 240 learners, but only for students who
engaged with it" says what was found. Include the concrete outcome, effect or number when
the abstract gives one. For reviews and position papers, state the central conclusion.

Base the sentence only on the abstract. If the printed abstract was shortened and the
result is in the omitted part, read the full abstract in the saved JSON. Do not fill gaps with what you would expect such a
paper to show. The user will decide what to read based on your sentence, and an invented
finding is worse than none. When OpenAlex has no abstract, either fetch the paper's landing
page to read it, or write the entry from the title and mark it "(no abstract available)".
A title-only entry says what the title says and nothing more, and does not go at the top
of a topic. The same holds when the abstract only states the problem or is cut off before
the results: say that the abstract gives no result, rather than inferring one.

Keep the abstract's own limits. If it says an effect held "generally", or for two of three
models, or that the authors "conclude" something, the sentence says the same. Dropping
such qualifiers is the most common way these summaries go wrong. Attribute details to the
right part of the study: a number that belongs to one experiment should not be attached to
another.

**Check before you present.** When all entries are written, go through them once more
against the abstracts: every number, every direction of effect, every name of a method or
dataset. Correct what does not match. This takes a minute and is what makes the digest
trustworthy.

**The relevance sentence** connects the paper to this user's own work, and should be
different for every paper. Refer to their specific papers, methods, data or questions:
"Uses the same learner corpus as your 2017 task-effects study and reaches the opposite
conclusion for syntactic complexity." A sentence that would fit any reader, such as "This
is relevant to your interest in readability", tells them nothing, since the paper is
already listed under that topic. Name the paper or item you mean ("your 2024 study of the
task-based agent", "the Denis 2021 paper in your library"). "Your dialogue system" or "your
work on feedback" is too vague for the user to see the connection.

### Output format

Group by topic. Within a topic, most relevant first. Use this structure:

```markdown
# Research catch-up: 30 June to 28 September 2026

Based on: ORCID 0000-0002-1825-0097 (200 publications)
Topics: 3 | Papers screened: 84 | Papers selected: 21

## 1. LLM feedback on second language writing
7 selected out of 31 screened

**1. [Title of the paper](https://doi.org/10.xxxx/xxxxx)**
First Author, Second Author, et al. · *Journal or venue* · 14 Jul 2026 · article · open access
- **Findings:** One sentence with the main result.
- **Why it matters to you:** One sentence linking it to their work.

**2. [Next paper](https://doi.org/...)**
...

## 2. Next topic
...

## Notes
- Anything the user should know: quiet topics, topics where the query had to be broadened,
  papers summarised from title only.
```

Every paper you mention gets a link, including those in brief "also on topic" or "not
shown" lists. Copy names, venues and dates from the OpenAlex record; if you fill a gap
yourself (a venue guessed from the DOI, a name transliterated), say so.

Mark preprints as "preprint" in the metadata line, since they are not peer reviewed. Show
"open access" only when OpenAlex reports it, and link the open access copy when its URL
differs from the DOI link.

If the user asked for a file or has many results, also save the digest as a Markdown file
in their working folder and tell them where it is.

### Afterwards

**If the run was slow or hit the daily limit**, and no key was in use, add this once, in
your own words but keeping the steps:

> The search was slow because OpenAlex limits anonymous use. A free OpenAlex key makes
> future runs faster and more complete. It is optional. To set it up:
>
> 1. Go to https://openalex.org and create a free account.
> 2. Open https://openalex.org/settings/api and copy the key shown there.
> 3. Store it where I can find it next time:
>    - Claude: open or create a Project, and add the line `OpenAlex key: <your key>` to
>      the project instructions.
>    - ChatGPT: open or create a Project, and add the same line to its instructions.
>    - A terminal agent: create a file named `.config` in the skill's folder containing
>      the line `OPENALEX_API_KEY=<your key>`.
>
> The key only counts how much you use OpenAlex. It gives no access to your account or
> data, and you can replace it on the same page at any time.

If the user pastes a key into the chat instead, accept it and use it for this conversation
with `--key-file`. Mention once that storing it as above saves them from pasting it again.

Offer, briefly:

- to go deeper on any paper, widen or narrow a topic, or extend the time window
- to save a profile for next time. If they agree, write `phd-skill-catchup-profile.md` to
  the working folder with: the sources used (ORCID, file paths, never API keys), the chosen
  topics with the queries that worked well, and today's date as the last run. Next time
  the search can start from there and cover only the period since.
