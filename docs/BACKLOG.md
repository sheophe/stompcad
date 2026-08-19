# Backlog

Current work that is agreed or recorded but not scheduled.

## Paired redundancy review

**Status:** Agreed, not started.

**Constraint:** Claude and Codex review the source together, preserving behaviour and
public interfaces. Target about a 15% reduction in source lines through consolidation,
especially repeated drawing, formatting, parsing, and test helpers. Architectural
rationale belongs in ADRs; source reduction must not remove required documentation or
features.

**Acceptance:** The source is about 15% smaller with no loss of function. The full suite
passes, and targeted mutation checks demonstrate that each refactor preserved behaviour.

## Adopt mypy `strict` on `src/stompdrill`

**Status:** Agreed, not started.

**Constraint:** Annotate one module at a time and keep the type gate green throughout.
`Pipeline.__getitem__` needs overloads for `int` and `slice`; enable `strict` only after
the implementation is clean. Keep each module's typing change in its own commit.

**Acceptance:** `strict = true` is enabled for `src/stompdrill`, `mypy src/stompdrill` reports no
errors, and the test suite passes.

## Measure and, if necessary, reduce package import cost

**Status:** Noted; no implementation agreed.

**Constraint:** `import stompdrill` currently imports `pikepdf` because the package root
exports `AiPdfSource`. Do not introduce lazy loading without evidence that this cost is
material. If measurement justifies a change, preserve the root import contract and keep
`__all__`, `dir()`, and attribute access consistent.

**Acceptance:** A reproducible benchmark closes the item if the cost is immaterial. If the
cost is material, the implemented change demonstrates an improvement, avoids eager
`pikepdf` loading, preserves `AiPdfSource` at the package root, and passes the full suite.

## Cover every chain-dimension segment

**Status:** Confirmed gap, not scheduled.

**Constraint:** Exercise a row with at least three holes so omitting the first or last
consecutive pair cannot pass accidentally.

**Acceptance:** The test checks that each row has `len(stations) - 1` `dim-line` elements,
and a mutation that skips the first pair fails that test.

## ISO 3098 lettering

**Status:** Noted; no implementation agreed.

**Constraint:** The PDF sheet letters in base-14 Helvetica, so it is not ISO 3098
conformant. A true technical face (osifont, ISOCPEUR) means vendoring a TTF, subsetting
it, and clearing its licence — and, because both drawing backends share one text-fitting
estimate, adopting real font metrics for one would make the two sheets truncate the same
string at different points. Both backends move together or neither does.

**Acceptance:** Both sheets letter in the same conformant face, the licence is recorded
alongside the vendored file, and the agreement tests still show the two sheets stating the
same facts about every row they both list.
