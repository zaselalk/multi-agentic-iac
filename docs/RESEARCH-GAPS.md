# Research gaps

What the system does today, what it does not, and what has to be built to
finish the research. Every claim below was checked against the code on the
`feat/visor-integration` branch, not inferred from the proposal.

Gap IDs (`G1`…`G9`) are referenced from the source and from the other READMEs.

This is the register of **what** is missing and why, and what closed it.
Deviations from the proposal — mechanisms named on slides 9–10 that were built
differently — are recorded separately below, and are decisions rather than
gaps. [PLAN.md](PLAN.md) was the order it got done in.
[FUTURE-WORK.md](FUTURE-WORK.md) is what is *left* — written for someone who
did not do any of it, and separating what the research still needs from what
was deliberately left as an interface from the limits of what was built.

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
- The Security Prover: OPA over seven Rego rules in four policy files,
  evaluated on the typed IR, with every violation carrying the `node_id` it
  belongs to. The IR is parsed back out of the emitted HCL, so it describes
  what Terraform will actually see (G1).
- Validation on every hand edit, at ~110 ms per save, reported and never
  auto-repaired (G5).
- Nesting on the canvas compiling to real Terraform references, gated on the
  registry, with no edges drawn (G3).
- Concurrent-edit detection: a hand edit landing mid-turn is held rather than
  overwritten, and merged on approval where the two edits compose (G6).
- Intent routing: a validator objecting to something somebody actually asked
  for stops the turn and offers its fix as a diff, instead of reversing the
  request silently. The reply is composed after the loop settles, so it
  describes the outcome rather than the plan (G6).
- The canvas rendering all of it — findings on the nodes that caused them,
  a validator strip where `skipped` reads as unproven, an offered fix ghosted
  on the node as before → after, and a breakpoint banner that can actually
  release a paused turn (G8).
- The round-trip check, on every compile: the Terraform this graph produced,
  read back and recompiled, must still be the same Terraform (G2, MACOG
  Eq. 11).
- Importing Terraform this system did not write, with a report of everything
  that could not be represented — which doubles as the first measure of how
  much real Terraform the registry covers (G2).
- The DevOps validator, grounded against the provider: `init -backend=false`,
  `validate`, `plan -out` and `show -json`, all offline, in ~8 s. The plan is a
  controller-owned artifact the Security Prover receives too, so a policy can be written
  against values only the provider knows (G4).
- Agentic breakpoints on destructive edits, and the proof-carrying evidence
  bundle.

Not built at all: cost estimation, the Memory Curator, real-state drift, and an
evaluation protocol.

**Closed so far:** G1, G5 (2026-09-06); G2, G3, G4, G6, G8 (2026-09-07). G4's
cost half stays open on purpose — see below. **G7 (evaluation) is the only gap
left that blocks the result, and its automatic half now exists** —
`benchmark/`, 27 seeded-fault cases with an ablation table. What remains of it
needs people.

---

## Deviations from the proposal

Four mechanisms named in the proposal presentation (slides 9–10) were not
built as named. None of them is a shortfall — three are strictly stronger than
what was proposed, and one was a requirement that dissolved under inspection.
They are recorded here because an unexplained deviation reads as an oversight,
while an explained one reads as a decision, and the proposal is the document
an examiner will hold.

Unlike `G1`…`G9`, nothing in this section is open. It is here to be cited.

### D1 — LangGraph → a hand-rolled deterministic controller

**Proposed:** "LangGraph Orchestration: Cyclic state machine managing agent
transitions and human-in-the-loop interrupts."

**Built:** `orchestrator/state_machine.py`, with no LangGraph dependency
anywhere in the project.

**Why.** The claim this system makes is that the pipeline is *deterministic
except where it is explicitly not* — only `plan` and `repair` call a model,
both through the Architect, and everything else is code whose output is a
function of its input. A framework that owns control flow makes that claim
harder to demonstrate, not easier: the reader has to take the framework's
scheduling on trust. Here the FSM is 491 lines that can be read end to end,
the repair loop is Algorithm 1 written out with its `J` non-increasing
guard visible, and the human-in-the-loop interrupt is an ordinary `return`
rather than a framework primitive.

This is a case where the implementation is more defensible than the plan, and
the benchmark depends on it: the four ablation columns in `benchmark/RESULTS.md`
are produced by disabling components in this controller, which is only
meaningful because the controller is the thing that decides.

### D2 — Grammar-constrained decoding → no decoding at all

**Proposed:** "Constrained Synthesizer: Compiles validated schemas into .tf HCL
code using grammar-constrained decoding to eliminate hallucinations."

