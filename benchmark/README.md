# Seeded-fault benchmark

The automatic half of the evaluation (G7, part 1). No participants, no network
beyond the Terraform provider, and — by default — no model call, so a run is
free and reproducible.

```shell
python -m benchmark.run                     # the full configuration
python -m benchmark.run --ablate            # every row of the ablation table
python -m benchmark.run --json results.json # machine-readable, to diff a re-run
python -m benchmark.run --model             # opt in to real repair rounds
```

`RESULTS.md` holds a committed run, so a later one can be diffed against it.

## Why not IaC-Eval

MACOG is measured on IaC-Eval: one prompt, one file, did it pass. This system
cannot be measured that way, and the reason is the contribution rather than an
excuse. A human edits the artefact mid-run, so "solved on the first try" is not
a quantity the interaction admits. And the claim being made is not that the
generated Terraform is good — a deterministic compiler makes that mostly a
property of the registry — but that a violation is **found**, **addressed to
the right place on a diagram**, and **resolved without reversing what somebody
asked for**.

So: take graphs that pass everything, inject exactly one known fault, and
measure what happens. Every fault declares which rule should fire and on which
node, so scoring is mechanical — no judgement, no model, no reading of prose.

## What is measured

| | | Why it is here |
|---|---|---|
| **Detection** | did a validator fire | The floor. See the caveat below. |
| **Attribution** | did the finding name the **right node** | **The metric that is ours.** Nothing in the literature reports it, because nothing else addresses a failure to a visual element. It is measurable here only because every counterexample carries a `node_id`. |
| **Fix offered** | was a concrete patch put on the table | Deterministic, computed from the violated rule with no model call. |
| **Repaired** | was it silently fixed by the repair loop | Needs `--model`. Reads as 0 without it, and the report says so rather than implying it was measured. |
| **Nodes touched** | nodes the system changed | The presence rule says this must be **zero** for an injected fault. This is the measurement of that claim rather than an assertion of it. |
| **Model rounds** | how often the loop reached for a model | Most of this architecture is deterministic; this is how much. |
| **Collateral** | alarms the fault caused beyond its own | Subtracted against the clean baseline, so it counts what the *fault* set off. |

### Read the detection column with the caveat

Every fault in this corpus is one the system has a validator for, so a high
detection rate is the expected result and not a finding. A benchmark of a
system against its own feature list cannot be surprised by it. The informative
columns are **attribution**, the **ablation** table, and **collateral**.
Detection becomes interesting only when the corpus grows faults nobody wrote a
rule for.

### Why `remediation` is not MACOG's `repair rate`

MACOG repairs every counterexample it can reach. This system does not, on
purpose. By the presence rule in `orchestrator/intent.py`, a value that is *in*
the graph is something somebody asked for — so a **policy** objecting to one is
held and its fix offered rather than applied.

Scoring "was it silently fixed" would therefore mark the system down for its
central design decision. The benchmark reports `Fix offered` and `Repaired`
separately, and `Nodes touched` beside them, because *offered and changed
nothing* is the claim under test.

That protection applies only to policy and cost violations. A schema error is
not a disagreement about a rule — `bucket = ""` is not a bucket name somebody
prefers, it is a graph that cannot compile — so those are still repaired. That
distinction was **found by this benchmark**, not designed in: the first run
showed `missing_required` reaching zero model rounds and offering no fix,
because the intent rule was holding a value that could not be honoured by
anybody. See `orchestrator/agents/repair.py`, `ARGUABLE`.

## The corpus

Five graphs, chosen to spread across the registry rather than to be realistic.
Between them they use **all ten registered resource types**, both reference
kinds (attribute and `@block:`), companion emission, virtual attributes and the
variable fallback — so a fault injected into any of them lands in machinery
that is actually exercised.

`run.py` **refuses to score a corpus that is not clean first**. A base graph
that already violates something makes every number measured against it the sum
of two effects, so that check is the precondition and not a nicety.

## The faults

| Fault | Injected as | Should be caught by |
|---|---|---|
| `public_acl` | `acl: public-read` on a bucket | `s3_public_acl` |
| `unencrypted_db` | `storage_encrypted: false` | `rds_storage_encrypted` |
| `tag_override` | a node tag shadowing a project default | `plan_default_tags_resolved` — **plan only** |
| `dependency_cycle` | a `depends_on` back-edge | `dag_cycle_detection` |
| `residency_breach` | region outside `allowed_regions` | `region_not_allowed` |
| `unknown_resource` | a resource key not in the registry | `registry_coverage` |
| `missing_required` | a required attribute emptied | `schema_validation` |
| `invalid_value` | a value failing the registry's own pattern | `schema_validation` |

Three details in the scoring that matter:

- **`node` can be a set.** A dependency cycle belongs to every node in it and
  the compiler names them all, so attribution is a membership test there.
  Everywhere else it is equality, or a finding naming two nodes would pass by
  accident.
- **`node` can be `None`.** A residency breach is a property of the project and
  belongs to no resource. Attribution is *not applicable*; scoring it as a
  failure would understate the system and scoring it as a success would
  overstate it, so it is excluded from the denominator and reported as `n/a`.
- **`needs_plan`.** `tag_override` is invisible to the IR and appears only in a
  real `terraform plan`. It is the case that justifies running the provider at
  all, and it is the one the `- devops` ablation removes.

`broken_invariant` — a registry entry losing its `companion_resources` — is
deliberately **not** here. It is a fault in the compiler's own configuration
rather than in a graph, so injecting it means mutating a schema the MCP server
loads in another process. It is covered instead by
`mcp-server/tests/test_round_trip.py::BrokenRegistryTest`. Listing it here and
skipping it would be worse than saying where it actually lives.

## Ablations

Four rows, in the form of MACOG's Table 4 — **in form, not in value**, because
the task is different and claiming otherwise is the easiest way to lose a
reviewer.

| Row | How | What it removes |
|---|---|---|
| `- prover` | the policy validator reports `skipped` | OPA over the IR and the plan |
| `- devops` | `deploy_validation=False` | `terraform validate` and `plan` |
| `- harmonizer` | a harmonizer returning nothing | the registry-coverage check |
| `- repair` | `repair=False` | the counterexample-guided loop |

Each is swapped in at the object level rather than by editing configuration, so
an ablation run cannot accidentally differ from the full run in any other way.

## Re-run it as things change

The numbers should move as the system does, and **that trend is itself a
result**. `--json` writes every case, so two runs can be diffed rather than
compared by eye.
