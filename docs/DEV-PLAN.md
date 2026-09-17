# Development plan: closing the gap between the proposal and the repository

*Written 2026-09-14, plan revised 2026-09-17. Companion to
[FUTURE-WORK.md](FUTURE-WORK.md), not a replacement for it.*

`FUTURE-WORK.md` asks "what does this system still not do?" and answers it
honestly. This document asks a different question:

> **Where does the repository say something different from what the proposal
> promised an examiner?**

Those are not the same list. A limitation you have written down is a
paragraph in Chapter 6. A claim your own README contradicts is a viva
question you will answer badly. Everything below is the second kind, plus the
sequencing needed to close it.

**How to read this.** §1–§5 are the analysis: five findings from diffing the
proposal deck against the code, in descending order of damage. §1, §3 and part
of §5 are now closed, and the text is kept because the *argument* is what the
write-up needs, not just the outcome. The implementation plan at the end is
the forward-looking part, and is the only section that should be edited as
work lands.

| Section | Finding | State |
|---|---|---|
| §1 | The blackboard was already replaced; the repository said otherwise | ✅ Closed 2026-09-14 |
| §2 | "Universal" is three claims at three different stages | ◐ Scoped in writing; Axis A needs P4 |
| §3 | Four methodology deviations, none written down | ✅ Closed 2026-09-17 — `RESEARCH-GAPS.md` D1–D4 |
| §4 | The evaluation slide 10 promised does not exist | ○ Open — P1, P2, P14 |
| §5 | Three named methodology components are absent | ◐ M3 built; M1 and M2 open — P6, P7 |

---

## 1. The blackboard has already been replaced. The repository said otherwise.

> **Status: fixed 2026-09-14.** The evidence is kept below because the
> argument is needed in the write-up; the wording is now past tense where the
> repository has been corrected.

**The proposal's claim** (slide 17, *What we replace in MACOG*):

| Component | Original MACOG | Proposed framework |
|---|---|---|
| Protocol | Internal Shared Blackboard | **Model Context Protocol (MCP)** |

That is a *substitution*. The blackboard goes; MCP takes its place as the
coordination medium.

**What the code does.** The substitution is complete, and has been for some
time:

- **No agent reads the blackboard.** `grep -rn "board" orchestrator/agents/
  orchestrator/validators/` returns five hits, every one of them inside a
  prose docstring. Zero functional references.
- **Every agent takes typed arguments.** `harmonizer.run(nodes, settings)`,
  `architect.repair(counterexamples, session_id)`, `curator.retrieve(nodes,
  intent)`, `deploy.run(compiled)`. Nothing is passed by leaving it on a
  shared surface for someone else to find.
