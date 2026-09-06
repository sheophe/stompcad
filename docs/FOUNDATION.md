# Foundation

<!-- Maths is written as $`...`$ and ```math fences: GitHub applies markdown
     backslash-escaping before its maths renderer, so a bare $...$ loses \; \, \{ \}
     and MathJax then fails. The code span protects them. -->

Each tool in this project computes one model and uses it to produce several
artefacts. This document defines that structure and the properties needed to
keep those artefacts consistent.

Sections 1–7 describe the general model. Section 8 maps it to the instances,
and section 9 states the resulting verification obligations.

This document fixes the abstract model. Each instance fixes its own concrete
content: what its input space contains, what its facts are, and what its
equivalence ignores.

---

## 1. Notation

The tables below define the symbols used in the model. Every symbol used
anywhere below appears here. Nothing is introduced in prose.

### Sets

| Symbol | Reads as | Definition |
| --- | --- | --- |
| $`X`$ | the input space | what a tool accepts. $`x \in X`$ is one input. |
| $`D`$ | the model space | the canonical value a tool computes. $`d \in D`$. |
| $`F`$ | the fact space | the statements about $`d`$ that any artefact may carry. An element of $`F`$ is a finite assignment of values to facts. |
| $`A_i`$ | the artefact space of format $`i`$ | the emitted bytes of one format. $`a \in A_i`$. |
| $`O_i`$ | the option space of format $`i`$ | presentation choices for one artefact. $`o \in O_i`$. |
| $`C`$ | the configuration space | resolved settings governing the whole tool: $`P`$ and every $`E_i`$. $`c \in C`$. |
| $`\Sigma`$ | the severity space | totally ordered; $`\Sigma`$ is shared by every instance. |
| $`\Sigma^{*}`$ | the finding space | finite sequences over $`\Sigma`$, order preserved and repetition allowed. $`\langle\,\rangle`$ is the empty sequence. |

### Operators

| Symbol | Signature | Reads as |
| --- | --- | --- |
| $`T`$ | $`X \times C \to A_1 \times \cdots \times A_n`$ | the **tool**: the fan-out of one invocation (§2). |
| $`P`$ | $`X \times C \to D`$ | the **pipeline**: read, canonicalise, and fold the stages. |
| $`E_i`$ | $`D \times O_i \times C \to A_i`$ | the **emitter** for format $`i`$. |
| $`\pi_i`$ | $`A_i \rightharpoonup F`$ | the **recovery** of format $`i`$: a parser. Partial — see §3. |
| $`\rho_i`$ | $`D \times C \to F`$ | the **restriction** to format $`i`$: the model's facts, narrowed to what $`i`$ can express under $`c`$. |
| $`\omega_i`$ | $`A_i \rightharpoonup \mathbb{N}`$ | the **omission count** of format $`i`$: how many facts of the restriction the artefact did not state. Carried by a bounded format; a faithful format is the degenerate case $`\omega_i \equiv 0`$ — see Definition 4. |
| $`S`$ | $`D \to D`$ | one **stage** of the fold inside $`P`$. |
| $`\kappa`$ | $`D \to D`$ | the **content projection**: the model with its findings discarded. |
| $`\Delta`$ | $`D \to \Sigma^{*}`$ | the **findings** a model carries. |
| $`\delta_S`$ | $`D \to \Sigma^{*}`$ | the **contribution** of stage $`S`$: the findings that one application appends — see Definition 5. |
| $`\gamma_S`$ | $`D \times D \to \Sigma^{*}`$ | the **finding rule** of stage $`S`$, read on the content it was given and the content it produced — see Definition 6. |
| $`\varepsilon`$ | $`\Sigma \cup \{\bot\} \to \mathbb{Z}`$ | the **status reduction**: worst finding to exit code, $`\bot`$ for none. |

### Relations and indices

| Symbol | Reads as |
| --- | --- |
| $`x \sim y`$ | $`x`$ and $`y`$ **denote** the same input (Definition 2). |
| $`\text{dom}\, f`$ | the facts a fact set $`f`$ assigns. $`\text{dom}\,\pi_i`$ abbreviates the domain of the fact set recovered from the artefact in hand. |
| $`f \subseteq g`$ | $`f`$ assigns no fact outside $`\text{dom}\,g`$ and assigns the same value everywhere it assigns one: the containment order on $`F`$. |
| $`\#f`$ | the number of facts $`f`$ assigns. Every restriction is finite. |
| $`u \frown v`$ | concatenation of finding sequences. |
| $`\mathcal{B}`$ | the **bounded** format indices; $`i \notin \mathcal{B}`$ is **faithful** (Definition 4). |
| $`\mathcal{R}`$ | the **result-reporting** stages; $`S \notin \mathcal{R}`$ is **change-reporting** (Definition 6). |
| $`i, j`$ | format indices, $`1 \le i, j \le n`$. |
| $`k`$ | instance index, when several tools are composed (§6). |

