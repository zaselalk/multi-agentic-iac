# Finishing plan

Nine gap IDs is too many things to hold at once. This regroups what is left
into **four workstreams**, mapped onto the two-person split the proposal
already makes — slide 9 "Orchestration & Logic (The Brain)", slide 10
"Semantic Interface & Sync (The Eyes & Hands)", and "System Evaluation
(Joint)".

`RESEARCH-GAPS.md` stays the register of *what* is missing and why. This is
*how it gets finished, in what order, by whom*.

---

## Where things stand

Closed: **G1**, **G3**, **G5**, **G8**, and two of G6's three conflict classes.

What that adds up to: a human and an agent co-edit one graph; nesting compiles
to real Terraform references; every hand edit is validated in ~110 ms and
never silently repaired; violations are drawn on the node that caused them; a
concurrent edit is held and merged rather than overwritten. That is objectives
(a), (c) and (d) substantially met, and (b) partly.

Remaining, as four workstreams:

| | Workstream | Gaps | Owner | Blocks |
|---|---|---|---|---|
| **W1** | Decide, don't overwrite | G6 (rest), G8 (ghosting) | Brain + small canvas | The research question |
| **W2** | Prove it against the provider | G4 | Brain | Objective (b), (d) |
| **W3** | Make bi-directional true | G2 | Eyes & Hands | **The title** |
| **W4** | Measure it | G7 | Joint | Publishability |
| — | Tests | G9 | Both, continuous | Reproducibility |
| — | Proximity | G3 (rest) | Eyes & Hands | Optional |

---

## W1 — Decide, don't overwrite

**Why first.** It is small, it finishes the story the other three assume, and
it fixes the one place where the system currently does something dishonest.

Ask for `storage_encrypted: false` today and the Architect builds it, the
Security Prover objects, the repair loop sets it back to `true`, and the reply
— written before the repair ran — still says encryption is disabled. Nothing
wrong happened at any step and the outcome is still wrong: the human asked for
something, the system did the opposite, and never said so.

**The change is one thing serving two gaps: the repair loop returns its patch
as a diff instead of applying it.**

1. **Mark intent.** The Architect knows which attributes it set from the user's
   request. Tag those on the blackboard as `intended`.
2. **Route on intent.** In `agents/repair.py`, a counterexample landing on an
   intended attribute goes to a breakpoint, not a repair — *"you asked for X,
   policy Y forbids it. Override, change the policy, or let me fix it?"* A
   counterexample on an attribute nobody asked about is an omission, and the
   loop still fixes it silently. That distinction is the deliverable.
3. **Return the patch.** `state_machine.run` returns the repaired graph as a
   proposal alongside the current one, rather than having already written it.
