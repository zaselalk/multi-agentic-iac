# Future work

`RESEARCH-GAPS.md` is the register of what was missing and what closed it.
`PLAN.md` was the order it got done in. This is what is *left*, written to be
read by someone who did not do any of it — a supervisor, an examiner, or
whoever picks the work up next.

It is deliberately split three ways, because "not built" covers three very
different situations and running them together is how a limitations section
turns into an apology:

- **A — what the research still needs.** One gap, G7. Without it there is a
  system and no result.
- **B — built to an interface and left there, on purpose.** Each of these has a
  reason it was not finished that is stronger than "we ran out of time".
- **C — the limits of what *was* built.** Things that work, within a boundary
  that has to be stated or the claims overreach.

Section D is the part that is genuinely future research rather than remaining
engineering.

---

## Where the system stands

Closed: **G1, G2, G3, G4, G5, G6, G8**. In plain terms, the system now does all
of this, and each part is checked rather than asserted:

- A human and an agent co-edit one graph. A hand edit is validated in ~110 ms
  and **never silently repaired**; a concurrent edit is detected, held, and
  merged where the two compose.
- A validator objecting to something somebody actually asked for **stops and
  offers its fix as a before → after diff** instead of reversing the request.
  The reply is composed after the loop settles, so it describes the outcome
  rather than the plan.
- The graph is proved against a real `terraform plan`, **offline**, in ~8 s —
  and the plan JSON reaches the Security Prover, so a policy can be written
  against values only the provider knows.
- The generated Terraform is **read back and compared to the graph on every
  compile** (MACOG Eq. 11), at no measurable cost.
- Somebody else's `.tf` file **opens as a canvas**, with an honest report of
  everything that could not be represented.

Objectives (a) through (d) are met. What is missing is (e): showing it works.

---

## A. What the research still needs — G7, and only G7

This is the gap that decides whether the work is publishable. Everything in
sections B and C is a limitation to state; this is a hole in the result.

The reason it is still open is worth recording rather than hiding: the plan
said to start it *in parallel* with the system work, precisely because it is
the only part whose schedule cannot be compressed by working harder. That did
not happen. It is now the critical path, and the ethics application is the
critical path within it.

### A1. Ethics approval — start first, finish last

Nothing else here has a lead time measured in weeks. Submit before the study
design is final; the protocol can be amended, the waiting cannot be recovered.

### A2. Seeded-fault benchmark — **BUILT, 2026-09-07**

`benchmark/`, with a committed run in `benchmark/RESULTS.md`. Deterministic and
free by default (the Architect is stubbed), `--model` for the repair columns,
`--ablate` for the table. Headline: **detection 100% of 27 cases, attribution
100% of the 22 that have a node, and nothing silently rewritten.** The
`- devops` ablation removes exactly one fault class — which is the entire
argument for W2 in one row.

It found two real defects in the system on its first run, and one in its own
scoring once a real model was put behind it. All three are recorded in
`RESULTS.md`.

**What is left here:** grow the corpus with faults nobody wrote a rule for.
Detection at 100% against a system's own feature list is the expected result,
not a finding; it only becomes informative when the corpus can surprise it.

**The original plan:**

Take a corpus of valid graphs, inject **one** known fault into each, and
measure what the system does. Fault classes the system already has validators
for, so each has a defined right answer:

| Fault | Injected as | Should be caught by |
|---|---|---|
| Public object storage | `acl: public-read` on a bucket | `s3_public_acl` |
| Unencrypted database | `storage_encrypted: false` | `rds_storage_encrypted` |
| Tag override | a node tag shadowing a project default | `plan_default_tags_resolved` (plan only) |
| Dependency cycle | a `depends_on` back-edge | `dag_cycle_detection` |
| Residency breach | region outside `allowed_regions` | `region_not_allowed` |
| Out-of-registry resource | a resource key not in `schema.json` | `registry_coverage` |
| Broken invariant | a registry entry losing `companion_resources` | `round_trip_equivalence` |

