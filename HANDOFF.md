# Handoff

State of the `phd-skill-catchup` project at the end of the session of 29–30 September 2026.

## What this is

An AI agent skill that helps a researcher catch up on recent literature. It learns their
interests from an ORCID iD, a Zotero library, a CV publication list or a folder of PDFs,
lets them choose topics, searches OpenAlex for the last 90 days, screens the results for
relevance, and presents each paper with one sentence on its findings and one on why it
matters to them. It can then export the selected papers for a reference manager.

## Where things are

| Path | Contents |
|---|---|
| `phd-skill-catchup/` | The skill itself: `SKILL.md`, `scripts/`, `references/`, `evals/` |
| `README.md` | User-facing install and setup |
| `build.sh` | Builds `dist/phd-skill-catchup.zip` without `.config` or test files |
| `phd-skill-catchup-workspace/` | Test runs, graded results, fixtures. Git-ignored |
| `phd-skill-catchup/.config` | The personal OpenAlex key. Git-ignored, never published |

GitHub: https://github.com/cheniode/phd-skill-catchup (public).
Latest release: **v1.2.0**. Install link used in the README and release notes:
`https://github.com/cheniode/phd-skill-catchup/releases/latest/download/phd-skill-catchup.zip`

Installed for local use at `~/.claude/skills/phd-skill-catchup/`, including its own
`.config` with the key.

## Scope decision

The skill targets agents that run on the user's own computer: **Claude Code** and **OpenAI
Codex CLI**, both tested. The Claude and ChatGPT web apps cannot reach `api.openalex.org`
from the skill sandbox, so the skill no longer claims to support them; if it cannot
connect it says so plainly instead of improvising a digest. A hosted MCP connector was
considered and rejected as too much upkeep for now.

## How keys are handled

Keys are optional; the skill never asks for one before delivering results. Lookup order:
the `OPENALEX_API_KEY` environment variable, a file passed with `--key-file`, then
`OPENALEX_API_KEY=...` in `.config` in the skill folder. A rejected key falls back to
keyless use. `ZOTERO_API_KEY` works the same way, and is only needed for reading a private
zotero.org library instead of an export file.

Without a key OpenAlex throttles anonymous searches and allows about one run a day. With
the key, test runs took 5–6.5 minutes instead of 15–25.

## What was verified

**Comparison tests (iteration 2, `phd-skill-catchup-workspace/iteration-2/`).** Five
scenarios: ORCID with the default window; a CV list with 60 days; a non-technical user
with a Zotero export; an ORCID whose OpenAlex record merges namesakes; and the first
scenario run by Codex instead of Claude. Each output was graded by Codex against six
checks (time window, interests proposed with evidence, links, findings plus relevance
sentence, screening counts, relevance specific to the user), plus extra checks for the
Zotero and namesake cases.

Result: **32 of 35 checks passed with the skill, 12 of 29 without it.** Open
`iteration-2/review.html` for the side-by-side outputs and grades.

**Accuracy of the summaries.** Codex compared every findings sentence with the paper's
abstract, offline. Iteration 2: 99 of 113 fully supported, 4 minor issues, 1 unsupported,
9 without an abstract. Verdicts in `iteration-2/accuracy/`.

**Caveats on this evidence.** One run per configuration, so the ± figures in
`benchmark.md` are spread across tests, not repeated runs. The checks were written from
the original specification, so they favour the skill's format; an unaided agent can
produce a useful digest and still fail several. Two of the without-skill runs are reused
from iteration 1 and ran without a key. One without-skill run had to be done on Claude
Opus after a safety classifier stopped two attempts.

## Known gaps

- **Never tested:** a real Zotero export from a live library (fixtures were generated);
  the Zotero local-API and web-API routes; macOS and Windows; importing a generated
  `.bib` into Zotero to confirm it round-trips.
- **The README section "Not using Claude Code or Codex?"** is a placeholder: *"The author
  maintains a separate free tool… Its name and link will be added here."* It needs the
  name, URL and one sentence. No new release is required, since the link is not in the
  package.
- **Genome-editing and similar sensitive topics:** during testing a safety classifier
  stopped one write-up about a paper on base editing in human embryos. The agent
  continued and listed that paper by title only. This can happen again and the skill
  cannot control it.
- **Summaries come from abstracts only.** Nothing reads full texts.

## Repository notes

History was rewritten on 29 September to remove the test workspace from the initial
commit, and force-pushed. The old commits (`173da46`, `ae77c64`) may remain reachable by
hash on GitHub until it garbage-collects; ask GitHub support if that matters. A local
branch `backup-before-rewrite` still holds the old history — it contains the workspace, so
do not push it; delete it with `git branch -D backup-before-rewrite` when no longer needed.

`.gitignore` covers `.config`, `phd-skill-catchup-workspace/`, `dist/` and `*.zip`. A stray
`phd-skill-catchup.zip` in the project root contains the personal key and must not be
shared; build packages with `./build.sh`, which writes a clean zip to `dist/`.

`phd-skill-catchup_plot.excalidraw` in the project root is untracked and was not created
during this session.

## Releasing a new version

```bash
./build.sh                         # writes dist/phd-skill-catchup.zip, refuses if .config slipped in
gh release create vX.Y.Z dist/phd-skill-catchup.zip --target main --title "phd-skill-catchup X.Y.Z" --notes "…"
```
The README's download link always points at the newest release, so it needs no change.

## Sensible next steps

1. Fill in the alternative-tool section of the README.
2. Import a generated `.bib` into Zotero and confirm the entries look right.
3. Re-run the tests against the current skill: the iteration-2 results predate the export
   feature and the fixes made after that round.
4. Ask a colleague who is not technical to install it from the README alone and watch
   where they get stuck.
