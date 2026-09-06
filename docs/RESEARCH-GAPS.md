# Research gaps

What the system does today, what it does not, and what has to be built to
finish the research. Every claim below was checked against the code on the
`feat/visor-integration` branch, not inferred from the proposal.

Gap IDs (`G1`…`G9`) are referenced from the source and from the other READMEs.

---

## Where the system actually stands

Verified working, end to end:

- The canvas, the shared graph, and a deterministic graph→HCL compiler whose
  output passes `terraform validate`.
- The Architect's MCP tool-calling loop, editing the graph rather than writing
  HCL.
- The orchestration state machine
  (`load → plan → harmonize → compile → review → prove → price → deploy → repair → done`),
  MACOG's Eq. 14 states plus the two this research adds.
- The counterexample-guided repair loop. Measured on a deliberately
  non-compliant project (public S3 ACL + unencrypted RDS): the Security Prover
  raised J = 6.0, and two repair rounds took it to J = 0.
- The Security Prover: OPA over three Rego policies, evaluated on the typed IR,
  with every violation carrying the `node_id` it belongs to.
- The DevOps validator: `terraform init -backend=false` + `terraform validate`.
- Agentic breakpoints on destructive edits, and the proof-carrying evidence
  bundle.

Not built at all: cost estimation, the Memory Curator, any code→graph
direction, spatial semantics, the visual overlay, real-state drift, and an
evaluation protocol.

---

## The gaps

| | Gap | Blocks objective | Size |
|---|---|---|---|
| **G1** | The IR is lossy — compliance companions never reach it | (a) schema, (b) conflict detection | S |
| **G2** | No code→graph direction; "bi-directional" is unproven | (a) schema — **the title** | L |
| **G3** | Spatial metadata is carried but never interpreted | (a) schema, (c) canvas | M |
| **G4** | Validators stop short of runtime grounding | (b) orchestrator, (d) validation loop | M |
| **G5** | A human edit does not trigger the validation loop | **(d) — directly** | S |
| **G6** | Conflict detection is declared in the schema, unimplemented | (b) — **the research question** | M |
| **G7** | No evaluation protocol | all | L |
| **G8** | The canvas does not render what the backend now emits | (c), (d) | M |
| **G9** | No tests, in any of the three repos | reproducibility | M |

---

### G1 — The IR is lossy

`compile_graph` emits compliance *companion* resources into the HCL —
`aws_s3_bucket_public_access_block`, `aws_s3_bucket_server_side_encryption_configuration`,
`aws_s3_bucket_versioning` — but `terraform_ir.resources` contains only the
primary resource for each node. Confirmed by compiling a two-node graph: the
HCL has five resources, the IR has two.

Three consequences:

1. Policies evaluated on the IR cannot see the mitigations the compiler
   applied. `no_public_s3.rego` flags `acl = "public-read"` correctly, but a
   rule of the form "every bucket must have a public access block" would fire
   falsely on every bucket, because the block is invisible.
2. The IR shown in the canvas's **IR** tab is not a faithful account of the
   Terraform in the **Terraform** tab, which undercuts the point of showing it.
3. MACOG's round-trip equivalence check (Eq. 11, `equiv(P₁, P*) = true`) cannot
   be run against an IR that does not describe what was emitted.

**Fix.** In `mcp-server/compiler.py`, append companion resources to
`ir_resources` as they are emitted in `_emit_companions`, tagging each with the
`node_id` of the node that induced it and a flag marking it compiler-generated.
Small and self-contained; do it before writing more policies, or the policies
will encode the blind spot.

### G2 — No code→graph direction

The title promises bi-directional synchronisation. What exists is
canvas ⇄ graph ⇄ HCL, where the last arrow points one way only. There is no
HCL parser anywhere in the three repos (`grep` for `hcl2`, `parse_hcl`,
`round_trip`: no hits).

So the system cannot:

- import an existing Terraform project onto the canvas — a hard limit on who
  can adopt it, since nobody starts from an empty canvas;
