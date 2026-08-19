# Domain Docs

How the engineering skills should consume this repo's domain documentation when
exploring the codebase.

One glossary serves the whole repository: `docs/GLOSSARY.md`, with `docs/adr/`
beside it. There is no root `CONTEXT.md` and no `CONTEXT-MAP.md` — this repo
keeps a single sectioned glossary rather than one per context, so do not go
looking for either.

## Before exploring, read these

- **`CLAUDE.md`** at the repo root — loaded automatically, and currently the
  repo's working glossary. Its *Domain invariants* and *Parsing constraints*
  sections define the vocabulary (canonical frame, answer set, quantisation
  boundary, branded length units, reference outline, tool block) that the code
  and its tests already speak.
- **`docs/GLOSSARY.md`** — the glossary. Its Scope section states what belongs
  in it and what does not.
- **`docs/adr/`** — read the ADRs that touch the area you are about to work in.
  There are seven, `0001`–`0007`; `CLAUDE.md`'s *Architecture* section lists
  what each one decides, so read that list first and open only what is
  relevant.

If a document listed here does not exist, **proceed silently**. Don't flag its absence;
don't suggest creating it upfront. The `/domain-modeling` skill (reached via
`/grill-with-docs` and `/improve-codebase-architecture`) creates it lazily when
terms actually get resolved.

## File structure

```
/
├── CLAUDE.md                          ← the rules that govern the vocabulary
├── docs/GLOSSARY.md                   ← the glossary itself
├── docs/adr/
│   ├── 0001-pipeline-and-emitter-adapters.md
│   ├── …
│   └── 0008-workspace-and-shared-geometry-core.md
└── src/aidrill/
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor
proposal, a hypothesis, a test name), use the term as the glossary defines it.
Don't drift to synonyms it avoids.

If the concept you need isn't in the glossary yet, that's a signal — either
you're inventing language the project doesn't use (reconsider) or there's a
real gap (note it for `/domain-modeling`).

Prose uses British spelling; identifiers use established American spelling.
`CLAUDE.md`'s *Documentation rules* is authoritative on this and on ADR
formatting (figure numbering, the ten-line docstring cap).

## Flag ADR conflicts

`docs/adr/` is the authority for architectural decisions, and an ADR is
updated and accepted *before* the architecture changes in code. So a
contradiction is never something to resolve silently in your output — surface
it:

> _Contradicts ADR-0003 (quantisation boundary) — but worth reopening because…_
