# Issue tracker: Local Markdown

Issues and specs for this repo live as markdown files in `.scratch/`.

This repo has no git remote, so there is no GitHub or GitLab to talk to and no
external pull requests to triage. `.scratch/` is **git-ignored**: it holds live
working state — what is being decided right now — not a record to keep. A
decision worth keeping graduates out of it, into a spec, an ADR, or
`docs/GLOSSARY.md`.

## Conventions

- One feature per directory: `.scratch/<feature-slug>/`
- The spec is `.scratch/<feature-slug>/spec.md`
- Implementation issues are one file per ticket at
  `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01` — never a
  single combined tickets file
- Triage state is recorded as a `Status:` line near the top of each issue file
  (see `triage-labels.md` for the role strings)
- Comments and conversation history append to the bottom of the file under a
  `## Comments` heading

`.scratch/` is for issues, specs and wayfinder maps. It is not the Superpowers
SDD workspace, which lives at `.superpowers/sdd/`. Nor is it
`docs/superpowers/`, which holds that workflow's specs and plans. All three are
git-ignored (a couple of files under `docs/superpowers/` predate its rule and
remain tracked). Three directories, three purposes, none of them a durable
record — that is what `docs/adr/` and `docs/GLOSSARY.md` are for.

## When a skill says "publish to the issue tracker"

Create a new file under `.scratch/<feature-slug>/` (creating the directory if
needed).

## When a skill says "fetch the relevant ticket"

Read the file at the referenced path. The user will normally pass the path or
the issue number directly.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a file with one **child** file per ticket.

- **Map**: `.scratch/<effort>/map.md` — the Notes / Decisions-so-far / Fog body.
- **Child ticket**: `.scratch/<effort>/issues/NN-<slug>.md`, numbered from `01`,
  with the question in the body. A `Type:` line records the ticket type
  (`research`/`prototype`/`grilling`/`task`); a `Status:` line records
  `claimed`/`resolved`.
- **Blocking**: a `Blocked by: NN, NN` line near the top. A ticket is unblocked
  when every file it lists is `resolved`.
- **Frontier**: scan `.scratch/<effort>/issues/` for files that are open,
  unblocked, and unclaimed; first by number wins.
- **Claim**: set `Status: claimed` and save before any work.
- **Resolve**: append the answer under an `## Answer` heading, set
  `Status: resolved`, then append a context pointer (gist + link) to the map's
  Decisions-so-far in `map.md`.
