# phd-skill-catchup

An AI agent skill that helps researchers stay up to date. It learns your research interests
from your ORCID iD, your Zotero library, the publication list in your CV or a folder of
PDFs. You pick the topics you want to catch up on, and it finds recent publications on
[OpenAlex](https://openalex.org), keeps the ones that are really on topic, and gives you
for each paper one sentence on what it found and one on why it matters to you.

## Who it is for

The skill runs in AI agents that work on your own computer. It has been tested with
**Claude Code** and **OpenAI Codex CLI**.

It does not work in the Claude and ChatGPT web apps. These apps do not let a skill connect
to OpenAlex. If you use them, or if you do not use an AI agent at all, see
[Not using Claude Code or Codex?](#not-using-claude-code-or-codex) below.

## Quick start

**1. Install the skill**

Copy this prompt into Claude Code or Codex:

```text
Install the "phd-skill-catchup" skill from https://github.com/cheniode/phd-skill-catchup for me.

1. Download https://github.com/cheniode/phd-skill-catchup/releases/latest/download/phd-skill-catchup.zip
2. Unpack it into your personal skills folder, so that the file
   <skills folder>/phd-skill-catchup/SKILL.md exists. If an older version is already
   there, replace it but keep its .config file.
3. Check that SKILL.md is in place and tell me which folder you used.
4. Tell me how to add my OpenAlex key: I create a file named .config in that folder with
   the line OPENALEX_API_KEY=<my key>. Do not ask me to paste the key into the chat.
```

The agent asks your permission before it downloads and writes files. Restart the agent
afterwards so that it sees the new skill.

To install by hand instead,
[download phd-skill-catchup.zip](https://github.com/cheniode/phd-skill-catchup/releases/latest/download/phd-skill-catchup.zip)
and unpack it into the skills folder of your agent:

| Agent | Skills folder |
|---|---|
| Claude Code | `~/.claude/skills/` |
| Codex CLI | `~/.agents/skills/` |

**2. Set up your OpenAlex key**

This is the only thing to set up. OpenAlex is the free database the skill searches. The key
is free, and with it searches are fast and complete.

1. Create a free account at https://openalex.org.
2. Open https://openalex.org/settings/api and copy your key.
3. Create a text file named `.config` in the installed skill folder (the agent told you
   which folder it used) with this single line: `OPENALEX_API_KEY=<your key>`

The key only counts how much you use OpenAlex. It gives no access to your account or data,
and you can replace it on the same page at any time.

If you skip this step the skill still works, but searches are slow at busy times and you
are limited to about one run per day.

**3. Use it**

Ask your agent, for example:

> Help me catch up on recent papers in my field.

The agent asks what it may use to learn your interests. You can give it any of these:

- your ORCID iD
- your Zotero library, which it reads from the Zotero app on your computer, or a file
  exported from Zotero (File > Export Library, format CSV)
- the publication list from your CV, pasted into the chat
- a folder with PDFs of papers you have read or written

None of these needs a password or an account. By default the skill covers the last 90
days. Ask for a different period if you want one.

When the list is ready, the agent offers to save the papers as a file you can import into
Zotero, EndNote, Mendeley, Papers or JabRef. Every entry is tagged with the date of the
catch-up, so the batch is easy to find in your library afterwards.

## Not using Claude Code or Codex?

The author maintains a separate free tool that does this without an AI agent.
Its name and link will be added here.

## Good to know

- **Summaries are based on abstracts.** The agent does not read the full papers. Check a
  paper before you cite it.
- **Same name, different person.** OpenAlex sometimes attaches the works of other people
  with your name to your ORCID. The skill notices this and asks which works are yours.
- **Reading PDFs** works best if `pypdf` is installed (`pip install pypdf`) or the
  `pdftotext` program is available.

## For developers

```
phd-skill-catchup/
├── SKILL.md                    workflow instructions for the agent
├── scripts/
│   ├── openalex.py             ORCID loading, title and DOI matching, recent-works search
│   ├── zotero.py               Zotero export files, local database, local and web API
│   ├── scan_pdfs.py            title, DOI and first-page text from a folder of PDFs
│   └── export_refs.py          selected papers as BibTeX, RIS or CSL JSON
└── references/
    └── openalex-api.md         raw API usage for agents that cannot run scripts
```

The helper scripts need Python 3.8 or later and no additional packages. They were tested on
Linux. They are written to run on macOS and Windows too, but that has not been tested.

Keys are looked up in this order: the `OPENALEX_API_KEY` environment variable, a file given
with `--key-file`, the `.config` file in the skill folder. Reading a private Zotero library
through zotero.org, instead of an export file, needs a read-only Zotero key as
`ZOTERO_API_KEY=<your key>` in the same `.config` file.

`.config` is listed in `.gitignore`. To build the package, run `./build.sh`. It leaves out
`.config`, so your own key never ends up in the zip file.
