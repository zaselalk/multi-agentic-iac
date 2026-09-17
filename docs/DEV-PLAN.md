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