**Built:** a deterministic compiler in `mcp-server/compiler.py`. The model
never emits HCL.

**Why.** Constrained decoding narrows a model's output space to
grammar-admissible tokens; it reduces the rate of invalid output but the model
is still the thing producing the text. Here the graph is lowered to HCL by
code — `schema.json` sets `compiler.strategy.llm_allowed: false` — so there is
no decoding step to constrain and a hallucinated provider field cannot be
emitted at all. Not generating is the limit case of constrained generation.

MACOG needs constrained decoding because its Engineer generates HCL text. The
Engineer row in `orchestrator/agents/__init__.py` is a compiler rather than a
prompt for exactly this reason.

### D3 — MCP "real-time deltas" → request/response, with SSE for the trace

**Proposed:** "MCP Bridge: Implementing a Python-based MCP server/client to
stream Real-Time Deltas."

**Built:** MCP is request/response — `set_graph` pushes the canvas, `get_graph`
reads back an agent's edits. Server-sent events stream the *agent trace* from
orchestrator to canvas while a turn runs, not graph deltas over MCP.

**Why, and the honest form of the claim.** The user-visible requirement behind
"real-time" is that a turn should be watchable while it happens rather than
only readable afterwards, and that is met: `POST /projects/{id}/chat/stream`
emits a `state` event per FSM transition and a `write` event per ledger entry,
measured arriving from 0.0s of a ~7s turn through the canvas's own proxy.
Delta streaming at the MCP layer would be an optimisation of a channel that
carries one graph per turn between two processes on the same host. It is not
implemented, no result depends on it, and this is the deviation to state
plainly rather than reinterpret — the claim should be narrowed to what SSE
delivers.

### D4 — LocalStack → `terraform plan` offline

**Proposed, and assumed throughout early planning:** the DevOps sandbox needs
LocalStack.

**Built:** real Terraform (v1.9.8) running `plan` against placeholder
credentials with the provider's skip flags — see `compiler.preamble.plan_mode`
in `schema.json`. No container, no account, no network past the one-time
provider download.

**Why this matters more than the convenience.** MACOG's ablation shows the
DevOps sandbox is the costliest component to remove — IaC-Eval 74.02 → 56.93,
the largest drop of its eight. This environment cannot run LocalStack at all
(no Docker; `post-create.sh` never ran), so the component with the largest
measured contribution looked unavailable. It turned out not to need one:
`terraform plan` resolves the real provider schema, expands every default, and
emits plan JSON offline.

That plan is what the IR structurally cannot carry. The IR says
`tags = merge(local.default_tags, ...)`; the plan says
`tags_all = {"Owner": "visor", ...}`. So `deploy` runs *before* `prove`, which
is not MACOG's order, and the plan becomes an input to the Security Prover.
`benchmark/RESULTS.md` shows the payoff directly: `tag_override` is detected
100% by plan-grounded policy in the full configuration and **0% with `devops`
removed** — and 0% with `prover` removed too, since a plan-grounded rule needs
both the plan and something to evaluate it. All 5 of the DevOps validator's 27
cases are this fault class. It is undetectable without a real `terraform plan`.

**A simplification over MACOG worth stating as one:** the sandbox ablation's
benefit is captured without the sandbox.

---

## The gaps

| | Gap | Blocks objective | Size | Status |
|---|---|---|---|---|
| **G1** | The IR is lossy — compliance companions never reach it | (a) schema, (b) conflict detection | S | **Closed** 2026-09-06 |
| **G2** | No code→graph direction; "bi-directional" is unproven | (a) schema — **the title** | L | **Closed** 2026-09-07 |
| **G3** | Spatial metadata is carried but never interpreted | (a) schema, (c) canvas | M | **Closed** 2026-09-07 |
| **G4** | Validators stop short of runtime grounding | (b) orchestrator, (d) validation loop | M | **Closed** 2026-09-07 (cost open) |
| **G5** | A human edit does not trigger the validation loop | **(d) — directly** | S | **Closed** 2026-09-06 |
| **G6** | Conflict detection is declared in the schema, unimplemented | (b) — **the research question** | M | **Closed** 2026-09-07 |
| **G7** | No evaluation protocol | all | L | Open |
| **G8** | The canvas does not render what the backend now emits | (c), (d) | M | **Closed** 2026-09-07 |
| **G9** | No tests, in any of the three repos | reproducibility | M | Open |

---

### G1 — The IR is lossy — CLOSED

