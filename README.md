# phd-skill-catchup

An agent skill that helps researchers stay up to date. It learns your research interests
from your ORCID iD, Zotero library, CV publication list or a folder of PDFs, lets you pick
the topics you want to catch up on, and then finds and summarises recent publications from
[OpenAlex](https://openalex.org).

The skill follows the open [Agent Skills](https://agentskills.io) format (`SKILL.md` plus
bundled scripts), so it works in any agent that supports it. The helper scripts use only
the Python standard library (3.8+) and run on Linux, macOS and Windows.

## Install

Copy or link the `phd-skill-catchup/` folder into the skills directory of your agent:

| Agent | Location |
|---|---|
| Claude Code | `~/.claude/skills/` (personal) or `<project>/.claude/skills/` |
| Claude apps (claude.ai, desktop) | zip the `phd-skill-catchup` folder and upload it under Settings > Capabilities > Skills |
| OpenAI Codex CLI, Gemini CLI, Cursor, GitHub Copilot, and others | `~/.agents/skills/` or `<project>/.agents/skills/` (check your agent's documentation for the exact path) |

Example:

```bash
cp -r phd-skill-catchup ~/.claude/skills/
```

## Use

Ask your agent something like "help me catch up on recent papers in my field" or invoke the
skill by name (`/phd-skill-catchup` in Claude Code).

## No keys required

The skill works without any account or API key. Zotero libraries are shared as an export
file (File > Export Library in Zotero), and OpenAlex is used anonymously.

Anonymous OpenAlex use is slow at busy times and limited to about one run per day. A free
OpenAlex key lifts both. The skill explains this to the user after a slow run. To store a
key so it is found in every conversation:

| Where you use the skill | Where to put the key |
|---|---|
| Claude or ChatGPT web and desktop apps | Add the line `OpenAlex key: <your key>` to the instructions of a Project |
| Terminal agents such as Claude Code | Create a file `.config` in the installed skill folder with the line `OPENALEX_API_KEY=<your key>`, or set the `OPENALEX_API_KEY` environment variable |

The key comes from https://openalex.org/settings/api. It only meters usage and can be
replaced at any time.

Advanced: reading a private library through zotero.org instead of an export file needs a
read-only Zotero key, as `ZOTERO_API_KEY=<your key>` in the same `.config` file or as an
environment variable.

The `.config` file is listed in `.gitignore`, so it is not committed. Remove it before you
zip or share the skill folder.

Optional: `pip install pypdf` (or install poppler's `pdftotext`) for reading PDF folders.

## Layout

```
phd-skill-catchup/
├── SKILL.md                    workflow instructions for the agent
├── scripts/
│   ├── openalex.py             ORCID/author loading, title+DOI matching, recent-works search
│   ├── zotero.py               Zotero export files, local database, local and web API
│   └── scan_pdfs.py            title, DOI and first-page text from a folder of PDFs
└── references/
    └── openalex-api.md         raw API usage for agents that cannot run scripts
```
