# Foundation

<!-- Maths is written as $`...`$ and ```math fences: GitHub applies markdown
     backslash-escaping before its maths renderer, so a bare $...$ loses \; \, \{ \}
     and MathJax then fails. The code span protects them. -->

The model every `stompcad` tool is an instance of. It exists so that
correctness obligations can be **derived** rather than enumerated: state the
structure once, and what must hold follows from it.

Sections 1–7 are domain-free and describe any tool of this shape. Section 8 is
the only place a concrete tool, format or rule appears; everything the domain
contributes enters there.

This document says what the system **is**. `docs/GLOSSARY.md` says what its
terms **mean**, `docs/adr/` records the decisions **taken**, and `CLAUDE.md`
holds the rules that **bind** the code. Where this document and an ADR
disagree, the ADR is the authority and this document is stale — fix it.

---

## 1. Notation

Every symbol used anywhere below. Nothing is introduced in prose.

### Sets

| Symbol | Reads as | Definition |
| --- | --- | --- |
| $`X`$ | the input space | what a tool accepts. $`x \in X`$ is one input. |
| $`D`$ | the model space | the canonical value a tool computes. $`d \in D`$. |
| $`F`$ | the fact space | the statements about $`d`$ that any artefact may carry. |
| $`A_i`$ | the artefact space of format $`i`$ | the emitted bytes of one format. $`a \in A_i`$. |
| $`O_i`$ | the option space of format $`i`$ | presentation choices. $`o \in O_i`$. |
| $`C`$ | the configuration space | resolved settings governing $`P`$. $`c \in C`$. |
| $`\Sigma`$ | the severity space | totally ordered; $`\Sigma`$ is shared by every instance. |

### Operators

| Symbol | Signature | Reads as |
| --- | --- | --- |
| $`P`$ | $`X \times C \to D`$ | the **pipeline**: read, canonicalise, and fold the stages. |
| $`E_i`$ | $`D \times O_i \to A_i`$ | the **emitter** for format $`i`$. |
| $`\pi_i`$ | $`A_i \rightharpoonup F`$ | the **recovery** of format $`i`$: a parser. Partial — see §3. |
| $`\rho_i`$ | $`D \to F`$ | the **restriction** to format $`i`$: the model's facts, narrowed to what $`i`$ can express. |
| $`S`$ | $`D \to D`$ | one **stage** of the fold inside $`P`$. |
| $`\Delta`$ | $`D \to \Sigma^{*}`$ | the **findings** a model carries. |
| $`\varepsilon`$ | $`\Sigma \cup \{\bot\} \to \mathbb{Z}`$ | the **status reduction**: worst finding to exit code, $`\bot`$ for none. |

### Relations and indices

| Symbol | Reads as |
| --- | --- |
| $`x \sim y`$ | $`x`$ and $`y`$ **denote** the same input (Definition 2). |
| $`i, j`$ | format indices, $`1 \le i, j \le n`$. |
| $`k`$ | instance index, when several tools are composed (§6). |

$`c`$ is written explicitly only where it matters. Elsewhere $`P(x)`$ abbreviates
$`P(x, c)`$ for a fixed $`c`$, and every statement is read as holding per
configuration. This is a notational convenience, never a claim that behaviour
is configuration-independent.

---

## 2. A tool

> **Definition 1 (instance).** A tool is a tuple
> ```math
> \big(X,\ D,\ F,\ P,\ \{E_i\}_{i=1}^{n},\ \{\pi_i\}_{i=1}^{n},\ \{\rho_i\}_{i=1}^{n}\big)
> ```
> in which $`P`$ computes one model from one input, and each format $`i`$ has an
> emitter, a recovery, and a restriction.

Its observable behaviour is the fan-out over a single model:

```math
T(x) \;=\; \big\{\, E_1(P(x), o_1),\ \ldots,\ E_n(P(x), o_n) \,\big\}
```

$`P`$ runs **once**. Every artefact of one invocation is a function of the same
$`d`$, which is what makes agreement between them a property to prove rather than
a coincidence to hope for.

---

## 3. Recovery and restriction

> **Definition 2 (denotational equivalence).** $`x \sim y`$ when $`x`$ and $`y`$
> denote the same content — they differ only in ways the input format permits
> and the domain does not distinguish. $`\sim`$ is part of a tool's
> specification; it cannot be derived from the types.

> **Definition 3 (expressive range).** $`\rho_i(d)`$ is the image of $`d`$ under
> the facts format $`i`$ can carry. $`\pi_i`$ is partial for the same reason: a
> format states some of $`F`$ and is silent about the rest.

$`\rho_i`$ and $`\pi_i`$ are the pair that makes fidelity checkable. Without them
an artefact can only be judged *well-formed*; with them it can be judged
*faithful*. They are the reason §7's instrument table has a semantic column at
all.

---

## 4. Theorems

> **T1 — Determinism.** $`P`$ is a pure function. For a fixed $`x`$ and $`c`$ it
> yields the same $`d`$ in every run and every process.

Not idempotence: $`P(P(x))`$ does not type-check, since $`D \not\subseteq X`$.
Idempotence belongs to the stages (§5).

> **T1′ — Denotational invariance.**
> ```math
> x \sim y \;\implies\; P(x) = P(y)
> ```

$`P`$ factors through the quotient $`X/{\sim}`$: whatever $`\sim`$ declares
insignificant cannot reach the output, so no rule inside $`P`$ may consult it.
T1′ presupposes T1 and is strictly stronger.

> **T2 — Fidelity.** For every format $`i`$, every $`d`$ in the image of $`P`$, and
> **every** $`o \in O_i`$:
> ```math
> \pi_i\big(E_i(d, o)\big) \;=\; \rho_i(d)
> ```

An artefact states exactly the facts the model holds, narrowed to what the
format expresses — no more, no less, and independent of presentation.

> **T3 — Presentation neutrality** *(corollary of T2, from its $`\forall o`$)*.
> ```math
> \pi_i\big(E_i(d, o)\big) \;=\; \pi_i\big(E_i(d, o')\big) \qquad \forall\, o, o' \in O_i
> ```

Options may change bytes. They may not change facts.

> **T4 — Agreement** *(corollary of T2)*.
> ```math
> \pi_i\big(E_i(d, o)\big) \;=\; \pi_j\big(E_j(d, o')\big) \quad \text{on } \text{dom}\,\pi_i \cap \text{dom}\,\pi_j
> ```

Two artefacts of one invocation never disagree about a fact they both state.
They may differ in *which* facts they state; never in the value of a shared one.

**Remark (why the star, not the pairs).** T4 is derived, and that is the point.
Verifying $`n`$ instances of T2 against the model is stronger than verifying
$`\binom{n}{2}`$ pairwise agreements, because pairwise agreement can be
*uniformly wrong*: every emitter agreeing about a fact the model never held
satisfies all pairs and no instance of T2. It is also fewer tests, and it
localises a failure to one emitter rather than to a pair. **The model is the
reference; each artefact is checked against it.**

---

## 5. Stage idempotence

Distinct from T1, one level down. For the stages composing $`P`$:

```math
S\big(S(d)\big) \;=\; S(d)
```

> **Rule.** A property with no falsifying case is not verified by asserting it.
> Where a stage compares by exact equality on values it has itself made exact,
> its idempotence is a theorem about the type rather than about the code: no
> mutation can falsify it, and a test of it passes regardless. Assert
> idempotence only where re-application could plausibly differ; elsewhere
> record why it cannot and write no test.

---

## 6. Composition

Instances chain. Write $`P_k`$, $`E_{k,i}`$, $`\pi_{k,i}`$ for instance $`k`$. Two
kinds of composition occur, and each imposes a condition.

**Chaining — one tool's artefact is another's input.**

```math
d_2 \;=\; P_2\Big(\big\langle\, x_2,\ E_{1,i}\big(P_1(x_1), o\big) \,\big\rangle\Big)
```

> **T5 — Composability.** Chaining is sound exactly when T2 holds for the
> format on the seam: instance 2 recovers from the artefact precisely the facts
> instance 1 held.

This is why T2 is not merely a testing convenience. A format that no $`\pi`$ can
read is a dead end, and a $`\pi`$ that disagrees with $`\rho`$ silently corrupts
every tool downstream of it. The recovery must exist and must be the inverse of
the emitter **on facts**, though never on bytes.

**Orchestration — one invocation drives several instances and reports once.**

```math
\varepsilon\Big(\max_k \max \Delta\big(d_k\big)\Big)
```

> **T6 — Uniform reduction.** The orchestrator's status is the reduction of the
> worst finding across every instance it ran.

For that maximum to be defined, $`\Sigma`$, its ordering, and $`\varepsilon`$ must
be **one** definition shared by all instances rather than one per tool. A
second copy of the ordering is a second chance to disagree about what a warning
is. This is the obligation ADR-0009's shared contracts exist to discharge.

---

## 7. Equivalence, not bytes

T2, T4 and T5 are equalities in $`F`$, not in $`A_i`$. **Semantic equivalence is
the requirement; byte equality is a sound instrument for it in some places and
a false one in others.**

Byte equality is unsound wherever an artefact records something incidental to
its facts — a path, a timestamp, a tool version, a locale-dependent glyph, a
counter the writing library appends. Such a value differs between two runs that
are semantically identical, and is identical between two runs that are not.

The instrument follows from whether both sides of the comparison come from the
same code:

| Property | Both sides from | Sound instrument |
| --- | --- | --- |
| T1 determinism | same code, two runs | **bytes** |
| T1′ denotational invariance | same code, $`\sim`$-equivalent inputs | **bytes** |
| T2 fidelity | model versus artefact | **semantic** — via $`\pi_i`$ |
| T3 presentation neutrality | one emitter, two option sets | **semantic** |
| T4 agreement | two formats | **semantic** |
| T5 composability | producer's model versus consumer's read | **semantic** |
| Regression against a reference | recorded expectation | **semantic** — a recorded $`\rho_i(d)`$, never a recorded $`a`$ |

The last row is why a golden *artefact* rots and a golden *fact-set* does not: a
change to presentation breaks the first and leaves the second alone, while a
change to a value breaks both.

---

## 8. Instances

The only section in which the domain appears.

| | $`X`$ | $`D`$ | artefacts $`A_i`$ | $`\sim`$ |
| --- | --- | --- | --- | --- |
| `stompdrill` | vector artwork of a panel | the drill data | CNC files for the machine, dimensioned drawings for the operator, an interchange document, and the cut solid | same geometry regardless of the order elements appear in the file |
| `stompcollider` | a board model and a drilled enclosure | the docking result | the assembled solid, and a report of what seated and what fouled | same geometry regardless of element order, and regardless of which of two identical parts is named first |
| `stompcad` | a project | the orchestration result | the combined outputs of the instances it drove, and one report over all of them | inherited from the instances |

Chaining (§6, T5) occurs where `stompdrill`'s cut solid becomes part of
`stompcollider`'s input, and where either tool's interchange document is read
back. Orchestration (§6, T6) is `stompcad`'s whole purpose.

Where each tool's $`\sim`$, $`F`$ and stage set are fixed:

- what $`P`$ may decide, and against which answer sets — ADR-0002, ADR-0003
- what $`\sim`$ ignores, and the ordering that follows — ADR-0006
- what $`F`$ holds in common across tools, and why — ADR-0009

**The domain is not in the shape.** It is in the content of $`F`$, the definition
of $`\sim`$, and the decisions inside $`P`$ — and only there. A tool that does not
fit §§1–7 is not a tool of this system.

---

## 9. What this obliges

Each theorem is a family of tests, not a single one.

| | Obligation |
| --- | --- |
| T1 | emit twice in fresh processes; compare bytes. |
| T1′ | transform an input within its $`\sim`$-class; compare bytes. Widen the transformation as the class widens. |
| T2 | one $`\pi_i`$ per format, and one test per format against the model. |
| T3 | for each emitter, vary its options; compare recovered facts. |
| T4 | free, given T2. Assert only where a shared fact is easy to get wrong independently in two formats. |
| T5 | for each seam, round-trip the producer's model through the consumer's read. |
| T6 | drive instances with findings of differing severity; assert one status. |

Two standing rules govern all of them. **A test must fail when the behaviour it
names is removed** — the obligation is falsifiability, not assertion. And where
a theorem holds trivially because the code cannot express its violation, record
why and omit the test rather than committing a tautology.