**What was wrong.** The IR and the HCL were assembled independently and had
drifted in both directions. Compliance companions —
`aws_s3_bucket_public_access_block`, the SSE configuration, the versioning
resource — reached the HCL and never the IR; so did `tags` and `static_blocks`.
Going the other way, `versioning_status` sat in the IR as an attribute of
`aws_s3_bucket`, which the emitter filters out as a derived key, so the IR
described a field Terraform never sees.

Because validators read the IR, this bounded what could be checked at all.

**What shipped.** `_emit_resource` and `_emit_companions` now return the IR
alongside the HCL, and the IR half is `parse_body` run over the rendered body —
a generic block parser, since the input is always text this compiler produced.
Divergence stopped being something to keep in sync and became
unrepresentable. Companions carry the `node_id` that induced them, plus
`generated_by` and the registry's `reason`.

Verified on a five-node graph: 8 resources emitted, 8 in the IR, every
top-level attribute key present in both, `terraform validate` still passing.

**What it unblocked.** Three policies that could not previously be written, each
now shipped and tested — `s3_missing_public_access_block`, `ebs_root_encrypted`
(reads the `root_block_device` static block), and `missing_default_tags` (reads
the merged `tags` expression, the fourth of the four checks MACOG names). They
double as a regression test for a registry entry silently losing its
`companion_resources`, `static_blocks` or `taggable` flag.

**Still open here.** The round-trip check this was a prerequisite for still
needs G2 — an IR that faithfully describes the HCL is necessary for
`equiv(P₁, P*)`, not sufficient.

### G2 — No code→graph direction — CLOSED

The title promises bi-directional synchronisation. What existed was
canvas ⇄ graph ⇄ HCL, where the last arrow pointed one way only, with no HCL
parser anywhere in the three repos.

So the system could not:

- run MACOG's round-trip check, which is the guarantee that compilation
  preserved intent — **now it does**;
- reconcile a change made in the `.tf` file by hand, which is the drift case
  the "Zero-Drift Architecture" claim rests on — **now reachable**;
- import an existing Terraform project onto the canvas — **now it does**.

**What shipped (2026-09-07): `mcp-server/decompiler.py`.**

The restriction is what makes it tractable, and it is the same insight that
closed G1: parsing HCL *this compiler emitted* is a bounded problem. Arbitrary
Terraform means modules, `count`, `for_each`, dynamic blocks, interpolation and
provider aliases. Registry-driven output from ten resource types means
splitting blocks and inverting a table that already exists. No `python-hcl2`,
no new dependency — `parse_body` was already there, because the IR is parsed
out of the emitted body.

What is inverted:

| In the HCL | Recovered as |
|---|---|
| `resource` block | a node, keyed by its Terraform local name |
| a companion | dropped — **unless** it carries intent (below) |
| `static_blocks` | dropped; the compiler regenerates them |
| `tags = merge(local.default_tags, {…})` | the map, minus the generated `Name` |
| a value equal to the registry default | dropped — it is the registry's, not the user's |
| a value equal to a `computed_attributes` template | dropped, same reason |
| any `aws_x.y` address in the block | `depends_on` |
| a type no registry entry accounts for | reported in `unmapped`, never silently dropped |

**Companions are not uniformly noise, and assuming they were would have been a
silent bug.** A bucket's public access block is pure compiler output. But a
companion with `emit_when` exists *because* a node asked for it, so
`aws_s3_bucket_versioning` being present is the only place `versioning: true`
survives — the attribute is virtual and never emitted as a field. Dropping all
companions alike loses it without a trace, which is precisely the class of loss
the check is for.

**The comparison is between the two compiled artifacts, not the two graphs.**
Comparing graphs drowns in questions with no answer — was this value explicit
or a default, did the user write `class` or `instance_class` — none of which
change what Terraform receives. Comparing what they compile to asks the only
question that matters: *does the graph recovered from this file still produce
this file.* Differences are reported per resource, addressed to nodes.

It runs on **every compile**, in the `compile` state, and costs nothing
measurable — a hand edit is still ~110 ms end to end. A failure is reported and
**never repaired**: the graph is not what is wrong, so handing it to the
Architect would have it edit a correct graph to work around a compiler defect.
`round_trip_equivalence` is in `NEEDS_HUMAN` for that reason. The canvas shows
the verdict whether it passes or fails — a claim nobody can see being tested is
a claim.

**Tested, including the failures.** `mcp-server/tests/test_round_trip.py`, 12
cases, stdlib only:
`python3 -m unittest discover -s tests -t .`. One node of **every registered
type** in one graph round-trips byte for byte, which makes the coverage claim
concrete: a new resource type that cannot be read back fails the day it is
added, not the day someone tries to import a file. Half the file breaks the
registry on purpose — a companion losing its `emit_when`, a companion removed
after the HCL was written — and asserts the break is reported. A check that
cannot fail proves nothing.

