# Development plan: closing the gap between the proposal and the repository

*Written 2026-09-14. Companion to [FUTURE-WORK.md](FUTURE-WORK.md), not a
replacement for it.*

`FUTURE-WORK.md` asks "what does this system still not do?" and answers it
honestly. This document asks a different question:

> **Where does the repository say something different from what the proposal
> promised an examiner?**

Those are not the same list. A limitation you have written down is a
paragraph in Chapter 6. A claim your own README contradicts is a viva
question you will answer badly. Everything below is the second kind, plus the
sequencing needed to close it.

Three findings, in descending order of how much damage they do.

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

Ordered by dependency, not by size. Effort is working days for one person.

### Phase 0 — unblock the clock (do today)

| # | Task | Effort | Why first |
|---|---|---|---|
| 0.1 | **Submit the ethics application (A1)** | 1 day to write, then waiting | The only item whose duration cannot be compressed by working harder. It gates A4, which gates both metrics the proposal names. It has been the critical path for some time and is still not submitted. |

Nothing else in this plan competes with 0.1. Start it before reading further.

### Phase 1 — make the repository state the thesis (≈2 days, no dependencies) — **COMPLETE 2026-09-17**

Pure framing debt. Cheap, and it removes the two questions an examiner is
most likely to ask.

| # | Task | Effort | Done when |
|---|---|---|---|
| ~~1.1~~ | ~~Rename `blackboard.py` → `ledger.py`, `Blackboard` → `EvidenceLedger`.~~ **Done 2026-09-14.** | 0.5 d | ✅ Live turn and SSE stream both verified. |
| ~~1.2~~ | ~~Delete dead `counterexamples()`; make `latest`/`all_of` private.~~ **Done 2026-09-14** — `all_of()` was also dead, so it was deleted rather than hidden. | 0.25 d | ✅ No public reader remains. |
| ~~1.3~~ | ~~Rewrite the `README.md` protocol row; fix `orchestrator/README.md` and the `deploy.py` docstring.~~ **Done 2026-09-14** — also `terraform.py`, `agents/__init__.py`, `server.py`, and the canvas vocabulary. | 0.5 d | ✅ No document claims an agent reads the ledger. |
| ~~1.4~~ | ~~Write the three methodology-deviation paragraphs into `RESEARCH-GAPS.md`.~~ **Done 2026-09-17** — four, not three: LocalStack (D4) belongs with them. | 0.5 d | ✅ `RESEARCH-GAPS.md` §D1–D4. |
| ~~1.5~~ | ~~Add the Chapter 1 scoping sentence for "universal".~~ **Done 2026-09-17** — a table in `README.md`, since that is where the word first appears and it needed three rows, not a sentence. | 0.25 d | ✅ The word is defined before it is used. |

### Phase 2 — convert claims into measurements (≈2.5 days, parallel with Phase 1)

| # | Task | Effort | Done when |
|---|---|---|---|
| 2.1 | **A3 — text-only baseline CLI.** Same agents, same validators, no canvas. | 1 d | A comparative number exists. Unblocks every "compared to text-based workflows" sentence. |
| 2.2 | **Azure spike.** 3–5 registry types; compile; fix whichever of the four leaks fire. | 1 d | Either "a provider is pure registry data" or "it costs N lines in 4 files" — both reportable. |
| 2.3 | **C1 coverage.** Import three public Terraform repos; report `unmapped` as a percentage. | 0.5 d | The largest limitation becomes a quantified boundary. |

### Phase 2b — the three absent methodology components (≈1.5 d, see §5)

Named on slide 9, so an examiner reads them as delivered. Lower priority than
2.1–2.3, higher than Phase 3.

| # | Task | Effort | Done when |
|---|---|---|---|
| ~~2.4~~ | ~~**M3 — Memory Curator.**~~ **Done 2026-09-17.** | 1 d | ✅ Retrieval and storage verified live. **No ablation row was added** — the benchmark runs `intent=""` and never enters `plan`, so a row would measure nothing. See revised note in §5/M3. |
| 2.5 | **M1 — proximity.** Cluster by distance, report to the Architect as context, flip `status` in the schema. | 0.5 d | A proximity suggestion reaches the human through the normal approval flow. Non-binding, so the benchmark cannot move. |
| 2.6 | **M2 — cost.** Reclassify rather than build; one paragraph. | 0.25 d | The slide's cost clause has a stated reason, not a silence. |

### Phase 3 — evidence hygiene (≈2 days, any time before writing up)

From `FUTURE-WORK.md` C8. Not research results, but a reviewer will look.

| # | Task | Effort |
|---|---|---|
| 3.1 | Golden HCL test — pin the compiler's output for a fixed graph. | 0.5 d |
| 3.2 | Adapter round-trip test — `canvas_to_nodes ∘ nodes_to_canvas`. W2 found a real loss here that this would have caught. | 0.5 d |
| 3.3 | State machine test with a stub Architect — assert J non-increasing, repair budget respected. | 0.5 d |
| 3.4 | `opa test` for the five policies; the A2 fault corpus doubles as fixtures. | 0.5 d |

### Phase 4 — gated on 0.1

| # | Task | Blocked by |
|---|---|---|
| 4.1 | **A4 human study.** Measures State Reconciliation Accuracy and Correction Speed — the two metrics slide 10 promises. | Ethics approval |
| 4.2 | Re-run A2 with post-Phase-2 code; the trend across runs is itself a result. | 2.1–2.3 |

---

## Critical path

```
A1 ethics ──────────────────────── (waiting) ─────────────── A4 human study ── both named metrics
                                                                  │
Phase 1 (framing) ──┐                                             │
Phase 2 (evidence) ─┼── write-up can begin ───────────────────────┴──> dissertation
Phase 3 (tests) ────┘
```

Phases 1–3 total about **6.5 working days** and have no external dependency.
Phase 4 has an unbounded wait that has not started.

## If you do only three things

1. **Submit the ethics application.** Nothing else on this page has a clock
   you cannot control.
2. **Phase 1.** Two days to stop the repository arguing against the thesis.
3. **A3, the text-only baseline.** One day, and every comparative claim in
   the dissertation depends on it.

---

## What this document deliberately does not repeat

`FUTURE-WORK.md` sections B (built-to-an-interface) and C (limits) are
accurate and complete. They belong in the limitations chapter as written.
Nothing there is a hole in the result; everything here is either a hole or a
contradiction.
