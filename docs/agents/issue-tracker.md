# Local issue tracker

Store issues and working specs as Markdown files under `.scratch/`. Use these
files for issue-tracker operations; this workflow does not publish external
issues or pull requests.

## File conventions

- Give each feature a directory: `.scratch/<feature-slug>/`.
- Store its spec at `.scratch/<feature-slug>/spec.md`.
- Give each implementation ticket a separate file:
  `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01`.
- Put a `Status:` line near the top of each issue. Use the values in
  [triage labels](triage-labels.md) for triage workflows.
- Append comments and conversation history under a `## Comments` heading.

When a skill asks you to publish an issue, create the corresponding local file.
When it asks you to fetch a ticket, read the path or issue number supplied by
the user.

These working directories are ignored by Git:

| Directory | Contents |
| --- | --- |
| `.scratch/` | Issues, working specs and wayfinder maps |
| `.superpowers/sdd/` | Superpowers subagent-development workspace |
| `docs/superpowers/` | Superpowers specs and plans |

Record lasting architectural decisions in [ADRs](../adr/) and domain
definitions in the [glossary](../GLOSSARY.md).

## Wayfinder operations

A wayfinder effort has a map and one child file per ticket:

- Map: `.scratch/<effort>/map.md`, with Notes, Decisions-so-far and Fog sections.
- Tickets: `.scratch/<effort>/issues/NN-<slug>.md`, numbered from `01`, with the
  question in the body. Use `Type: research`, `prototype`, `grilling` or `task`
  to describe the ticket, and `Status: claimed` or `resolved` as work proceeds.
- Dependencies: list ticket numbers in `Blocked by: NN, NN`. A ticket is
  unblocked when every listed ticket is resolved.

To find the next ticket, scan for open, unblocked and unclaimed tickets and
choose the lowest number. Set `Status: claimed` and save before starting work.

On completion, append the answer under `## Answer`, set `Status: resolved`, and
append a short result and a link to the ticket in the map's Decisions-so-far
section.