**And then the larger half: importing arbitrary Terraform (W3b).**

`decompiler.import_terraform`, the `import_terraform` MCP tool, and
`POST /projects/import/terraform`. Same registry inversion, different front
end: `python-hcl2` when it is installed, the built-in parser when it is not,
and the result says which ran. Real Terraform has comments, heredocs,
interpolation, nested blocks, `count`, `for_each`, modules and data sources,
and hand-rolling a parser for that would get it wrong quietly. `mcp-server`
stays dependency-free — the import is the one optional extra, documented in its
`requirements.txt`.

**The design decision that matters is what happens to what it cannot
represent**, and it is not one rule but three, because the failures are not
alike:

| | Example | What happens |
|---|---|---|
| No registry entry | `aws_kinesis_stream` | listed in `unmapped`; no node |
| Cardinality or placement changed | `count = 3`, a provider alias | **refused** — listed and not imported |
| One thing missing from a real resource | a heredoc, a `lifecycle` block, a `root_block_device` richer than the registry's | imported, and the gap named in `unsupported` |

The middle row is the one worth arguing for. A `count = 3` resource *could* be
imported as one node, with a footnote. That produces a canvas saying "one EC2"
where the file says three — it looks complete, and it is wrong. A resource
whose cardinality or account cannot be represented is refused and named; a
resource that is merely missing an attribute is still worth having.

Variables are the one non-resource block that does come across. A file tagging
`Env = var.env` compiles to Terraform that fails `terraform validate` if the
declaration is left behind, so referenced `variable` blocks ride along in
project settings and the compiler emits them with their declared types. An
import that is visible but not usable is not an import.

**Verified end to end** on a hand-written file with a module, a data source,
two variables, a `count`, a heredoc, an unknown resource type and an
interpolated tag. Four of six resources imported; the other two named. The
resulting project **compiles clean, passes `terraform validate` and a real
`terraform plan`, passes every policy, and round-trips byte for byte.**

**Two real defects the import found**, both in W3a's own decompiler and neither
reachable without a file this system had not written:

1. `_node_tags` read only *quoted* tag values, so `Env = var.env` was dropped
   and the round trip failed. It now keeps unquoted values as expressions.
2. `Name` was dropped from every tag map, on the grounds that the compiler
   generates it. Somebody else's `Name = "main-vpc"` is theirs — it is dropped
   now only when it equals the resource's local name.

Both were caught by running `/verify` on an imported project, which is the
round-trip check doing exactly the job it was built for.

### G3 — Spatial metadata is carried but never interpreted — CLOSED

**What was wrong.** `view` carried `position`, `parent_id` and `style`
faithfully and the compiler never read any of it, so dropping an EC2 inside a
subnet box communicated nothing. Worse than the original write-up recorded:
`parent_id` was never *produced* either. VPC and subnet nodes were built as
containers — resizable, transparent, dashed — and nothing ever assigned
children to them, so nesting was neither expressible nor producible.

**What shipped.** A `spatial_semantics` block in `schema.json` (v3.2.0) states
what a position is allowed to mean, and both halves now implement it:

- **Nesting is binding, gated on the registry.** A node nested in a parent
  gains an implied `depends_on` only where the child's registry entry declares
  a reference whose `from_resource` is the parent's resource. A subnet in a VPC
  implies `vpc_id`; an EC2 in a VPC implies nothing; an S3 bucket in a VPC
  implies nothing. The gate is what stops nesting inventing a relationship
  Terraform has no way to express. Verified: nesting alone, with no edges
  drawn, compiles to real `vpc_id` and `subnet_id` references.
- **Proximity is not binding, and not implemented.** Distance is ambiguous —
  two nodes may sit together because they are related, or because the layout
  put them there — and an ambiguous signal must not reach the compiled
  artefact. The block records that it may become a suggestion the human
  accepts. That is the remaining piece.
- **The canvas produces it.** Dropping into a container parents to the
  innermost one; dragging in or out re-parents.

**The property that took the most care: idempotence.** Derived edges are
returned marked `data.implied` and dashed, and `canvas_to_nodes` skips any edge
carrying that flag, re-deriving from `parent_id` each time. Without it the
implication bakes itself in on the first save — the derived edge comes back as
an explicit one, and un-nesting no longer removes the dependency. Verified by
nesting, round-tripping, un-nesting, and confirming the dependency is gone.

**Found on the way.** `rds` nested in a `subnet` implies nothing, because the
registry declares no reference for it. That is the honest answer and the gate
working; if an RDS should take a subnet group, the fix belongs in the registry.