4. **Compose the reply last.** After the loop settles, never before.
5. **Ghost it on the canvas** (G8's remainder). The proposed graph renders over
   the current one — added nodes outlined, changed attributes shown as
   before → after. The breakpoint banner already exists and is the approval
   surface; this gives it something to show.

**Done when:** asking for something non-compliant produces a breakpoint that
names the rule and offers the fix, the human can take it or refuse it, and the
reply text matches what is actually stored in every case.

**Files:** `orchestrator/agents/repair.py`, `agents/architect.py`,
`state_machine.py`, `server.py`; `components/BreakpointBanner.tsx`,
`components/InfraCanvas.tsx`.

---

## W2 — Prove it against the provider

**Why it moved up.** This was scoped as needing LocalStack, which this
container cannot run — no conda, so the install line never worked, and no
Docker to run the container in. It turns out not to be needed:
**`terraform plan` runs completely offline** with dummy credentials and the
provider's skip flags. Verified: `Plan: 6 to add, 0 to change, 0 to destroy`,
no network, no account.

That makes the most valuable validator in MACOG's ablation — removing the
sandbox costs it 74.02 → 56.93, the largest drop of the eight — reachable in
days rather than weeks.

1. **Plan mode in the compiler preamble.** A settings flag that emits the skip
   flags, so plan-mode HCL is generated the same deterministic way as the rest.
2. **Extend `validators/deploy.py`** past `validate` to
   `plan -out` + `show -json`. Map `resource_changes[].address` back to nodes
   with the address→`tf_name` lookup already there.
3. **Feed the plan JSON to the prover** as a second input beside the IR. This
   closes the limitation `policies/README.md` names: a plan has post-expansion
   values — resolved `tags_all`, `after_unknown` marking what is only known at
   apply — that the IR cannot have. Policies needing those become writable.
4. **Cost** (`validators/cost.py`). Lowest value of the four, and the one place
   where inventing numbers would be worse than reporting none. A pinned price
   book keyed by `terraform_type` × region × SKU, stamped with its catalogue
   date. Cut this first if time runs short — it stays honest as `skipped`.

**Done when:** `deploy` reports `pass`/`fail` from a real plan with findings
addressed to nodes, and at least one policy runs on plan-only values.

**Files:** `mcp-server/schema.json` (preamble), `orchestrator/validators/deploy.py`,
`validators/policy.py`, `policies/`.

---

## W3 — Make bi-directional true

**Why it cannot be cut.** The title is *bi-directional synchronization*. What
exists is canvas ⇄ graph ⇄ HCL, where the last arrow points one way. A
reviewer will go straight to this.

**Split it in two, and do the small half first.** The insight is the same one
that closed G1: parsing HCL *this compiler emitted* is a bounded problem, while
parsing arbitrary Terraform is not.

**W3a — the round-trip check (small, buys the claim).**
`parse_body` already exists and parses emitted bodies. A decompiler for our own
output is: split resource blocks, `parse_body` each, invert the registry. The
inversion surface is genuinely small — **10 resources, 3 references, 3
companions** — and every mapping already exists in `attribute_map`,
`references` and `terraform_type`.

Then add MACOG's Eq. 11 to the `compile` state:
`equiv(P, decompile(compile(P)))`, ignoring compiler-generated companions.
A mismatch becomes a counterexample like any other.

This is the defensible version of the claim: *compilation demonstrably
preserves intent, checked on every turn.* Target it first and treat it as the
deliverable.

**W3b — import arbitrary Terraform (large, do if time allows).**
`python-hcl2`, a `POST /projects/import/terraform` endpoint, and auto-layout
for nodes with no `view`. Expect it to surface registry gaps immediately —
which is a feature, since it makes compiler coverage measurable for the first
time. If the term runs out, W3a alone still supports the title; W3b is what
makes the system adoptable by someone with existing infrastructure.

**Done when (a):** the round-trip check runs on every compile and fails loudly
on a deliberately broken registry entry.
**Done when (b):** a real `.tf` file opens as a canvas graph.

**Files:** new `mcp-server/decompiler.py`, `compiler.py`, `main.py`,
`orchestrator/state_machine.py`, `server.py`.

---

## W4 — Measure it

**Start this now, in parallel, not after the system is finished.** It is the
only workstream with dependencies you cannot compress by working harder:
ethics approval has a lead time measured in weeks, and the baseline it compares
against does not exist yet.

**W4a — seeded-fault benchmark. Buildable today; no participants.**

Take a corpus of valid graphs, inject one known fault into each — public ACL,
unencrypted database, dependency cycle, region outside the allowed set,
out-of-registry resource — and measure per fault class:

- **Detection rate** — did a validator fire.
- **Attribution accuracy** — did the counterexample name the right `node_id`.
  Nothing in the literature reports this, because nothing else addresses
  failures to a visual element. This is the metric that is *yours*.
- **Repair rate** within K attempts.
- **Repair minimality** — nodes changed beyond the faulted one. MACOG's claim
  of "minimal edits, not speculative rewrites", made measurable.

Ablate as MACOG does — prover off, harmonizer off, repair budget 0 — for a
table comparable in form to their Table 4. Re-run it as each workstream lands;
the numbers should improve, and that trend is itself a result.

**W4b — the text-only baseline. Build it early; nothing compares without it.**

Same model, same policies, same orchestrator, chat only, no canvas. A small
CLI — the API already supports it. Without this there is no "compared to
text-based workflows" in any claim you make.

**W4c — ethics approval. Submit before the system is finished.**

Within-subjects, order counterbalanced, n ≥ 12, tasks with objectively
checkable end states.

**W4d — the human study.** Operationalise the proposal's two metrics:

- **State Reconciliation Accuracy** — show participants their final diagram and
  the compiled HCL, count discrepancies they identify. Zero drift is the claim.
- **Correction Speed** — wall-clock from a violation being introduced to it
  being resolved, visual vs. the W4b baseline.

Plus: task completion rate, agent suggestions accepted vs. rejected (does the
visual channel make agent reasoning legible?), and breakpoint outcomes.

**Files:** new `evaluation/` — a different thing entirely from the IaC-Eval
harness that was removed, and worth saying so in the write-up.

---

## Sequencing

```
now ──────────────────────────────────────────────────────────────────>

Brain        [ W1 decide/ghost ][ W2 plan grounding ][ W2 cost (cut if late) ]
Eyes&Hands   [ W1 canvas ][ W3a round-trip ][ W3b import (cut if late) ]
Joint        [ W4c ethics ─── submitted, then waiting ]
             [ W4a benchmark ─ built early, re-run as things land ]
                   [ W4b baseline ][ W4d study ─ runs when approval lands ]
Both         [ W9 tests ─────────────────────────────────────────────── ]
```

Three rules keep this from going wrong:

1. **W4c and W4a start immediately**, regardless of how finished the system
   feels. Ethics waiting is dead time you cannot buy back; the benchmark
   improves as the system does, so building it early costs nothing.
2. **W3a before W3b.** The round-trip check buys the title claim at a fraction
   of the cost of a general importer.
3. **Cut from the end, never the middle.** If the term runs short, drop W2's
   cost book and W3b. Do not drop W1 (it is the research question), W3a (it is
   the title) or any of W4 (it is the result).

## Tests, throughout

Not a phase — each workstream lands with its own:

| Workstream | Test that comes with it |
|---|---|
| W1 | Repair loop with a stub Architect: J non-increasing, budget respected, an intended attribute never silently changed. |
| W2 | Golden plan JSON for a fixed graph. |
| W3a | The round-trip check *is* a test — run it over the corpus in W4a. |
| W4a | The seeded-fault corpus doubles as fixtures for `opa test`. |

## The one thing not on this list

Proximity (G3's remainder). The schema records it as suggestion-only and not
implemented, which is a defensible position to write up as-is. Build it only if
W1–W4 land early — and if you do, keep it non-binding, because an ambiguous
signal reaching the compiled artefact would undo the care that went into the
nesting gate.