Two fact sets **agree** when they assign the same value at every fact in the
intersection of their domains. Neither is required to assign anything the other
does.

$`c`$ is written explicitly only where it matters. Elsewhere $`P(x)`$, $`E_i(d,
o)`$ and $`\rho_i(d)`$ abbreviate $`P(x, c)`$, $`E_i(d, o, c)`$ and
$`\rho_i(d, c)`$ for one fixed $`c`$, and every statement is read as holding per
configuration. Behaviour can depend on the configuration.

$`c`$ and $`o`$ are not the same kind of thing and must not be conflated.
$`c`$ is what the tool was configured with: it may determine facts that are not
derivable from $`d`$ alone, and it is shared by the pipeline and every emitter
of one invocation. $`o`$ is how one artefact is presented: it is per format and
determines no fact. Where a signature admits only $`o`$, substantive input has
nowhere to enter.

---

## 2. A tool

> **Definition 1 (instance).** A tool is a tuple
> ```math
> \big(X,\ D,\ F,\ C,\ \Sigma,\ P,\ \{E_i\}_{i=1}^{n},\ \{\pi_i\}_{i=1}^{n},\ \{\rho_i\}_{i=1}^{n},\ \mathcal{B},\ \{\omega_i\}_{i \in \mathcal{B}}\big)
> ```
> in which $`P`$ computes one model from one input under one configuration, and
> each format $`i`$ has an emitter, a recovery and a restriction; each bounded
> format also has an omission count.

Its observable behaviour is the fan-out over a single model under a single
configuration:

```math
T(x, c) \;=\; \big\{\, E_1\big(P(x, c),\ o_1,\ c\big),\ \ldots,\ E_n\big(P(x, c),\ o_n,\ c\big) \,\big\}
```

$`P`$ runs once. Every artefact of one invocation is a function of the same
$`d`$ and the same $`c`$, so each can be checked against a common reference.

---

## 3. Recovery and restriction

> **Definition 2 (denotational equivalence).** $`x \sim y`$ when $`x`$ and $`y`$
> denote the same content — they differ only in ways the input format permits
> and the domain does not distinguish. $`\sim`$ is part of a tool's
> specification; it cannot be derived from the types.

> **Definition 3 (expressive range).** $`\rho_i(d, c)`$ is the image of $`d`$
> under the facts format $`i`$ can carry, as $`c`$ determines them. $`\pi_i`$ is
> partial for the same reason: a format states some of $`F`$ and is silent about
> the rest.

> **Definition 4 (faithful and bounded formats).** Format $`i`$ is **faithful**
> when one artefact has room for the whole of $`\rho_i(d, c)`$ for every $`d`$,
> $`o`$ and $`c`$. It is **bounded** when its capacity is finite and depends on
> $`o`$, so that an artefact may state a proper subset of $`\rho_i(d, c)`$ and
> must account for the remainder through $`\omega_i`$. $`\mathcal{B}`$ collects
> the bounded indices. Like $`\sim`$, membership of $`\mathcal{B}`$ is part of a
> tool's specification and is not derivable from the types.