### G4 — Validators stop short of runtime grounding — CLOSED (except cost)

`terraform validate` parses HCL against the provider schema. It does not
resolve references, expand counts, or discover that an instance type is
unavailable in a region. MACOG's ablation makes this the single most costly
component to omit: removing the DevOps sandbox drops IaC-Eval 74.02 → 56.93,
the largest drop of the eight.

Also unbuilt: the Cost & Capacity Planner (`validators/cost.py` is an interface
and a no-op; it returns `skipped`, never a number).

**Correction to an earlier claim here.** This section used to say the
devcontainer already configures LocalStack. It does not: `post-create.sh`
installs it with `/opt/conda/bin/pip`, and there is no conda in this container,
so that line has never run. Docker is absent too, and LocalStack runs as a
container — so the LocalStack route is not available at all.

It turns out not to be needed. **`terraform plan` runs completely offline**
with dummy credentials and the provider's skip flags:

```hcl
provider "aws" {
  region                      = var.region
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
  skip_region_validation      = true
}
```

Verified on a four-node graph: `Plan: 6 to add, 0 to change, 0 to destroy`, no
network, no account, no Docker. `-out` plus `terraform show -json` then yields
the plan JSON — `resource_changes`, `planned_values`, `after_unknown` — which
is the document MACOG's and IaC-Eval's OPA policies are written against, and
the thing `policies/README.md` names as what IR evaluation cannot see.

**What shipped (2026-09-07).**

`compiler.preamble.plan_mode` in `schema.json` holds those provider arguments,
and the orchestrator compiles **twice**: once normally, for the HCL a human
reads and exports, and once in plan mode, for the copy Terraform is given.
Emitting placeholder credentials and skip flags into an export would be handing
someone a configuration that quietly disables its own safety checks, so the two
never mix — and both come out of the same deterministic compiler.

`validators/terraform.py` runs `init -backend=false` → `validate` →
`plan -out` → `show -json` and returns an **artifact, not a verdict**:
`stage` says how far it got, `resources` are the planned changes with a
`node_id` attached to each, `unknown` is `after_unknown`. `validators/deploy.py`
interprets it; the Security Prover reads the same artifact as `input.plan`.

**The order changed, deliberately.** MACOG runs the DevOps sandbox last, as a
final gate. Here the plan is an *input* to the prover, so the machine runs
`compile → deploy → review → prove → price`. Proving after grounding is the
only order in which a plan-grounded policy can exist at all.

`policies/plan_grounded.rego` proves the claim. Same graph, same policy set:

| | `input.ir` only | with `input.plan` |
|---|---|---|
| A node setting `Owner = "platform-team"` | **pass** | **fail** — `plan_default_tags_resolved` |

The IR holds `tags = merge(local.default_tags, ...)`, which is all
`tagging.rego` can check and is satisfied. The plan holds
`tags_all = {"Owner": "platform-team", ...}`, which is what will exist. The
canvas says which verdict it got, under the validator strip.