Four measures, per fault class:

- **Detection rate** — did a validator fire at all.
- **Attribution accuracy** — did the counterexample name the **right
  `node_id`**. This is the metric that is *yours*: nothing in the literature
  reports it, because nothing else addresses a failure to a visual element.
  Every counterexample in this system carries a `node_id`, so it is measurable
  without any new instrumentation.
- **Repair rate** within K attempts (`VISOR_MAX_REPAIRS`, default 2).
- **Repair minimality** — nodes changed beyond the faulted one. MACOG claims
  "minimal edits, not speculative rewrites"; this makes the claim a number.

Ablate the way MACOG's Table 4 does. Three of the four switches already exist
as environment variables — `VISOR_POLICY_DIR` pointed at an empty directory
turns the prover off, `VISOR_DEPLOY_VALIDATION=0` turns the DevOps validator
off, `VISOR_MAX_REPAIRS=0` sets the repair budget to zero. Turning the
harmonizer off needs a one-line switch it does not have yet. The result is a
table comparable **in form** to MACOG's — not in value, because the task is
different, and claiming otherwise would be the easiest way to lose a reviewer.

Two things make this cheaper than it looks. `mcp-server/tests/` is already the
harness pattern — stdlib `unittest`, no network. And the round-trip check is
itself a seeded-fault test: `BrokenRegistryTest` breaks a registry entry on
purpose and asserts the break is reported.

**Re-run it as anything changes.** The numbers should improve over time, and
that trend is itself a result.

### A3. The text-only baseline — nothing compares without it

Same model, same policies, same orchestrator, **chat only, no canvas**. A small
CLI is enough; the HTTP API already supports every call it needs
(`/projects`, `/chat`, `/verify`).

Without this there is no "compared to text-based workflows" in any sentence
the dissertation writes. It is a day of work and it gates the headline claim,
which is an uncomfortable ratio — build it early.

### A4. The human study — the actual contribution

The proposal names the right two metrics. They need operational definitions:

- **State Reconciliation Accuracy.** After a session, does the graph the
  participant believes they built match the Terraform that was emitted?
  Operationalise as: show them their final diagram and the compiled HCL, and
  count the discrepancies *they* identify. Zero drift is the claim under test.
  Note that the round-trip check now gives an independent, automatic measure of
  the same property — so this measures whether the *human's* mental model
  tracks the artefact, which is the interesting half.
- **Correction Speed.** Wall-clock from a violation being introduced to it
  being resolved, visual vs. the A3 baseline.

Add three the system can now report for free, because the plumbing exists:

- **Agent suggestions accepted vs. refused.** Every intent conflict produces an
  explicit two-button decision, and the choice is recorded. This measures
  whether the visual channel makes agent reasoning legible enough to disagree
  with — which is closer to the actual thesis than either headline metric.
- **Breakpoint outcomes** — how many were approved, dismissed, or abandoned.
- **Task completion rate.**

Design points a reviewer will look for: within-subjects with order
counterbalancing, n ≥ 12, tasks with objectively checkable end states, and a
pilot before the real thing.

---

## B. Built to an interface, and left there

Each of these is a working stub with a settled contract and a documented
reason. None is an oversight, and the reason matters more than the gap.

### B1. Cost and Capacity Planner — `validators/cost.py`

**Why not built:** it needs a pinned price catalogue, and inventing one would
be worse than reporting nothing. A cost figure nobody can trace is exactly the
kind of evidence a proof-carrying bundle exists to exclude. It reports
`skipped`, which the orchestrator surfaces as an *unproven obligation* rather
than a pass — the honest state.

**What W2 already did for it:** the plan artifact carries every SKU as the
provider resolves it (`instance_class`, `allocated_storage`, `storage_type`,
`billing_mode`) rather than as the graph happens to spell it. The hard half of
keying a price book is done.