- **The only two reads of the store are `ledger.bundle()`** —
  [`state_machine.py:324`](../orchestrator/state_machine.py#L324) and
  [`:356`](../orchestrator/state_machine.py#L356). Both are outputs: the
  Curator's memory, and the payload returned to the canvas.
- **The real shared state is the MCP-held schema instance.**
  [`state_machine.py:133`](../orchestrator/state_machine.py#L133) writes the
  graph with `set_graph`; [`:174`](../orchestrator/state_machine.py#L174) and
  [`:215`](../orchestrator/state_machine.py#L215) re-read it with `get_graph`.
  Line 174 is the decisive one: the Architect has just edited the graph, and
  the controller re-reads it **from MCP**, not from the blackboard, because
  MCP holds the canonical validated instance and the blackboard holds
  undifferentiated history.

There was even a fossil proving the design had moved: `counterexamples()` and
`all_of()` were dead code, called from nowhere — the remains of a read channel
that no longer existed. Both are now deleted, and the single surviving lookup
is private (`_latest`, called only by `bundle()`), so write-only is enforced by
the class rather than left to habit.

**So what is `Blackboard`?** An append-only, provenance-stamped, ordered
record. That is a *ledger*, not a blackboard. MACOG's blackboard is a
**coordination** mechanism — agents communicate by reading it. Ours is an
**observation** mechanism — agents are recorded on it. Same data structure,
different architectural role, and the difference is the contribution.

And it earns its place. The evidence bundle (MACOG S4.9), the live SSE agent
trail, and `author: human` conflict detection all need ordering and
provenance, which the schema instance deliberately does not carry. A schema
instance says what *is*. The ledger says who decided it, and when.

**The damage, and the fix.** `README.md` used to read:

> | Protocol | Internal shared blackboard | Blackboard **+ MCP**, with `human` as an author |

That conceded the thesis — an examiner reads it as "they kept MACOG's
blackboard and bolted MCP on beside it", which is additive, not a
substitution, and the opposite of slide 17. The same weakening appeared in
`orchestrator/README.md` ("Typed, versioned artifact store") and in the
`deploy.py` and `terraform.py` docstrings, which claimed the plan artifact was
"written to the blackboard ... and read by the Security Prover" when the
function signatures show it is passed by argument.

What changed:

| | |
|---|---|
| `orchestrator/blackboard.py` → [`orchestrator/ledger.py`](../orchestrator/ledger.py) | `git mv`, so history follows |
| `Blackboard` → `EvidenceLedger`; local `board` → `ledger` | 43 call sites |
| `counterexamples()`, `all_of()` deleted; `latest()` → private `_latest()` | write-only now enforced, not assumed |
| Module docstring rewritten | states the substitution, and what the ledger keeps that the schema cannot |
| `README.md` protocol row + a new paragraph | MCP replaces the blackboard; the ledger keeps MACOG's evidence discipline |
| `orchestrator/README.md`, `deploy.py`, `terraform.py`, `agents/__init__.py`, `server.py` | no document now claims an agent reads the ledger |
| 14 comments and one user-visible string in `visual-devops-builder` | vocabulary follows |

Verified after the change: `tsc --noEmit` clean; a live chat turn produces all
nine FSM states and 14 ledger entries with the S4.9 bundle format unchanged;
the SSE stream still delivers 9 `state` + 14 `write` events through the canvas
proxy. The evidence bundle is byte-compatible — this was a rename and a
deletion of dead code, not a behaviour change.

---

## 2. "Universal" is three claims — we hold one, are close on one, and should drop the third

The title and Objective (a) both promise a *Universal Schema*. An examiner
will read that as "any provider, any IaC tool". Separate the axes before
they do.

### Axis A — universal across cloud providers: designed for it, unproven

Structurally sound. `node_model.provider` is a free key, `resource_registry`
is data keyed by provider, and `compiler.py` / `decompiler.py` thread
`provider` as a parameter throughout. Adding Azure *should* be a registry
edit.

Empirically: **11 AWS types, 0 Azure, 0 GCP.** And the parameterisation leaks
in four places, which would make an Azure addition a code change after all:

| Site | Leak |
|---|---|
| [`decompiler.py:104`](../../mcp-server/decompiler.py#L104) | `ADDRESS = re.compile(r'\b(aws_[a-z0-9_]+)\.(...)')` — hardcoded |
| [`compiler.py:611`](../../mcp-server/compiler.py#L611) | `provider "aws" { ... }` literal |
| [`compiler.py:666`](../../mcp-server/compiler.py#L666) | `hashicorp/aws` in `required_providers` |
| [`compiler.py:759`](../../mcp-server/compiler.py#L759) | `"providers": [{"name": "aws", ...}]` |

The regex is the dangerous one. Importing an Azure `.tf` file today finds
**zero** dependency edges and fails silently — you get nodes and no graph.

### Axis B — universal across IaC targets: no, and the schema admits it

`schema.json`, `node_model.description`, our own words:

> `desired_state` is **Terraform-only**

`tf_name` is a first-class node field. `compiler.target` is the scalar
`"terraform"`. Registry entries carry `terraform_type` and raw HCL bodies with
`aws_s3_bucket.{tf_name}.id` interpolation inside them. `desired_state` is not
a neutral IR that compiles *to* Terraform — it is Terraform's attribute
vocabulary in JSON.

Pulumi or Bicep would need a genuine IR layer beneath it. **Rule this out of
scope explicitly in Chapter 1** rather than leave an examiner to find it.

### Axis C — universal as a synchronisation mechanism: yes, and this is the contribution

- `view` / `desired_state` separation, with `view` never compiled
- `spatial_semantics` — nesting implies `depends_on`, **gated by the
  registry**, so nesting can never invent a relationship Terraform cannot
  express
- `sync_engine` and the round-trip property `equiv(P₁, P*)`
- intent-by-presence: every `desired_state` key that exists is somebody's
  decision

None of that names AWS or Terraform. It is target-independent by
construction.

Read precisely, the title says *"A Universal Schema **for Bi-Directional
Synchronization**"* — universality is claimed over the sync mechanism, not the
resource vocabulary. **That reading is defensible. It is not the reading
anyone reaches unaided.** Say it in Chapter 1, in one sentence, before the
question is asked.

### The test that settles Axis A

Universality here has a binary, one-day experiment:

> **Can a provider be added without touching Python?**

Add three to five Azure types to the registry and compile. If it works, the
schema is universal in the sense that matters and you have a demonstration
instead of an assertion. If it fails, it fails at exactly the four sites
above — fix them, and *then* the claim is real. **Either outcome is a
reportable result.**

---

## 3. Three methodology deviations from slides 9–10, all defensible, none written down

The proposal names specific mechanisms. We built different ones, mostly
better. Silence here reads as oversight; a paragraph reads as a decision.

| Proposal says | We built | Verdict |
|---|---|---|
| **LangGraph Orchestration** (slide 9) | Hand-rolled deterministic FSM. Zero LangGraph anywhere. | **Stronger.** `strategy.llm_allowed: false`; only `plan` and `repair` call a model. Determinism is a thesis asset — a LangGraph dependency would have obscured it. Needs one justifying paragraph. |
| **Grammar-constrained decoding** (slide 9) | Fully deterministic compiler; the LLM never emits HCL at all. | **Stronger.** Constrained decoding reduces hallucination; not generating is the limit case of it. Say so — this is an upgrade, not a shortfall. |
| **MCP streams "Real-Time Deltas"** (slide 10) | Request/response `set_graph`/`get_graph`. SSE added for the *agent trace*, not for graph deltas. | **Narrow the claim.** The user-visible real-time requirement is met by SSE; MCP-level delta streaming is not implemented and is not needed for any result. |

Two claims from slide 9–11 that **are** met and should be cited as such:
Visual Ghosting is implemented
([`BaseNode.tsx:344`](../../visual-devops-builder/components/nodes/BaseNode.tsx#L344)),
and Agentic Breakpoints are ordinary control flow rather than future work.

One claim that is **overstated**: "Zero-Drift Architecture" (slide 11). Per
`FUTURE-WORK.md` C4, drift is measured desired-vs-last-compiled, not
desired-vs-live. The strong form of the claim needs `terraform apply`, which
C3 rules out on purpose. State the weaker form.

---

## 4. The evaluation the proposal promised

Slide 10 commits to this, jointly with the partner:

> **System Evaluation (Joint):** Benchmarking against the MACOG Framework for
> "State Reconciliation Accuracy" and "Correction Speed" compared to
> text-based workflows.

Status of that sentence, clause by clause:

- **Benchmarking against MACOG** — partially done. `benchmark/RESULTS.md`
  has 27 seeded faults across four ablations: 100% detection, 100%
  attribution. That is a self-comparison, not a MACOG comparison.
- **"compared to text-based workflows"** — **not done.** This is `A3`, the
  text-only baseline CLI. Roughly a day of work, and *every* comparative
  claim in the dissertation rests on it.
- **State Reconciliation Accuracy / Correction Speed** — **defined in three
  places** (`FUTURE-WORK.md:139`, `PLAN.md:272`, `RESEARCH-GAPS.md:627`),
  **measured in none.** Both are defined as *human-study* measures, so
  neither can be obtained from A3 alone.

That last point is the scheduling consequence worth stating plainly: **the
proposal's headline evaluation is gated entirely on ethics approval.** A3
gives the system-side comparison; the two named metrics need participants,
participants need A4, and A4 needs A1.

---

## 5. Methodology audit — every bullet on slides 8–11

Sections 1–4 came from diffing the *claims*. This is the line-by-line pass over
the **methodology** slides, because a bullet on slide 9 or 10 is something an
examiner will read as delivered.

Fourteen bullets. Nine are met, three are deviations already recorded as D1–D4,
and **three are named methodology components that do not exist**. Those three
are new to this document and are the subject of M1–M3 below.

### Slide 8 — Aim and objectives

| | Status |
|---|---|
| (a) Universal Schema for visual layout + infrastructure state | ✅ `schema.json`; scope of "universal" now stated in `README.md` |
| (b) Multi-Agent Orchestrator for reasoning and conflict detection | ✅ G6 closed — `conflict.py`, `intent.py` |
| (c) Real-Time Visual Canvas with event-driven state mapping | ✅ no polling anywhere; user action → request, SSE during the turn. Single-session only (C7) |
| (d) Validation Loop triggering AI intervention on human design errors | ✅ G5 closed — a hand edit validates in ~110 ms |

### Slide 9 — Orchestration & logic

| Bullet | Status |
|---|---|
| LangGraph Orchestration | ⚠️ **D1** — deterministic controller instead. Stronger; recorded |
| Visual-Spatial Architect: "nesting, **proximity**" | ⚠️ **M1** — nesting implemented and registry-gated; **proximity is `status: "not_implemented"` in the schema and appears in no code** |
| Visual Policy Critic: OPA + ghosting for "security**/cost**" fixes | ⚠️ **M2** — OPA and ghosting work; the cost half produces nothing |
| Constrained Synthesizer: grammar-constrained decoding | ⚠️ **D2** — deterministic compiler instead. Stronger; recorded |
| Memory Curator: Verified Visual Motifs | ⚠️ **M3** — interface only; `retrieve()` returns nothing on every turn |
| Safety Governance: Agentic Breakpoints | ✅ ordinary control flow, not future work |

### Slide 10 — Semantic interface & sync

| Bullet | Status |
|---|---|
| Semantic Canvas — nodes carry cloud metadata | ✅ |
| MCP Bridge streaming "Real-Time Deltas" | ⚠️ **D3** — request/response + SSE for the trace. The one deviation that is a shortfall, not an upgrade |
| Spatial Mapping: node ID ↔ Terraform address | ✅ `adapters.py`, both directions |
| HITL UI: red-glow conflict overlays | ✅ |
| System Evaluation vs MACOG, vs text-based workflows | ❌ **A3** not started; the two named metrics need **A4**, which needs **A1** |

### Slide 11 — Expected outcomes

| | Status |
|---|---|
| Multi-Modal Agentic Workflows | ✅ |
| Synchronized Co-Design Environment | ✅ |
| **Zero-Drift Architecture** | ⚠️ overstated. Drift is desired-vs-last-compiled, not desired-vs-live (C4), because nothing here runs `apply` (C3, deliberate). State the weaker form |
| Visual Conflict Resolution | ✅ |
| "validated model for high-fidelity human-agent collaboration" | ❌ "validated" needs **A4** |

---

### M1 — Proximity semantics

**Promised:** slide 9 — "Maps spatial metadata (**nesting, proximity**) from the
UI to a Universal Infrastructure Schema."

**Reality:** nesting is fully implemented and registry-gated, so it can never
invent a relationship Terraform cannot express. Proximity is specified in
`schema.json` — `signal: view.position`, `effect: suggestion_only`,
`binding: false` — and carries `"status": "not_implemented"`. `grep -rn
proximity` over all three repos returns nothing outside the schema.

**Why it is small.** The schema already decided the hard question: proximity is
*non-binding*. Distance must never create, remove or modify infrastructure,
because two nodes may sit together for reasons the layout engine chose. So
closing M1 cannot affect correctness and cannot break the benchmark — it is a
reporting path, not a compilation path.

**How to close (≈0.5 d).** Cluster nodes by canvas distance, pass the clusters
to the Architect as context alongside the retrieved motifs, and let any
resulting edit go through the ordinary breakpoint/approval flow. Then flip
`status` to `implemented` in the schema. Deliverable: a suggestion the human
accepts or rejects, never a silent edit.

**Or close it honestly instead.** Reclassify as scope: "proximity was specified
and deliberately left non-binding; implementing the suggestion channel is
future work." That costs a sentence. Either is defensible — what is not
defensible is a methodology bullet with nothing behind it and no explanation.

### M2 — The cost half of the Visual Policy Critic

**Promised:** slide 9 — ghosting "on the canvas for suggested **security/cost**
fixes."

**Reality:** security works end to end — OPA evaluates five Rego policies, and
a violated rule that names its own fix is ghosted over the node as a
before → after diff. `validators/cost.py` is a 53-line documented stub, so
`cost` reports `skipped` on every turn and the cost half of that sentence
produces nothing.

**The useful finding:** the ghosting path is generic. It renders any
counterexample carrying a `patch`, and does not care which validator produced
it. The cost half is absent **only because cost emits no counterexamples** —
not because the canvas cannot show them. Closing M2 is the price book and
nothing else.

**How to close (≈1–1.5 d).** `price_book.json` keyed
`{terraform_type: {region: {sku: usd_per_month}}}`, stamped with the catalogue
date so a run is reproducible; walk `compiled["plan"]["resources"]`; emit a
`cost_violation` per over-budget node. The harder half is already done — since
W2 the plan carries every SKU as the provider resolves it (`instance_class`,
`allocated_storage`, `billing_mode`), so the book can be keyed on values that
actually exist rather than on what the graph happens to spell.

**Recommendation: do not build this.** `cost.py`'s own docstring makes the
better argument — a cost figure nobody can trace is exactly the kind of
evidence a proof-carrying bundle exists to exclude, and a hand-made price book
for 11 resource types is not a research result. Reclassify: the interface is
settled, the plan-grounded inputs exist, the catalogue is out of scope. Say so
on the slide's terms.

### M3 — Memory Curator

**Promised:** slide 9 — "Maintains a library of Verified Visual Motifs to
prevent 'State Drift' and facilitate rapid co-design."

**Reality:** `agents/curator.py` is 59 lines of interface. It is wired into the
controller — `retrieve()` is called before the Architect plans, `store()` after
a successful turn — so every turn runs the `- Memory Curator` ablation without
saying so.

**Why this one is different from M2.** The curator's own docstring argues it
matters *more* here than in MACOG: MACOG's motifs are typed code fragments,
but here a verified motif is **a subgraph plus its layout**, so reusing one
restores the arrangement the human recognises rather than just the resources.
That is a distinctive claim of this research, and it currently has nothing
behind it. MACOG's ablation for this component is its mildest
(74.02 → 72.17), which is why it was deferred — but MACOG's version is the
weaker one.

**How to close (≈1 d).** `shape_key()` canonicalising (sorted resource kinds,
edge multiset) so "VPC + 2 subnets + ALB" retrieves regardless of naming;
`store()` writing {subgraph, HCL digest, evidence bundle, view positions} on a
turn that ends `done` with every validator passing; `retrieve()` injecting
matches as typed fragments, never raw HCL; persisted alongside projects.

**Built 2026-09-17.** Two things were learned doing it, both worth recording.

*The wiring was a no-op, not just the implementation.* `retrieve()` was called
and its result written to the ledger, but never passed to the Architect. Even
a working curator would have changed nothing until `plan()` took a `motifs`
argument. A component can be fully present in the trail and absent from the
system.

*It cannot be measured by the current benchmark.* The seeded-fault harness
runs with `intent=""`, so it never enters the `plan` state — the only place
`retrieve()` is called. A `- Memory Curator` row would measure nothing, so
none was added. This component is **built but not evidenced**, which is a
weaker position than the other seven and should be stated as such. The fix is
an arm in A3: the same task list, motif-seeded versus unseeded.

---

### Triage

| | Effort | Verdict |
|---|---|---|
| ~~**M3** Memory Curator~~ | 1 d | ✅ **Built 2026-09-17.** Built but not yet *evidenced* — needs a seeded-vs-unseeded arm in A3 |
| **M1** Proximity | 0.5 d | **Build** — it is half a day and completes a named objective — or reclassify in one sentence |
| **M2** Cost | 1.5 d | **Reclassify.** An untraceable price book is worse than an honest absence |
| **Zero-Drift wording** | — | State the weaker form: desired-vs-last-compiled |

None of these outranks **A3** or **A1**. M1–M3 make the methodology chapter
defensible; A3 and A4 decide whether there is a result to defend. Do them in
that order.

---

## Implementation plan

*Revised 2026-09-17. Everything above is analysis; this is what is left to do
about it. Effort is working days for one person.*

### Where this stands

| | |
|---|---|
| **Closed** | §1 blackboard→ledger · §2 "universal" scoped in `README.md` · §3 D1–D4 written into `RESEARCH-GAPS.md` · §5 M3 Memory Curator built |
| **Open** | The evaluation (§4) · M1 proximity · M2 cost · four wording fixes · tests · **ethics** |
| **Non-gated work remaining** | ≈ **7.5 days** |
| **Gated work** | A4, behind an ethics application that has not been submitted |

Three things surfaced while doing the above that had no task and now do:
A3 needs a second arm (B1b), the test suite cannot run in this container at
all (D0), and two claims still need narrowing in prose (C3).

---

### Phase A — the clock (1 task)

| # | Task | Effort | Why it is alone in its phase |
|---|---|---|---|
| **P1** | **Submit the ethics application** (`FUTURE-WORK.md` A1). | 1 d to write, then waiting | The only item whose duration cannot be compressed by working harder. It gates A4, which gates *both* metrics slide 10 names. It has been the critical path since the plan was first written and is still not submitted. |

Nothing else competes with P1. Every other phase can proceed in parallel with
the waiting, and none of them can start the waiting sooner.

### Phase B — evidence (≈3 days, nothing blocking)

The phase that decides whether there is a result to defend.

| # | Task | Effort | Done when |
|---|---|---|---|
| **P2** | **A3 — text-only baseline CLI.** Same agents, same validators, no canvas. | 1 d | A comparative number exists. Unblocks every "compared to text-based workflows" sentence — which slide 10 commits to explicitly. |
| **P3** | **Motif-seeded vs unseeded arm.** Same task list, run twice: empty motif store, then warm. | 0.5 d | The Memory Curator stops being *built but unevidenced*. See §5/M3 — the seeded-fault benchmark cannot measure it, because it runs `intent=""` and never enters `plan`. This is the cheapest place to fix that, and it rides on P2's harness. |
| **P4** | **Azure spike.** 3–5 registry types; compile; fix whichever of the four AWS leaks fire. | 1 d | Either "a provider is pure registry data" or "it costs N lines across 4 files" — both are reportable, and until one is run, §2's Axis A is a design property rather than a result. |
| **P5** | **C1 coverage.** Import three public Terraform repos; report `unmapped` as a percentage. | 0.5 d | The largest stated limitation becomes a quantified boundary. |

**Watch item for P4.** `decompiler.py:104` hardcodes `aws_` in the address
regex, so importing a non-AWS file finds **zero** dependency edges and says
nothing about it. Add a failing-import test alongside the fix; a silent wrong
answer is worse than the leak.

### Phase C — finish the methodology chapter (≈1 day)

Slide 9 and 11 items an examiner reads as delivered. Cheap, and none of it
touches the benchmark.

| # | Task | Effort | Done when |
|---|---|---|---|
| **P6** | **M1 — proximity.** Cluster by canvas distance, report to the Architect as context, flip `status` in `schema.json`. | 0.5 d | A proximity suggestion reaches the human through the normal approval flow. `binding: false`, so correctness and the benchmark cannot move. **Or** reclassify in one sentence — both are defensible; an unexplained blank is not. |
| **P7** | **M2 — cost.** Reclassify rather than build. | 0.25 d | The slide's "security/cost" clause has a stated reason. `cost.py` already makes the argument: an untraceable price figure is exactly the evidence a proof-carrying bundle exists to exclude. |
| **P8** | **Two claims still to narrow in prose.** "Zero-Drift Architecture" (slide 11) → desired-vs-last-compiled, not desired-vs-live, because nothing runs `apply` (C3/C4 in `FUTURE-WORK.md`). And D3, MCP "real-time deltas" → what SSE actually delivers. | 0.25 d | Neither claim is stated in a form the implementation does not support. |

### Phase D — tests (≈2.25 days)

| # | Task | Effort | Note |
|---|---|---|---|
| **P9** | **Make the test suite runnable here.** `mcp-server`'s two venvs are Windows-layout (`Scripts/`, `Lib/`) and the orchestrator venv has no `pytest`. | 0.25 d | **Do this first.** 28 existing tests cannot be run in this container, which means they are currently unverified on every change — including the last four commits. |
| **P10** | Golden HCL — pin the compiler's output for a fixed graph. | 0.5 d | |
| **P11** | Adapter round-trip — `canvas_to_nodes ∘ nodes_to_canvas`. | 0.5 d | W2 found a real loss here (`tags` returned as a JSON string) that this would have caught first. |
| **P12** | State machine with a stub Architect — assert `J` non-increasing and the repair budget respected. | 0.5 d | |
| **P13** | `opa test` for the five policies; the A2 fault corpus doubles as fixtures. | 0.5 d | |

### Phase E — gated on P1

| # | Task | Blocked by |
|---|---|---|
| **P14** | **A4 human study.** Produces State Reconciliation Accuracy and Correction Speed — the two metrics slide 10 names, defined in three documents and measured in none. | P1 |
| **P15** | Re-run A2 with post-Phase-B code. The trend across runs is itself a result. | P2–P5 |

### Housekeeping (≈0.25 d, raised repeatedly, never actioned)

| | |
|---|---|
| `tsconfig.tsbuildinfo` is a tracked build artifact that dirties on every `tsc` run | `.gitignore` it |
| Nothing is pushed | Three repos, three feature branches, all local only: `improve/v1`, `new-ui`, `feat/visor-integration` |
| `.gitattributes` absent | Four files still store CRLF against 47 LF; `* text=auto eol=lf` settles it |

---

## Critical path

```
P1 ethics ──── submit ──── (unbounded wait) ──── P14 human study ──── both named metrics
    │                                                                        │
    └── everything below runs in parallel with the wait                      │
                                                                             │
B  evidence   (3 d)   ── P2 P3 P4 P5  baseline, arm, Azure, coverage ──┐               │
C  methodology(1 d)   ── P6 P7 P8     proximity, cost, wordings ──────┼── write-up ──┴──> dissertation
D  tests    (2.25 d)  ── P9 first, then P10-P13 ──────────────────────┘
```

**≈7.5 non-gated days.** The wait has not started.

Task ids are `P1`–`P15` and belong to this document only. `A1`–`A4`, `B1`–`B3`
and `C1`–`C8` are `FUTURE-WORK.md`'s; `D1`–`D4` are `RESEARCH-GAPS.md`'s
proposal deviations; `G1`–`G9` are the gap register. They are different
schemes and are not renumbered here.

## If you do only four things

| | | Why |
|---|---|---|
| 1 | **P1 — submit the ethics application** | The only clock you cannot speed up, and it gates the dissertation's headline metrics. Unchanged from the first version of this document, which is itself the finding. |
| 2 | **P2 — the text-only baseline** | One day, and slide 10 committed to it in writing. Every comparative claim rests on it. |
| 3 | **P9 — make the tests runnable** | A quarter of a day. 28 tests have been unverifiable for this entire work stream. |
| 4 | **P3 — the curator arm** | Half a day riding on B1a, and it is the difference between a component that exists and one that is shown to do something. |

Phase C (P6–P8) is a day and makes the methodology chapter defensible, but it changes
no result. Do it while waiting on A1, not instead of Phase B.

---

## What this document deliberately does not repeat

`FUTURE-WORK.md` sections B (built-to-an-interface) and C (limits) are
accurate and complete. They belong in the limitations chapter as written.
Nothing there is a hole in the result; everything here is either a hole or a
contradiction.