**Latency.** A fresh temp directory per run meant `terraform init` re-downloaded
the AWS provider every time: 24 s per verification, and a failure whenever the
registry was slow. The provider directory is now reused — as a plugin cache on
the first run, and as a **filesystem mirror** on every run after, which is
consulted before the registry, so later runs touch no network at all. **24 s →
8 s**, and stable. (Cache and mirror must be separate settings over one
directory, not both at once: Terraform refuses to "install existing provider
directory to itself".)

**Three real defects this found**, none of which any earlier check could have:

1. A node setting its own `tags` compiled to **two `tags` arguments in one
   resource** — invalid HCL. Terraform refused to initialise, so nothing
   downstream ever ran. The compiler now folds a node's tags into the `merge()`
   call, where they beat both the project defaults and the generated `Name`.
2. `terraform init` failing was reported as `skipped: no network`, which is how
   defect 1 stayed hidden — a configuration error explained away as an
   environment problem. Init failures are now classified, and a config error
   **fails**.
3. A `tags` map survived one agent turn and came back from storage as the
   *string* `"{\"Owner\": \"platform-team\"}"`. The canvas adapter
   JSON-encodes maps and lists on the way out; nothing decoded them on the way
   back. `compiler._coerce` now does.

**Still open: cost.** `validators/cost.py` returns `skipped`. The plan makes the
harder half easy — every SKU is there as the provider resolves it
(`instance_class`, `allocated_storage`, `storage_type`, `billing_mode`) rather
than as the graph happens to spell it. What is missing is a pinned price
catalogue, and that is the half that must not be guessed: a cost figure nobody
can trace does not belong in a proof-carrying bundle. It stays honestly
`skipped` until someone pins one.

### G5 — A human edit does not trigger the validation loop — CLOSED

**What was wrong.** `POST /projects/{id}/graph` — what the canvas calls on every
drag, drop and field edit — compiled and returned the compiler's schema errors
only. It never ran the Security Prover. A human who set a bucket's ACL to
`public-read` got silence until they happened to start a chat turn.

So the conflict this research is about was detectable by the system and not
surfaced when it actually happened.

**What shipped.** The handler now runs the full validator pass —
`run(intent="", repair=False)` — and returns `validators`, `counterexamples`
and the score alongside the compiler's errors. Measured at **~110 ms** per
save, with `terraform validate` staying off for interactive edits, so it sits
comfortably inside the canvas's 400 ms debounce.

Verified: setting `acl: public-read` by hand raises J = 3.0 with
`s3_public_acl` addressed to `logs-s3` at edit time; reverting clears it.

**The escalation rule, decided.** A hand edit is validated and **never
repaired**. The alternative — the agent quietly rewriting what someone just
drew — is precisely the failure mode recorded in G6, and doing it in response to
a drag would be worse, because no one asked for anything. The position taken
is that the system reports and waits; escalating to an agent turn is the
human's call, through `/chat`. State it explicitly in the write-up, because the
opposite choice is defensible and reviewers will ask.

**Found on the way.** With counterexamples finally reaching a human, the
Provider Harmonizer's registry-coverage check turned out to flag `versioning` —
a documented virtual attribute driving the versioning companion — as
unrecognised. Fixed by folding `virtual_attributes` and their derived keys into
the known set. Nothing surfaced it before because nothing displayed it.

### G6 — Conflict detection is declared but unimplemented — CLOSED

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
| Human edit violates a policy the agent knows | **Closed** — reported against the node at edit time (G5) and drawn on it (G8) |
| Human edit and agent edit touch the same node in one turn | **Closed** 2026-09-07 — detected, held, and merged where the edits compose |
| Explicit human *intent* violates a policy | **Closed** 2026-09-07 — held and offered, never reversed |

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

**The third is now closed.** `orchestrator/intent.py` draws the distinction,
and the test it uses is *presence*, not provenance:

> intent = every `desired_state` key that is **there** — the human drew it on
> the canvas, or the Architect wrote it acting on this request.
> omission = a failure about a key that is **absent**, or about no key at all.

`storage_encrypted: false` in a node is somebody's decision, whoever made it
and however long ago. No `storage_encrypted` key at all is nobody's. That is
the whole rule, it needs no extra model call, and it is reproducible.

The first design read intent from the Architect's tool calls alone. Testing it
found the hole: refuse the offered fix once, and the next unrelated turn would
quietly reverse the decision, because the human's choice was in the graph but
not in that turn's trace. Presence fixes that — a decision made is a decision
that sticks.

**Routing.** `ErrorToEdit.route` now takes the intent map and stamps every
escalated counterexample with why: `contradicts_intent` or `needs_human`. A
contradiction never enters the repair loop, so the graph keeps what was asked
for, and the violation stays visible on the node.

**The offer, not the edit.** Where a Rego rule names its own fix — the two new
`attribute` and `patch` fields on a `deny` — the fix is computed
deterministically and returned as a *proposal*: a list of attribute rows, each
with what the value is and what it would become. Nothing is written. The human
takes it (`POST /projects/{id}/proposal`) or refuses it, and refusing needs no
request at all, because refusing is the state the system is already in.

Applying sends the rows rather than the proposed graph, deliberately: an offer
sits on screen for as long as it takes to read, and replacing the whole graph
would roll back anything edited meanwhile — the same failure arriving through
the fix instead of the repair.

**The reply is composed last.** `intent.compose_reply` runs after the loop
settles and appends what actually happened: what was silently fixed, what was
held and why, and whether anything was applied at all. Verified end to end:

> "I have created a PostgreSQL database node named orders-db with storage
> encryption explicitly turned off as you requested. **I have left orders-db as
> you asked, but rds_storage_encrypted rejects it: … Set storage_encrypted to
> true on this database node — take that fix, or keep what you asked for.**"

`repairs: 0`, and the stored graph still says `storage_encrypted: false`.

**A third, found in the same pass.** An unapproved `destructive_edit`
breakpoint raised, and the chat handler saved the agent's graph anyway - so the
resource was already gone by the time the banner asked, and "Keep mine" did
nothing. Being told about a deletion that has happened is not being asked.
`state_machine.run` now returns `withheld` naming why a turn's graph must not
be written, the handler stores nothing when it is set, and the reply says so:

> "I have deleted the sessions DynamoDB table. **Nothing has been deleted yet.
> Removing resources is not something I will do without being asked twice —
> approve it and I will.**"

Verified: the node survives the unapproved turn and is removed on the approved
re-send.

**A second loss, found while testing this.** Conflict detection only fires when
*both* sides changed a node — correctly, since one-sided edits are nothing to
stop for. But the chat handler then wrote the agent's graph, which was built
from the canvas as it was at turn start and does not contain a human-only
mid-turn edit. So the edit was dropped, silently, with no conflict to show for
it. `conflict.diverged` now detects that case and the merge is applied without
asking, because there is nothing to ask. Verified: a bucket created out of band
survived a turn that added an unrelated table, where before it was deleted.

**The second is now closed.** Detection compares three states rather than two:
the graph as the turn started, the graph as stored now, and the graph the agent
produced. A node both sides changed is a conflict; a node one side changed is
not. Comparison is over `desired_state` and `depends_on` only — a human
dragging a node while an agent edits its attributes has not disagreed with
anything, and stopping a turn for that would make the feature unusable.

The schema's two strategies fall out of one test. Two edits to the same node
touching no attribute in common are not a disagreement, they are a merge
(`merge_available`). Two edits to the same attribute are a disagreement no rule
can settle (`human_required`). Either way the turn holds: the human's version
stands and the agent's is offered, not applied.

**Approval applies the merge, not the agent's graph.** This is the part that
matters. The agent's graph does not contain the human's mid-turn edit, so
handing it over on approval would discard that edit — the exact loss this path
exists to prevent, arriving one step later. Verified: with the human setting
`acl` and the agent setting `versioning`, the agent-only graph is
`{bucket, versioning}` and the stored result is `{bucket, acl, versioning}`.

**Found while testing, and worth recording.** The first run reported the agent
as having changed `acl`, which it never touched. `/graph` was calling
`set_graph` on the same MCP session the agent was working in, so a human edit
landed *inside* the agent's in-flight graph and came back out as part of its
result — the two writers were racing inside the session, not merely at save
time. Agent turns now run in their own session. Nothing would have surfaced
this except building the detection and reading its output.

### G7 — No evaluation protocol — PART 1 BUILT

**The seeded-fault benchmark shipped 2026-09-07**: `benchmark/`, with a
committed run in `benchmark/RESULTS.md`. Five graphs covering all ten
registered resource types, eight fault classes, 27 cases, four ablation rows.
Deterministic and free by default — the Architect is stubbed, so the run
measures the architecture rather than the model — with `--model` to fill the
repair columns when someone wants to pay for them.

| | Full configuration |
|---|---|
| Detection | 100% (27/27) |
| **Attribution** | **100% (22/22 attributable)** |
| Fix offered, no model call | 15% (4/27) |
| Nodes silently rewritten | **0** |
| Model rounds across all 27 cases | 13 |

Attribution is the number that matters, and the only one nothing else in the
literature reports. Detection at 100% is the *expected* result rather than a
finding — every fault in the corpus is one the system has a validator for — and
`benchmark/README.md` says so rather than letting the figure oversell itself.

The ablation table is where the components earn their place. Removing the
prover costs 14 of 27 cases; removing the DevOps validator costs exactly 5,
**all of them `tag_override`**, because it is the only fault a plan can see and
the IR cannot. That single row is the whole justification for W2.

**It found two defects in the system on its first run**, neither reachable by
reading the code: `region_not_allowed` was spending a model round in every run
and never clearing it (a region is a project setting; no node edit changes
one), and the presence rule was holding *schema* errors as intent — `bucket
= ""` is not a bucket name somebody prefers, it is a graph that cannot compile.
Both fixed; see `benchmark/RESULTS.md`.

**Still open:** the text-only baseline (A3), ethics approval (A1) and the human
study (A4). See `docs/FUTURE-WORK.md`.

---

**The original write-up:**

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

### G8 — The canvas does not render what the backend emits — CLOSED

**What was wrong.** The orchestrator had addressed every finding to a node id
since the validators were built. The canvas read `data.errors` and
`data.warnings` — the compiler's schema errors — and nothing else, so policy
violations, skipped validators, conflicts and breakpoints all arrived and were
dropped.

**What shipped.**

- **Findings on nodes.** Status is derived from everything addressed to a node,
  and `error` and `violation` are separate — a graph that will not compile is a
  different problem from one that compiles and breaks a rule, so they are red
  and orange with their own glows. The worst finding is printed on the node
  itself: a violation you must open a panel to read is one you will not read,
  and addressing findings to nodes is pointless if they are only listed
  elsewhere.
- **A validator strip, with `skipped` as a caution rather than a neutral.** A
  user who cannot see that cost was never checked will assume it passed.
- **A Verify button** — prove the stored graph on demand, no model call.
- **Ghosting** (2026-09-07). An offered fix is drawn on the node it belongs to,
  as `storage_encrypted false → true`, in a dashed outline labelled "offered,
  not applied", with its own node status (`proposed`) so it does not read as a
  bare violation — a violation has nothing waiting on it, and this has a
  decision waiting on it. The same rows appear in the breakpoint banner with
  **Apply the fix** / **Keep what I asked for**, and in the findings panel as a
  `fix offered` chip. The decision is about a resource, so it is shown on the
  resource; the banner is where it is acted on.
- **A breakpoint banner**, which is the only way to release one. It shows what
  each side changed, whether the two compose, and re-sends with approval. For a
  mergeable conflict it offers "Apply merged version" and promises the human's
  changes are kept either way — true, because the backend applies the merge and
  not the agent's graph.

**Still open.** "Ghosting" — a proposed-but-unapplied graph rendered over the
current one. It needs the backend addition noted originally: the repair loop
returning its patch as a diff for approval rather than applying it and
reporting afterwards. The breakpoint banner is the approval surface that would
carry it, so the frontend groundwork is done.

### G9 — No tests

First ones landed with W3a: `mcp-server/tests/test_round_trip.py`, 12 cases,
stdlib only, no network —
`cd mcp-server && python3 -m unittest discover -s tests -t .`. They pin the
decompiler and the round-trip property, including the negative cases.

W3b added `tests/test_import.py` — 16 more, covering the importer and its
report, skipping cleanly when `python-hcl2` is absent. 28 in total.

Still needed, for a research artefact intended for release:

- Compiler: golden HCL for a fixed graph; the ten-resource smoke graph is
  already the informal version of this.
- Adapters: `canvas_to_nodes ∘ nodes_to_canvas` round-trip. W2 found a real
  loss here — a `tags` map came back as a JSON string — which is exactly what
  this test would have caught first.
- State machine: the repair loop with a stub Architect, asserting J is
  non-increasing and the budget is respected.
- Policies: `opa test` — Rego has a native test framework, and the seeded-fault
  corpus from G7 doubles as its fixtures.

---

## Suggested order

Against the proposal's timeline (months 6–7 "advanced features", months 8–9
"testing and evaluation"):