$`\rho_i`$ selects the facts a format should contain, and $`\pi_i`$ recovers the
facts it actually contains. Comparing them checks fidelity as well as whether
the artefact is well-formed. Section 7 describes where to use this semantic
comparison.

Declaring a format bounded is a claim about that format, made in advance and
open to refutation. It is not a licence to drop facts silently: a bounded format
buys strictly less than a faithful one, and §4 states exactly how much less.

---

## 4. Theorems

> **T1 — Determinism.** $`P`$ is a pure function. For a fixed $`x`$ and $`c`$ it
> yields the same $`d`$ in every run.

Determinism concerns repeated runs on the same input. Stage idempotence (§5)
concerns applying a stage to its own result. The expression $`P(P(x))`$ does not
type-check, since $`D \not\subseteq X`$.

> **T1′ — Denotational invariance.**
> ```math
> x \sim y \;\implies\; P(x, c) = P(y, c)
> ```

$`P`$ factors through the quotient $`X/{\sim}`$: whatever $`\sim`$ declares
insignificant cannot reach the output, so no rule inside $`P`$ may consult it.
T1′ presupposes T1 and is strictly stronger.

> **T2 — Fidelity (faithful format).** For every $`i \notin \mathcal{B}`$, every
> $`c`$, every $`d`$ in the image of $`P(\cdot, c)`$, and **every**
> $`o \in O_i`$:
> ```math
> \pi_i\big(E_i(d, o, c)\big) \;=\; \rho_i(d, c)
> ```

An artefact states exactly the model facts its format can express, regardless
of presentation options.

> **T2ᵇ — Bounded fidelity.** For every $`i \in \mathcal{B}`$, every $`c`$, every
> $`d`$ in the image of $`P(\cdot, c)`$, and every $`o \in O_i`$:
> ```math
> \pi_i\big(E_i(d, o, c)\big) \;\subseteq\; \rho_i(d, c)
> ```
> ```math
> \#\,\pi_i\big(E_i(d, o, c)\big) \;+\; \omega_i\big(E_i(d, o, c)\big) \;=\; \#\,\rho_i(d, c)
> ```

Containment says an artefact never states a fact the model does not hold,
whatever its capacity: what room there is may be too small, never wrong.
Accounting says the artefact determines the size of what it left out, so no fact
vanishes without trace. T2 is the case $`\omega_i \equiv 0`$, where containment
and accounting together force equality; a bounded format weakens equality to
these two and to nothing further.

> **T3 — Presentation neutrality** *(corollary of T2, from its $`\forall o`$)*.
> For $`i \notin \mathcal{B}`$ and fixed $`c`$:
> ```math
> \pi_i\big(E_i(d, o, c)\big) \;=\; \pi_i\big(E_i(d, o', c)\big) \qquad \forall\, o, o' \in O_i
> ```

Presentation options may change bytes while preserving the recovered facts. T3
varies $`o`$ at fixed $`c`$: the configuration is held, so nothing substantive
moves, and this is exactly the separation the two arguments of $`E_i`$ record.

> **T3ᵇ — Presentation consistency** *(corollary of T2ᵇ)*. For
> $`i \in \mathcal{B}`$ and fixed $`c`$, write $`f = \pi_i(E_i(d, o, c))`$ and
> $`f' = \pi_i(E_i(d, o', c))`$. Both are contained in $`\rho_i(d, c)`$, so
> ```math
> f \;=\; f' \quad \text{on } \text{dom}\,f \cap \text{dom}\,f'
> ```

Two option sets may state different subsets, chosen by how much room each
leaves, but neither contradicts the other about a fact they both state: both are
restrictions of the one $`\rho_i(d, c)`$. Equality is recovered when the two
artefacts omit the same facts, and in particular when both omit none.

> **T4 — Agreement** *(corollary of T2 and T2ᵇ)*.
> ```math
> \pi_i\big(E_i(d, o, c)\big) \;=\; \pi_j\big(E_j(d, o', c)\big) \quad \text{on } \text{dom}\,\pi_i \cap \text{dom}\,\pi_j
> ```