**To finish:** a `price_book.json` stamped with its catalogue date, `estimate()`
walking `compiled["plan"]["resources"]`, and a `cost_violation` counterexample
per node when the total exceeds `settings["budget"]`. Half a day once the
catalogue exists.

### B2. Memory Curator — `agents/curator.py`

**Why not built:** MACOG's own ablation makes it the mildest of the eight
(74.02 → 72.17), so it was correctly last.

**Why it is more interesting here than in MACOG:** the motifs would be
*visual*. A verified motif is a subgraph **plus its layout**, so reusing one
restores the arrangement a person recognises, not just the resources. That is
the "Verified Visual Motifs" line in the proposal, and there is no equivalent
in a text-first system — which makes it a contribution rather than a port.

`shape_key()` is implemented already, because the structural key had to be
agreed before anything could be stored and it is testable without a store.

### B3. Proximity semantics — `spatial_semantics.proximity`

**Why not built, and this one is a decision rather than a delay:** distance is
an ambiguous signal. Two nodes may sit together because they are related, or
because the auto-layout put them there. The schema states the rule explicitly —
proximity is `suggestion_only`, `binding: false` — and an ambiguous signal must
never reach the compiled artefact.

Nesting was implemented instead, and gated on the registry, because it is
unambiguous: a node dropped *inside* a container is a statement, and it becomes
a dependency only where the registry declares a reference that can express it.

**If it is ever built,** proximity should reach the Architect as context for a
suggestion the human accepts or rejects — never the compiler.

### B4. The deterministic half of Error-to-Edit

`agents/repair.py` implements MACOG's routing decision — which counterexamples
are worth a model round, which need a human, which cannot make progress — but
every repair still goes back through the Architect.

Many repairs do not need a model at all. A policy rule that names its own
`patch` is already applied deterministically (that is how the intent-conflict
offer works, with no model call); the same mechanism could clear the
non-contradicting cases too. That would make the repair loop cheaper, faster
and reproducible, and would shrink the surface where a model can do something
surprising. **This is the highest-value item in section B** and the one with
the clearest path.

---

## C. Limits of what was built

These work. The boundary has to be stated.

### C1. Registry breadth

**Ten AWS resource types, one provider.** Everything the system does — the
compiler, the decompiler, the importer, nesting, companions — is driven by
`schema.json`, so breadth is data rather than code. But ten types is a
demonstration, not coverage, and every claim about "real infrastructure" is
bounded by it.

The importer's `unmapped` list is now the honest measure: import a real
project and its length is exactly how far the registry is from covering it.
**Reporting that number for a few public Terraform repositories would cost an
afternoon and would strengthen the dissertation more than almost anything else
in this document.**

### C2. Policy set size

Ten rules across five files. Enough to demonstrate IR-grounded and
plan-grounded proving side by side; not enough to claim compliance coverage.
Adding rules needs no code — a `.rego` file under `package visor.*` is picked
up — so this is a corpus problem, not an architecture one.

### C3. `terraform apply` is deliberately absent

Everything up to `plan` is side-effect-free and runs on every verification.
`apply` is not, and a system whose entire argument is that it does not change
things behind your back should not be the thing that creates them. Nothing in
the design forbids it later; the position is that it needs a different consent
model than a Verify button.

### C4. Drift is desired-vs-last-compiled, not desired-vs-live

`drift_check` compares the graph against the last `compile_terraform` snapshot.
The schema declares `state_model: "desired_vs_actual"`, and "actual" here means
*what we last emitted*, not what exists in a cloud account or a Terraform state
file. Reading a real `terraform.tfstate` is the missing piece, and the decompiler
makes it tractable — state JSON is closer to plan JSON than to HCL, and the
normalisation for that already exists.

### C5. What an import cannot bring across

By construction, and reported rather than dropped: modules are not expanded,
data sources have no node, and a resource using `count`, `for_each` or a
provider alias is **refused** rather than imported as a single node — because a
canvas saying "one EC2" where the file says three looks complete and is wrong.
Heredocs and nested blocks richer than the registry's are named as gaps.