**~~First — small, unblocks other work. G1 and G5.~~ Done, 2026-09-06.** Both
closed; objective (d) is met, and the policy set grew from three rules to seven.
Next is the second group.

**~~Second — the contribution, in parallel. G8, G6, G3.~~ Done, 2026-09-07.**
G8 and G3 closed; G6's concurrent-edit half closed. The multi-agent reasoning
is now visible on the canvas, nesting compiles to real references, and a
concurrent edit is detected and merged rather than overwritten.

**~~Then — W1, the rest of G6 and G8.~~ Done, 2026-09-07.** The repair loop can
now tell an accident it should fix from a decision it should argue with, and
returns its patch as an offer rather than applying it. Both halves were one
backend change, as predicted; the breakpoint banner was already the approval
surface. G6 and G8 are closed.

Next is W2 (`docs/PLAN.md`) — `terraform plan` offline, and the plan JSON fed
to the Security Prover.

**Third — start now regardless of readiness.** G7. The seeded-fault benchmark
can be built against today's system and re-run as gaps close. The ethics
approval and the text baseline both have lead times measured in weeks.

**~~Then — W2, G4.~~ Done, 2026-09-07.** `terraform plan` runs offline, the
plan JSON reaches the Security Prover, and a plan-grounded policy catches what
the IR cannot. Cost stays `skipped` for want of a price catalogue.

**~~Then — W3a, half of G2.~~ Done, 2026-09-07.** The round-trip check runs on
every compile, with tests that break the registry on purpose to prove it can
fail. "Compilation demonstrably preserves intent" is now checked rather than
claimed.

**~~Fourth — W3b, the other half of G2.~~ Done, 2026-09-07.** A `.tf` file this
system did not write opens as a canvas, and everything that could not come
across is named rather than dropped.

**What is left is G7, and only G7.** The seeded-fault benchmark, the text-only
baseline, ethics approval and the human study. Every one of the system gaps is
now closed or deliberately parked (cost, proximity), so nothing else competes
for the time — and ethics approval is the one thing that cannot be compressed
by working harder.

**Throughout.** G9.