- run MACOG's round-trip check, which is the guarantee that compilation
  preserved intent;
- reconcile a change made in the `.tf` file by hand, which is the drift case
  the "Zero-Drift Architecture" claim rests on.

**Fix.** `python-hcl2` (or the `hcl2json` binary) parses HCL to a dict. Write
`mcp-server/decompiler.py` inverting the registry: `terraform_type` → resource
key, attributes back through `attribute_map`, `aws_x.y.id` references back to
`depends_on`. The registry already holds every mapping, so this is an inversion
rather than new knowledge. Then add `equiv(P, decompile(compile(P)))` as a
check in the `compile` state, and a `POST /projects/import/terraform` endpoint.

Expect this to be the largest single piece of work, and to surface registry
gaps immediately — which is a feature, since it makes the compiler's coverage
measurable for the first time.

### G3 — Spatial metadata is carried but never interpreted

The proposal's Visual-Spatial Architect "maps spatial metadata (nesting,
proximity) from the UI to a Universal Infrastructure Schema". Today `view`
carries `position`, `parent_id` and `style` faithfully through
`canvas_to_nodes` and back — and `compiler.py` never reads any of it
(confirmed: no reference to `view`, `parent_id` or `position` in the compiler).

So dropping an EC2 node *inside* a subnet box communicates nothing. The
dependency comes only from an explicitly drawn edge. The nesting a human reads
as containment is, to the system, decoration.

**Fix.** Decide the semantics first, then implement:

- `parent_id` ⇒ an implied `depends_on`, when the registry declares a reference
  between the two resource types. This is the whole of "nesting" and is cheap.
- Proximity is harder and needs a rule you can defend in a write-up. A
  defensible one: proximity never *creates* infrastructure, it only *proposes*
  it — the Architect is told which nodes are spatially clustered and may
  suggest an edge, which the human accepts. That keeps an ambiguous signal out
  of the compiled artefact while still using it.

Record the choice in `schema.json` under a `spatial_semantics` block, so the
canvas and the compiler agree on what a position means.

### G4 — Validators stop short of runtime grounding

`terraform validate` parses HCL against the provider schema. It does not
resolve references, expand counts, or discover that an instance type is
unavailable in a region. MACOG's ablation makes this the single most costly
component to omit: removing the DevOps sandbox drops IaC-Eval 74.02 → 56.93,
the largest drop of the eight.

Also unbuilt: the Cost & Capacity Planner (`validators/cost.py` is an interface
and a no-op; it returns `skipped`, never a number).

**Fix, in order of value:**

1. `terraform plan` against **LocalStack** — the devcontainer already
   configures LocalStack credentials, so this needs an endpoint override in the
   provider block and no real AWS account. Map plan diagnostics back to nodes
   with the address→`tf_name` lookup already in `validators/deploy.py`.
2. A pinned price book for the ten registered resources, and `estimate()`
   filled in. Stamp it with the catalogue date — a cost figure nobody can trace
   does not belong in a proof-carrying bundle.

### G5 — A human edit does not trigger the validation loop

This is objective (d) — "a Validation Loop that triggers AI intervention during
human design errors" — and it is the cheapest gap on this list.

`POST /projects/{id}/graph` is the endpoint the canvas calls on every drag,
drop and field edit. It calls `_compile` and returns the compiler's schema
errors. It does **not** run the Security Prover, and it does not consult an
agent. A human who sets a bucket's ACL to `public-read` gets silence until they
happen to start a chat turn or click verify.

So the policy conflict the research is about — a human making a visual change
that violates a constraint only the agents know — is detectable by the system
and not currently surfaced when it actually happens.

**Fix.** Run the validators (not the repair loop) inside the `/graph` handler,
debounced, and return `counterexamples` alongside `errors`. The state machine
already supports it: `run(intent="", repair=False)` is exactly this call. Then
decide the escalation rule — at what point a violation stops being an overlay
and becomes an agent turn that proposes a fix. That threshold is a research
choice worth stating explicitly rather than defaulting.

### G6 — Conflict detection is declared but unimplemented