Two artefacts of one invocation agree on every fact they both state. Each
format may express a different subset of the model's facts. This phrasing needs
no amendment for bounded formats: it already restricts the comparison to
$`\text{dom}\,\pi_i \cap \text{dom}\,\pi_j`$, the facts both artefacts actually
state, and a bounded format merely makes that domain depend on $`o`$ as well as
on the format. Containment into a common $`\rho`$ is what carries the corollary
in both cases.

**Checking against the model.** Verifying $`n`$ instances of T2 or T2ᵇ
establishes T4 and also checks fidelity. The $`\binom{n}{2}`$ pairwise
comparisons alone cannot do that: every emitter could produce the same incorrect
value, and every bounded emitter could omit the same facts. Checking each
artefact against the model uses fewer comparisons and identifies the emitter
responsible when one fails.

---

## 5. Stage idempotence

A stage may change content and may append findings. The two behave differently
under re-application, so they are separated. Throughout, $`\kappa`$ and
$`\Delta`$ are jointly injective: a model is determined by its content together
with its findings.

> **Definition 5 (accumulation).** A stage only extends the findings it was
> given: for every $`S`$ and $`d`$ there is a unique $`\delta_S(d) \in
> \Sigma^{*}`$ with
> ```math
> \Delta\big(S(d)\big) \;=\; \Delta(d) \frown \delta_S(d)
> ```
> Its contribution is read from the content on either side of it:
> ```math
> \delta_S(d) \;=\; \gamma_S\big(\kappa(d),\ \kappa(S(d))\big)
> ```

> **Definition 6 (result-reporting and change-reporting stages).** Stage $`S`$ is
> **result-reporting** when $`\gamma_S`$ ignores its first argument: it states a
> property of the content it produced. It is **change-reporting** when
> $`\gamma_S(u, u) = \langle\,\rangle`$ for every $`u`$: it states what it
> altered, and has nothing to state where nothing altered. $`\mathcal{R}`$
> collects the result-reporting stages. Like membership of $`\mathcal{B}`$,
> which kind a stage is belongs to a tool's specification and must be declared;
> it is not derivable from the types.

Definitions 4 and 6 are the same move made twice. In each, one law is common to
the whole class and a declared distinction says which of two strictly different
consequences may then be claimed. Neither alternative is degenerate, and in
neither case can the declaration be read off the types.

> **Content idempotence** *(both kinds)*. Re-application changes no fact:
> ```math
> \kappa\big(S(S(d))\big) \;=\; \kappa\big(S(d)\big)
> ```

> **Repetition** *(for $`S \in \mathcal{R}`$)*. Re-application re-derives the
> same contribution:
> ```math
> \Delta\big(S(S(d))\big) \;=\; \Delta\big(S(d)\big) \frown \delta_S(d)
> \;=\; \Delta(d) \frown \delta_S(d) \frown \delta_S(d)
> ```

> **Full idempotence** *(for $`S \notin \mathcal{R}`$)*. Re-application
> contributes nothing:
> ```math
> \delta_S\big(S(d)\big) \;=\; \langle\,\rangle,
> \qquad S\big(S(d)\big) \;=\; S(d)
> ```

Both follow from content idempotence. Write $`u = \kappa(S(d))`$, so that
$`\kappa(S(S(d))) = u`$ and $`\delta_S(S(d)) = \gamma_S(u, u)`$. For
$`S \in \mathcal{R}`$ the first argument is immaterial, so this is
$`\gamma_S(\kappa(d), u) = \delta_S(d)`$, and Definition 5 appends it a second
time. For $`S \notin \mathcal{R}`$ it is $`\langle\,\rangle`$ by definition,
so $`\Delta(S(S(d))) = \Delta(S(d))`$; with content idempotence and joint
injectivity the two models coincide.