The obvious extension is `count`/`for_each` as a node property with a
multiplicity badge on the canvas. It is a real design question, not a small
one: it changes what a node *is*.

### C6. Intent is inferred from presence

The rule that keeps the system from reversing a decision is: every
`desired_state` key that is *there* is somebody's, and a key that is absent is
nobody's. It is deterministic, needs no extra model call, and makes a refused
fix stick across later turns.

It cannot distinguish a value a person chose from one a default put there. It
errs towards asking, which is the safe direction — the cost is a question that
did not need asking, and the cost the other way is the system doing the
opposite of what it was told.

### C7. Single-user, single-session

Conflict detection handles a human and an agent editing concurrently. Two
*humans* on one project is not modelled: projects are files on disk with a
process-level lock, and there is no presence, no per-user identity and no
operational transform. The ledger's `author` field would carry it, which
is why the abstraction is right even though the feature is absent.

### C8. Tests

28 in `mcp-server/tests/`, covering the decompiler, the round-trip property and
the importer — including negative cases that break the registry on purpose,
because a check that cannot fail proves nothing. Still missing, and named in
G9:

- **Golden HCL** for a fixed graph, pinning the compiler's output.
- **Adapter round-trip** — `canvas_to_nodes ∘ nodes_to_canvas`. W2 found a real
  loss here (a `tags` map returned as a JSON string) that this test would have
  caught first.
- **State machine** with a stub Architect: assert J is non-increasing and the
  repair budget is respected.
- **`opa test`** for the policies — Rego has a native test framework, and the
  A2 seeded-fault corpus doubles as its fixtures.

Nothing in `visual-devops-builder` or `multi-agentic-iac` has tests at all.

---

## D. Beyond the dissertation

Directions that follow from the contribution rather than completing it.

**D1. Registry synthesis from provider schemas.** `terraform providers schema
-json` emits the full attribute set for every resource type. The registry's
hand-written parts are the *opinions* — which attributes are compliance
companions, which references are structural, what is taggable. Generating the
mechanical parts and hand-writing only the opinions would take coverage from
ten resource types to hundreds, and would turn C1 from a limitation into a
result.

**D2. Attribution accuracy as a shared benchmark.** The metric in A2 exists
because this system addresses failures to visual elements. If the seeded-fault
corpus and its scoring were released, other visual-IaC tools could be measured
on it. That is a smaller, sharper contribution than the system itself, and a
more citable one.

**D3. Policy authoring from the canvas.** Policies are Rego today, which means
the person who can express a constraint is not the person drawing the diagram.
The plan-grounded input document is regular enough that a constrained visual
policy builder is plausible — and it would close the loop the research opens,
since the whole argument is that the visual channel should carry reasoning
rather than only shapes.

**D4. Live drift and reconciliation.** C4 plus a scheduled `terraform refresh`
gives a canvas that shows what *is* rather than what was asked for, with the
same counterexample machinery pointing at real divergence. This is the
"Zero-Drift Architecture" claim in its strong form.

**D5. Multi-human collaboration.** C7, properly: the three-state conflict
detection generalises from (base, human, agent) to (base, human A, human B,
agent) without changing its shape.

---

## If you only do four things

| | | Why |
|---|---|---|
| 1 | **A1 — submit the ethics application** | The only thing whose clock you cannot speed up. Still not done. |
| 2 | ~~A2 — the seeded-fault benchmark~~ | **Done 2026-09-07.** Re-run it as things change; the trend is a result. |
| 3 | **A3 — the text-only baseline** | A day's work, and every comparative claim depends on it. |
| 4 | **C1's measurement — import three public Terraform repos and report `unmapped`** | An afternoon, and it converts the largest limitation into a stated, quantified boundary. |

Everything in B and C can be a paragraph in the limitations section. G7 cannot.
