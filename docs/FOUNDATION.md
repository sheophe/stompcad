# Foundation

The mathematical model every `stompcad` tool is an instance of. It exists so
that correctness obligations can be *derived* rather than enumerated: state the
structure once, and what must be verified follows from it.

This document says what the system **is**. `docs/GLOSSARY.md` says what its
terms **mean**, `docs/adr/` records the decisions **taken**, and `CLAUDE.md`
holds the rules that **bind** the code. Where this document and an ADR
disagree, the ADR is the authority and this document is stale — fix it.

## Objects

| Symbol | Is | Realised by |
| --- | --- | --- |
| $I$ | an input | Illustrator artwork; later, a board model and a drilled case |
| $D$ | the canonical model | `DrillData`; later, `DockData` |
| $A_i$ | an artefact in format $i$ | the Excellon file, the JSON document, the SVG and PDF sheets, the STEP solid |
| $F$ | the shared fact space | hole positions, diameters, drill sequence, tool assignments, the reference outline, enclosure identity, diagnostics, provenance |
| $O_i$ | the options of format $i$ | `indent`, `scale`, `title` — presentation, never content |

## Operators

$$P : I \to D \qquad E_i : D \times O_i \to A_i$$

$P$ is the whole read-and-process path: source, quantisation, then the stage
fold. $E_i$ is one emitter. The system is the fan-out

$$T(I) = \{\, E_1(P(I)),\ \ldots,\ E_n(P(I)) \,\}$$

Configuration is suppressed throughout: properly $P_c$ and $E_{i,o}$, and every
statement below is read as holding for each fixed $c$. Suppressing it is a
notational convenience, not a claim that behaviour is config-independent.

Two further maps carry the whole verification argument:

$$\pi_i : A_i \rightharpoonup F \qquad \rho_i : D \to F$$

$\pi_i$ **recovers** facts from an emitted artefact — a parser. It is partial
because a format represents only some of $F$: an Excellon file states no title,
a drawing states no G-code. $\rho_i$ is the model's own facts restricted to
what format $i$ can express. Together they say what it means for an artefact to
be *faithful* rather than merely *well-formed*.

## The theorems

**T1 — Determinism.** $P$ is a pure function. For a fixed input and
configuration it yields the same $D$ every time, in every process.

> Not idempotence: $P(P(x))$ does not type-check, because $D$ is not in $P$'s
> domain. Idempotence is a property of the *stages*, stated separately below.

**T1′ — Geometric invariance.** Let $I_1 \sim I_2$ mean the two inputs describe
the same geometry, differing only in the order their elements happen to appear.
Then

$$I_1 \sim I_2 \implies P(I_1) = P(I_2)$$

$P$ factors through the quotient $I/{\sim}$. Element order is not information,
so no rule may consult it. This is ADR-0006's binding invariant and it is
strictly stronger than T1.

**T2 — Fidelity.** For every format $i$, every model $d$ in the image of $P$,
and **every** choice of options $o$:

$$\pi_i\big(E_i(d, o)\big) = \rho_i(d)$$

An artefact states exactly the facts the model holds, restricted to what the
format can express — no more, no less, and independent of presentation.

**T3 — Presentation neutrality** *(corollary of T2's $\forall o$)*.

$$\pi_i\big(E_i(d, o)\big) = \pi_i\big(E_i(d, o')\big) \quad \forall o, o' \in O_i$$

Options may change bytes. They may not change facts. This is ADR-0001's
"emitters only translate frames, convert units, format, and serialise", stated
so that it can be tested.

**T4 — Cross-artefact agreement** *(corollary of T2)*. For any two formats,

$$\pi_i\big(E_i(d,o)\big) = \pi_j\big(E_j(d,o')\big) \quad \text{on } \operatorname{dom}\pi_i \cap \operatorname{dom}\pi_j$$

Two artefacts of one invocation never disagree about a fact they both state.
They may differ in *which* facts they state — a sheet lists the rows that fit —
but never in the value of one they share.

### Why the star, not the pairs

T4 is a consequence, not an axiom, and that is the point. Verifying $n$
statements of T2 against the model is stronger than verifying $\binom{n}{2}$
pairwise agreements, because pairwise agreement can be **uniformly wrong**: every
emitter agreeing about a hole the model never held would satisfy all pairs and
no instance of T2. It is also cheaper, and it localises a failure to one
emitter rather than to a pair.

The model is the reference. Each artefact is checked against it.

## Stage idempotence

Distinct from T1, one level down. A stage is $S : D \to D$, and the stages this
system relies on satisfy

$$S(S(d)) = S(d)$$

Snapping and routing are idempotent in this sense. A stage whose idempotence
cannot be falsified — because it compares by exact equality on values it has
already made exact — states nothing, and a test of it will pass whatever the
code does. Idempotence is worth asserting only where re-application could
plausibly differ.

## Equivalence, not bytes

T2 and T4 are equalities in $F$, not in the artefact. **Semantic equivalence is
the requirement; byte equality is sometimes a sound instrument for it and
sometimes a false one.**

Byte equality is unsound wherever an artefact records something incidental. In
this system, already observed:

- the panel's path is written as provenance into four of the five artefacts, so
  the same geometry read from two paths differs byte-wise and not in fact;
- the STEP translator appends a volatile counter to its product name, which the
  writer normalises away;
- the SVG writes `⌀` and the PDF writes `Ø`, because WinAnsi has no code point
  for the former. The glyph is a backend fact; the value after it is a panel
  fact.

So the instrument is chosen per property, by whether both sides of the
comparison come from the same code:

| Property | Both sides from | Sound instrument |
| --- | --- | --- |
| T1 determinism | same code, two runs | **bytes** |
| T1′ geometric invariance | same code, permuted input | **bytes** |
| T2 fidelity | model versus artefact | **semantic** — needs $\pi_i$ |
| T3 presentation neutrality | one code, two option sets | **semantic** |
| T4 agreement | two formats | **semantic** |
| Regression against a reference | recorded expectation | **semantic** — a recorded $\rho_i$, not a recorded file |

The last row is why a golden *artefact* rots and a golden *fact-set* does not:
a change to a title block breaks the first and leaves the second alone, while a
hole moving ten microns breaks both.

## What this obliges

Each theorem is a family of tests, not a single one:

- **T1** — emit twice in fresh processes; compare bytes.
- **T1′** — permute the input's elements; compare bytes. Extend the equivalence
  beyond permutation as other order-carrying representations are admitted.
- **T2** — one $\pi_i$ per format, and one test per format against the model.
  $\pi_{\text{json}}$ already exists as `stompmodel.codec.from_document`, and
  its round trip is the first instance of T2 proved.
- **T3** — for each emitter, vary its options and compare recovered facts.
- **T4** — free, given T2. Assert it only where a shared fact is easy to get
  wrong independently in two formats.

A property with no falsifying case is not verified by asserting it. Where a
theorem holds trivially — because the code cannot express the violation — say
so and omit the test rather than recording a tautology.

## Scope

The model is stated for one tool. `stompcollider` is another instance of it,
with $I$ a board and a drilled case, $D$ a `DockData`, and its own emitters;
`stompcad` composes instances and must therefore reduce their diagnostics and
provenance uniformly, which is what ADR-0009's shared contracts are for.

Nothing here is domain-specific. The domain enters in what $F$ contains and in
what $P$ decides — see ADR-0002 and ADR-0003 — never in the shape above.