The unqualified $`S(S(d)) = S(d)`$ therefore characterises the change-reporting
kind: it holds of every such stage, at every $`d`$. Of a result-reporting stage
it holds exactly where $`\delta_S(d) = \langle\,\rangle`$ — where this stage
finds nothing at this $`d`$ — and fails everywhere else, the two models agreeing
in $`\kappa`$ and differing in $`\Delta`$. A stage whose finding rule is
silent everywhere answers to both descriptions; the declaration then says which
law is claimed of it.

> **Rule.** Establish idempotence where reapplying a stage could plausibly
> change its result, and establish the half its declared kind claims: for a
> result-reporting stage, content under $`\kappa`$ and the repeated
> contribution under $`\Delta`$; for a change-reporting stage, equality of the
> models outright. Establishing the common half alone leaves the declared
> claim untouched.
> Where a stage compares by exact equality on values it has itself made exact,
> content idempotence is a theorem about the type rather than a contingent
> property: no admissible variation of the tool can falsify it, so an assertion
> would hold regardless. In that case, record why the result cannot change and
> raise no instrument.

---

## 6. Composition

Tools can exchange artefacts or run under a shared orchestrator. Write $`P_k`$,
$`E_{k,i}`$, $`\pi_{k,i}`$ for instance $`k`$. Each kind of composition has a
condition to satisfy.

**Chaining — one tool's artefact is another's input.**

```math
d_2 \;=\; P_2\Big(\big\langle\, x_2,\ E_{1,i}\big(P_1(x_1, c_1), o, c_1\big) \,\big\rangle,\ c_2\Big)
```

> **T5 — Composability.** Chaining is sound exactly when T2 holds for the
> format on the seam: instance 2 recovers from the artefact precisely the facts
> instance 1 held.

The receiving tool needs a recovery that preserves the producer's facts. If
$`\pi`$ disagrees with $`\rho`$, the receiving tool works from incorrect data.
Recovery must therefore invert the emitter on facts; it need not reproduce
the original bytes. A bounded format satisfies T2ᵇ and not T2, so it may carry a
seam only where $`\omega_i`$ vanishes on every artefact the seam transports: a
non-zero omission count is a fact the consumer never receives, and containment
alone does not bound the damage.

**Orchestration — one invocation drives several instances and reports once.**

```math
\varepsilon\Big(\max_k \max \Delta\big(d_k\big)\Big)
```

> **T6 — Uniform reduction.** The orchestrator's status is the reduction of the
> worst finding across every instance it ran.

For that maximum to be defined, all instances must share one definition of
$`\Sigma`$, its ordering and $`\varepsilon`$. A severity space private to an
instance makes the outer maximum a comparison between incomparable values, and
T6 states nothing.

---

## 7. Choosing a comparison

T2, T2ᵇ, T4 and T5 compare facts in $`F`$. Byte equality in $`A_i`$ is useful
only where it reliably represents that semantic comparison.

An artefact can include incidental values such as paths, timestamps, tool
versions, locale-dependent glyphs or counters added by the writing library.
These can change while the facts remain the same. Incidental values can also
stay the same when the facts change, so they do not establish semantic
agreement.

Choose the comparison according to the property being checked:

| Property | Both sides from | Sound instrument |
| --- | --- | --- |
| T1 determinism | one tool, two runs at one $`x`$ and $`c`$ | **bytes** |
| T1′ denotational invariance | one tool, $`\sim`$-equivalent inputs at one $`c`$ | **bytes** |
| T2 fidelity, faithful format | model versus artefact | **semantic** — via $`\pi_i`$ |
| T2ᵇ fidelity, bounded format | model versus artefact | **semantic** — containment via $`\pi_i`$, plus the count via $`\omega_i`$ |
| T3 presentation neutrality | one emitter, two option sets at one $`c`$ | **semantic** |
| T3ᵇ presentation consistency | one emitter, two option sets at one $`c`$ | **semantic** — on the common domain |
| T4 agreement | two formats, one $`d`$ and $`c`$ | **semantic** |
| T5 composability | producer's model versus consumer's read | **semantic** |
| §5 idempotence, $`S \in \mathcal{R}`$ | one stage, applied twice | **semantic** — content via $`\kappa`$, repeated contribution via $`\Delta`$ |
| §5 idempotence, $`S \notin \mathcal{R}`$ | one stage, applied twice | **semantic** — the two models entire |
| Comparison with a recorded reference | recorded expectation | **semantic** — a recorded $`\rho_i(d, c)`$, never a recorded $`a`$ |

