# phd-skill-catchup

An AI agent skill that helps researchers stay up to date. It learns your research interests
from your ORCID iD, your Zotero library, the publication list in your CV or a folder of
PDFs. You pick the topics you want to catch up on, and it finds recent publications on
[OpenAlex](https://openalex.org), keeps the ones that are really on topic, and gives you
for each paper one sentence on what it found and one on why it matters to you.

## Quick start

**1. Download the package**

[Download phd-skill-catchup.zip](https://github.com/cheniode/phd-skill-catchup/releases/latest/download/phd-skill-catchup.zip)

The zip file is ready to use. You do not need to unpack or edit it.

**2. Upload it to your AI agent**

| Agent | How to add the skill |
|---|---|
| Claude (web and desktop app) | Settings > Capabilities > Skills > upload the zip file |
| Claude Code | Unpack the zip into `~/.claude/skills/` |
| OpenAI Codex CLI, Gemini CLI, Cursor, GitHub Copilot and others | Unpack the zip into the agent's skills folder, usually `~/.agents/skills/`. Check your agent's documentation for the exact place |

**3. Set up your OpenAlex key**

This is the only thing to set up. OpenAlex is the free database the skill searches. The key
is free, and with it searches are fast and complete.

1. Create a free account at https://openalex.org.
2. Open https://openalex.org/settings/api and copy your key.
3. Store the key where your agent finds it:

| Where you use the skill | Where to put the key |
|---|---|
| Claude or ChatGPT (web and desktop app) | Create a Project and add this line to its instructions: `OpenAlex key: <your key>`. Use the skill in chats inside that Project |
| Claude Code, Codex and other terminal agents | Create a file named `.config` in the installed skill folder with this line: `OPENALEX_API_KEY=<your key>` |

The key only counts how much you use OpenAlex. It gives no access to your account or data,
and you can replace it on the same page at any time.

If you skip this step the skill still works, but searches are slow at busy times and you
are limited to about one run per day.

**4. Use it**

Ask your agent, for example:

> Help me catch up on recent papers in my field.

The agent asks what it may use to learn your interests. You can give it any of these:

- your ORCID iD
- a file exported from Zotero (in Zotero: File > Export Library, format CSV)
- the publication list from your CV, pasted into the chat
- PDFs of papers you have read or written

None of these needs a password or an account. By default the skill covers the last 90
days. Ask for a different period if you want one.

## What has been tested

The skill was tested with Claude Code and with OpenAI Codex CLI on Linux. It follows the
open [Agent Skills](https://agentskills.io) format, so it should work in other agents that
support that format, but uploading the zip to the Claude and ChatGPT apps has not been
tested yet. Please open an issue if it does not work in your agent.

The helper scripts need Python 3.8 or later and no additional packages. They run on Linux,
macOS and Windows.

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
│   └── scan_pdfs.py            title, DOI and first-page text from a folder of PDFs
└── references/
    └── openalex-api.md         raw API usage for agents that cannot run scripts
```

Keys are looked up in this order: the `OPENALEX_API_KEY` environment variable, a file given
with `--key-file`, the `.config` file in the skill folder. Reading a private Zotero library
through zotero.org, instead of an export file, needs a read-only Zotero key as
`ZOTERO_API_KEY=<your key>` in the same `.config` file.

`.config` is listed in `.gitignore`. To build the package, run `./build.sh`. It leaves out
`.config`, so your own key never ends up in the zip file.