`schema.json` declares:

```json
"conflict_resolution": { "strategy": "human_in_the_loop",
                         "fallback": "agentic_merge_with_approval" }
```

Nothing implements either. The canvas is unconditionally authoritative at turn
start (`set_graph` overwrites), so a concurrent agent edit and human edit do
not conflict — the human silently wins, and the agent's work is lost with no
record that it existed.

This is the stated research question ("conflict detection when a human makes a
visual change that violates a policy known only to the AI agent or the
compiler"), so it needs to be named precisely. There are two distinct
conflicts, and only one is handled:

| Conflict | Status |
|---|---|
| Human edit violates a policy the agent knows | **Detected** — the prover reports it against the node (though not yet at edit time, see G5) |
| Human edit and agent edit touch the same node in one turn | **Not detected** — last write wins, silently |
| Explicit human *intent* violates a policy | **Silently overridden** — see below |

**The third one was found by running the system, and is the sharpest.** Asked
for "a postgres database with `storage_encrypted` set to false", the Architect
built exactly that, the Security Prover raised `rds_storage_encrypted`, and one
repair round set it back to `true`. The stored graph now says `true`.

Nothing wrong happened at any single step, and the outcome is still wrong: the
human asked for something, the system did the opposite, and never said so. The
repair loop cannot tell an *accident* it should quietly fix from a *decision*
it should argue with — and this system, unlike MACOG, has someone present to
argue with.

Worse, the reply the user reads — "a PostgreSQL database instance with storage
encryption disabled" — was generated in the `plan` state, before the repair.
It is stale and actively misleading. Whatever the escalation policy turns out
to be, the reply must be composed after the loop settles, not before.

**Fix.** Distinguish a counterexample that contradicts something the human
explicitly asked for from one that merely reveals an omission. The Architect
already knows which attributes it set from the request; mark those as
*intended*, and route a violation on an intended attribute to a breakpoint
("you asked for X, policy Y forbids it — override, or change the policy?")
rather than to a silent repair. This is `human_in_the_loop` as the schema
already declares it, applied to the case that actually occurs.

**Fix for the second.** The blackboard already stamps every write with an
author and a content digest. Compare the digest of the node as loaded (author
`human`) against the digest after the Architect's edits; where both changed the
same node, emit a `conflict` artefact and raise a breakpoint instead of
overwriting. `agentic_merge_with_approval` is then the attribute-level merge on
top of that, offered to the human rather than applied.

### G7 — No evaluation protocol

The IaC-Eval harness has been removed, and nothing replaces it. This is the
gap that decides whether the work is publishable, so it is worth being blunt:
IaC-Eval could not have been kept. Its baselines (few-shot, CoT, multi-turn,
RAG) all measure single-shot text→HCL task success, and this system is neither
single-shot nor text-first. A human edits the artefact mid-run, so
"task solved on the first try" is not a quantity it admits.

What is needed is a two-part protocol — one half automatic and reproducible,
one half with humans — because a user study alone cannot be compared against
MACOG's numbers, and a benchmark alone measures nothing about the contribution.

**Part 1 — seeded-fault benchmark (automatic, no humans, reproducible).**
The system's own claim is that it detects and repairs violations. Test exactly
that:

- Take a corpus of valid graphs. Inject a single known fault into each — a
  public ACL, an unencrypted database, a dependency cycle, a region outside
  the allowed set, an out-of-registry resource.
- Measure, per fault class: **detection rate** (did a validator fire),
  **attribution accuracy** (did the counterexample name the right `node_id` —
  this is the metric nothing in the literature reports, because nothing else
  addresses failures to a visual element), **repair rate** within K attempts,
  and **repair minimality** (nodes changed beyond the faulted one — MACOG's
  claim of "minimal edits, not speculative rewrites" made measurable).
- Ablate the same way MACOG does: prover off, harmonizer off, repair budget 0.
  This yields a table directly comparable in form to MACOG's Table 4.

This is buildable now, needs no participants, and gives a number well before
the user study.

**Part 2 — human study (the actual contribution).**
The proposal already names the right two metrics; they need operational
definitions:

- **State Reconciliation Accuracy** — after a session, does the graph the human
  believes they built match the Terraform emitted? Operationalise as: show
  participants their final diagram and the compiled HCL, and count
  discrepancies they identify. A drift of zero is the claim being tested.
- **Correction Speed** — wall-clock from a violation being introduced to it
  being resolved, visual workflow vs. a text baseline (same model, same
  policies, chat-only, no canvas). That baseline is essential and does not
  exist yet — build it as a CLI, since the orchestrator API already supports it.

Add: task completion rate, count of agent suggestions accepted vs. rejected
(a measure of whether the visual channel makes agent reasoning legible), and
breakpoint outcomes.

Design notes that will matter to a reviewer: within-subjects with order
counterbalancing, n ≥ 12, tasks with objectively checkable end states, and
ethics approval — which has a lead time, so start it before the system is
finished rather than after.

### G8 — The canvas does not render what the backend emits

`POST /projects/{id}/chat` now returns `validators`, `counterexamples`,
`breakpoints`, `repairs` and `evidence`. The canvas consumes none of them: the
Zustand store reads only `data.errors` and `data.warnings`
(`store/useInfraStore.ts`), which are the compiler's schema errors.

So the proposal's "Visual Ghosting", "Red-Glow alerts" and Agentic Breakpoint
approval have a complete backend and no frontend. `BaseNode.tsx` already has an
`error` status with border, glow and dot — the styling hook exists.

**Fix.**

- Extend the store with `counterexamples`, `breakpoints` and `validators`.
- Node overlay keyed on `counterexample.node_id`, coloured by `severity` and
  `type` — a policy violation should not look like a schema error.
- Breakpoint modal: show `detail.nodes` and the reason, and resend the turn
  with `approved: true` on accept. Until this exists a breakpoint stops a turn
  with no way for the user to release it.
- A validator strip showing the four statuses, so `skipped` is visible. A user
  who cannot see that cost was never checked will assume it passed.
- Show `repairs > 0` and what changed. The reply text is written before the
  repair loop runs (see G6), so on any repaired turn the prose and the graph
  disagree. Until the reply is recomposed after the loop, the canvas is the
  only place the user can find out that a repair happened at all.
- "Ghosting" needs one backend addition: a proposed-but-unapplied graph. The
  cleanest route is for the repair loop to return its patch as a diff the human
  approves, rather than applying it and reporting afterwards.

### G9 — No tests

`git ls-files | grep -i test` returns nothing in any of the three repos. For a
research artefact intended for release, the compiler and the state machine both
need to be pinned:

- Compiler: golden HCL for a fixed graph; the ten-resource smoke graph is
  already the informal version of this.
- Adapters: `canvas_to_nodes ∘ nodes_to_canvas` round-trip.
- State machine: the repair loop with a stub Architect, asserting J is
  non-increasing and the budget is respected.
- Policies: `opa test` — Rego has a native test framework, and the seeded-fault
  corpus from G7 doubles as its fixtures.

---

## Suggested order

Against the proposal's timeline (months 6–7 "advanced features", months 8–9
"testing and evaluation"):

**First — small, unblocks other work.** G1 (lossy IR) and G5 (validate on human
edit). Together they are perhaps a day, and G5 alone completes objective (d).

**Second — the contribution, in parallel.** G8 makes the multi-agent reasoning
visible, which is the demo and the thing a study participant reacts to. G6's
concurrent-edit half makes the research question answerable. G3 decides what a
position means.

**Third — start now regardless of readiness.** G7. The seeded-fault benchmark
can be built against today's system and re-run as gaps close. The ethics
approval and the text baseline both have lead times measured in weeks.

**Fourth — largest, and separable.** G2 (code→graph). It is what makes
"bi-directional" true rather than aspirational, and it is a self-contained
piece of work someone can own end to end. G4 (LocalStack plan, price book) sits
alongside it.

**Throughout.** G9.