Recording a fact set lets presentation change without disturbing the
comparison, while a changed fact still fails it. A recorded artefact would fail
for either kind of change, and so distinguishes neither.

---

## 8. Instances

This is the only section in which the domain appears. The model applies to the
two current tools and the proposed orchestrator:

| | $`X`$ | $`D`$ | artefacts $`A_i`$ | $`\sim`$ |
| --- | --- | --- | --- | --- |
| `stompdrill` | vector artwork of a panel | the drill data | CNC files for the machine, dimensioned drawings for the operator, an interchange document, and the cut solid | same geometry regardless of the order elements appear in the file |
| `stompcollider` | a board model and a drilled enclosure | the docking result | the assembled solid, and a report of what seated and what fouled | same geometry regardless of element order, and regardless of how names are assigned among geometrically indistinguishable parts |
| `stompcad` (proposed) | a project | the orchestration result | the combined outputs of the instances it drove, and one report over all of them | inherited from the instances |

Chaining (§6, T5) occurs where `stompdrill`'s cut solid becomes part of
`stompcollider`'s input, and where either tool's interchange document is read
back. The proposed `stompcad` command would provide orchestration (§6, T6).
It is not yet realised; the realised instances are `stompdrill` and
`stompcollider`.

Domain-specific behaviour belongs in the content of $`F`$, the definition of
$`\sim`$, the membership of $`\mathcal{B}`$, and the decisions inside $`P`$.
Each instance declares those four for itself; each must satisfy the structure
and properties in §§1–7.

---

## 9. Verification obligations

Each theorem carries a family of obligations, not a single one.

| | Obligation |
| --- | --- |
| T1 | emit twice in independent runs at one $`x`$ and $`c`$; compare bytes. |
| T1′ | transform an input within its $`\sim`$-class at one $`c`$; compare bytes. Widen the transformation as the class widens. |
| T2 | one $`\pi_i`$ per faithful format, and one comparison per format of the recovered facts with $`\rho_i(d, c)`$. |
| T2ᵇ | for each bounded format, establish containment in $`\rho_i(d, c)`$ and the accounting identity, at a capacity that forces omission and at one that does not. Containment alone is satisfied by an empty artefact, so the accounting half carries the obligation. |
| T3 | for each faithful emitter, vary $`o`$ at fixed $`c`$; compare recovered facts. |
| T3ᵇ | for each bounded emitter, vary $`o`$ at fixed $`c`$ across capacities that differ; compare on the common domain. |
| T4 | follows from T2 and T2ᵇ. Establish separately only where a shared fact is easy to get wrong independently in two formats. |
| T5 | for each seam, round-trip the producer's model through the consumer's read, and confirm $`\omega_i`$ vanishes if the seam's format is bounded. |
| T6 | drive instances with findings of differing severity; confirm one status. |
| §5, $`S \in \mathcal{R}`$ | apply a stage to its own result; confirm content agrees under $`\kappa`$ and that the contribution appears a second time under $`\Delta`$. A stage that finds nothing at the chosen $`d`$ leaves the second half unexercised. |
| §5, $`S \notin \mathcal{R}`$ | apply a stage to its own result at a $`d`$ it does alter; confirm the two models coincide, findings included. |

An instrument must fail when the behaviour it names is removed. Varying $`c`$
belongs to every obligation above, since each is read per configuration: an
obligation established at one $`c`$ says nothing about another. Where the model
cannot express a violation of a property, record why and raise no instrument.
