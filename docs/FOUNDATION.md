# Foundation

<!-- Maths is written as $`...`$ and ```math fences: GitHub applies markdown
     backslash-escaping before its maths renderer, so a bare $...$ loses \; \, \{ \}
     and MathJax then fails. The code span protects them. -->

Each tool in this project computes one model and uses it to produce several
artefacts. This document defines that structure and the properties needed to
keep those artefacts consistent.

Sections 1–7 describe the general model. Section 8 maps it to the tools and
formats used here, and section 9 describes the resulting test obligations.

The [glossary](GLOSSARY.md) explains the terms, the [ADRs](adr/) record design
decisions, and [CLAUDE.md](../CLAUDE.md) gives the implementation rules. If this
document conflicts with an ADR, follow the ADR and update this document.

---

## 1. Notation

The tables below define the symbols used in the model.

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
configuration. Behaviour can depend on the configuration.

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

$`P`$ runs once. Every artefact of one invocation is a function of the same
$`d`$, so each can be checked against a common reference.

---

## 3. Recovery and restriction

> **Definition 2 (denotational equivalence).** $`x \sim y`$ when $`x`$ and $`y`$
> denote the same content — they differ only in ways the input format permits
> and the domain does not distinguish. $`\sim`$ is part of a tool's
> specification; it cannot be derived from the types.

> **Definition 3 (expressive range).** $`\rho_i(d)`$ is the image of $`d`$ under
> the facts format $`i`$ can carry. $`\pi_i`$ is partial for the same reason: a
> format states some of $`F`$ and is silent about the rest.

$`\rho_i`$ selects the facts a format should contain, and $`\pi_i`$ recovers the
facts it actually contains. Comparing them checks fidelity as well as whether
the artefact is well-formed. Section 7 describes where to use this semantic
comparison.

---

## 4. Theorems

> **T1 — Determinism.** $`P`$ is a pure function. For a fixed $`x`$ and $`c`$ it
> yields the same $`d`$ in every run and every process.

Determinism concerns repeated runs on the same input. Stage idempotence (§5)
concerns applying a stage to its own result. The expression $`P(P(x))`$ does not
type-check, since $`D \not\subseteq X`$.

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

An artefact states exactly the model facts its format can express, regardless
of presentation options.

> **T3 — Presentation neutrality** *(corollary of T2, from its $`\forall o`$)*.
> ```math
> \pi_i\big(E_i(d, o)\big) \;=\; \pi_i\big(E_i(d, o')\big) \qquad \forall\, o, o' \in O_i
> ```

Presentation options may change bytes while preserving the recovered facts.

> **T4 — Agreement** *(corollary of T2)*.
> ```math
> \pi_i\big(E_i(d, o)\big) \;=\; \pi_j\big(E_j(d, o')\big) \quad \text{on } \text{dom}\,\pi_i \cap \text{dom}\,\pi_j
> ```

Two artefacts of one invocation agree on every fact they both state. Each
format may express a different subset of the model's facts.

**Checking against the model.** Verifying $`n`$ instances of T2 establishes T4
and also checks fidelity. The $`\binom{n}{2}`$ pairwise comparisons alone cannot
do that: every emitter could produce the same incorrect value. Checking each
artefact against the model uses fewer comparisons and identifies the emitter
responsible when one fails.

---

## 5. Stage idempotence

Applying a stage a second time should leave its result unchanged. For the
stages composing $`P`$:

```math
S\big(S(d)\big) \;=\; S(d)
```

> **Rule.** Test idempotence where reapplying a stage could plausibly change its
> result.
> Where a stage compares by exact equality on values it has itself made exact,
> its idempotence is a theorem about the type rather than about the code: no
> mutation can falsify it, so an assertion would pass regardless. In that case,
> record why the result cannot change and omit the test.

---

## 6. Composition

Tools can exchange artefacts or run under a shared orchestrator. Write $`P_k`$,
$`E_{k,i}`$, $`\pi_{k,i}`$ for instance $`k`$. Each kind of composition has a
condition to satisfy.

**Chaining — one tool's artefact is another's input.**

```math
d_2 \;=\; P_2\Big(\big\langle\, x_2,\ E_{1,i}\big(P_1(x_1), o\big) \,\big\rangle\Big)
```

> **T5 — Composability.** Chaining is sound exactly when T2 holds for the
> format on the seam: instance 2 recovers from the artefact precisely the facts
> instance 1 held.

The receiving tool needs a recovery that preserves the producer's facts. If
$`\pi`$ disagrees with $`\rho`$, the receiving tool works from incorrect data.
Recovery must therefore invert the emitter on facts; it need not reproduce
the original bytes.

**Orchestration — one invocation drives several instances and reports once.**

```math
\varepsilon\Big(\max_k \max \Delta\big(d_k\big)\Big)
```

> **T6 — Uniform reduction.** The orchestrator's status is the reduction of the
> worst finding across every instance it ran.

For that maximum to be defined, all instances must share one definition of
$`\Sigma`$, its ordering and $`\varepsilon`$. The shared contracts in
[ADR-0009](adr/0009-shared-model-package-and-dependency-order.md) keep severity
and exit-status reduction consistent across tools.

---

## 7. Choosing a comparison

T2, T4 and T5 compare facts in $`F`$. Byte equality in $`A_i`$ is useful only
where it reliably represents that semantic comparison.

An artefact can include incidental values such as paths, timestamps, tool
versions, locale-dependent glyphs or counters added by the writing library.
These can change while the facts remain the same. Incidental values can also
stay the same when the facts change, so they do not establish semantic
agreement.

Choose the comparison according to the property being checked:

| Property | Both sides from | Sound instrument |
| --- | --- | --- |
| T1 determinism | same code, two runs | **bytes** |
| T1′ denotational invariance | same code, $`\sim`$-equivalent inputs | **bytes** |
| T2 fidelity | model versus artefact | **semantic** — via $`\pi_i`$ |
| T3 presentation neutrality | one emitter, two option sets | **semantic** |
| T4 agreement | two formats | **semantic** |
| T5 composability | producer's model versus consumer's read | **semantic** |
| Regression against a reference | recorded expectation | **semantic** — a recorded $`\rho_i(d)`$, never a recorded $`a`$ |

For regression tests, a recorded fact set allows presentation to change without
breaking the test. A changed fact still fails the comparison. A recorded
artefact would fail for either kind of change.

---

## 8. Instances

The model applies to the two current tools and the proposed orchestrator:

| | $`X`$ | $`D`$ | artefacts $`A_i`$ | $`\sim`$ |
| --- | --- | --- | --- | --- |
| `stompdrill` | vector artwork of a panel | the drill data | CNC files for the machine, dimensioned drawings for the operator, an interchange document, and the cut solid | same geometry regardless of the order elements appear in the file |
| `stompcollider` | a board model and a drilled enclosure | the docking result | the assembled solid, and a report of what seated and what fouled | same geometry regardless of element order, and regardless of which of two identical parts is named first |
| `stompcad` (proposed) | a project | the orchestration result | the combined outputs of the instances it drove, and one report over all of them | inherited from the instances |

Chaining (§6, T5) occurs where `stompdrill`'s cut solid becomes part of
`stompcollider`'s input, and where either tool's interchange document is read
back. The proposed `stompcad` command would provide orchestration (§6, T6).
It is not implemented in this workspace; the currently installed commands are
`stompdrill` and `stompcollider`.

The following decisions define each tool's $`\sim`$, $`F`$ and stages:

- What $`P`$ may decide, and which answer sets it uses:
  [ADR-0002](adr/0002-domain-quantisers.md) and
  [ADR-0003](adr/0003-quantisation-boundary-and-ordering.md).
- What $`\sim`$ ignores, and the resulting ordering:
  [ADR-0006](adr/0006-toolpath-ordering-and-hole-numbering.md).
- Which facts in $`F`$ are shared across tools, and why:
  [ADR-0009](adr/0009-shared-model-package-and-dependency-order.md).

Domain-specific behaviour belongs in the content of $`F`$, the definition of
$`\sim`$ and the decisions inside $`P`$. Each tool in the system must satisfy
the structure and properties in §§1–7.

---

## 9. Test obligations

Each theorem is a family of tests, not a single one.

| | Obligation |
| --- | --- |
| T1 | emit twice in fresh processes; compare bytes. |
| T1′ | transform an input within its $`\sim`$-class; compare bytes. Widen the transformation as the class widens. |
| T2 | one $`\pi_i`$ per format, and one test per format against the model. |
| T3 | for each emitter, vary its options; compare recovered facts. |
| T4 | follows from T2. Assert separately only where a shared fact is easy to get wrong independently in two formats. |
| T5 | for each seam, round-trip the producer's model through the consumer's read. |
| T6 | drive instances with findings of differing severity; assert one status. |

A test must fail when the behaviour it names is removed. Where the code cannot
express a violation of the property, record why and omit the test.
