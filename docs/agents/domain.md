# Using the domain documentation

Read the relevant documentation before exploring or changing domain behaviour:

- [CLAUDE.md](../../CLAUDE.md) collects agent instructions. Its domain invariants
  and parsing constraints describe rules the code and tests rely on.
- [The glossary](../GLOSSARY.md) defines enclosure, drilling and board-placement
  terms.
- [The architecture overview](../ARCHITECTURE.md) explains the packages and
  processing steps.
- [The ADRs](../adr/) record accepted decisions. Use the index in
  [CLAUDE.md](../../CLAUDE.md#architecture) to find the decisions relevant to
  your task.

This repository uses one sectioned glossary. There is no `CONTEXT.md` or
`CONTEXT-MAP.md`. If a referenced domain document is absent, continue with the
available context; `/domain-modeling` can create it when terms need resolving.

Use the glossary's technical distinctions in issues, proposals, tests and
explanations. You can explain a term in ordinary language without renaming the
underlying concept. If a needed concept has no entry, check whether an existing
term covers it before proposing an addition.

Follow the [writing conventions](../../CONTRIBUTING.md#writing-style). Prose
uses British spelling; identifiers keep their established spelling.

When code or documentation conflicts with an ADR, identify the decision and
explain the difference. Investigate which description is current. Architectural
changes require an updated and accepted ADR before implementation; editing
prose should preserve the decision.
