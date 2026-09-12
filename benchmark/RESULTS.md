# Results

A committed run, so a later one can be diffed against it rather than compared
by eye. Reproduce with:

```shell
python -m benchmark.run --ablate --json benchmark/results.json
```

Recorded **2026-09-07**, on the repository state of that day. The Architect is
stubbed, so this run is deterministic and cost nothing; `benchmark/results.json`
holds every case. How to read the columns — and why detection at 100% is the
*expected* result rather than a finding — is in `README.md`.

---

## Detection and attribution, full configuration

Architect: stubbed (deterministic; no model called)

`Fix offered` is a deterministic patch put on the table, computed from the violated rule with no model call.
`Repaired` is a silent fix by the repair loop, which needs `--model` to measure and reads as 0 here.

| Fault | Validator | Cases | Detection | Attribution | Fix offered | Repaired | Nodes touched | Model rounds |
|---|---|---|---|---|---|---|---|---|
| `public_acl` | policy | 2 | 100% (2/2) | 100% (2/2) | 100% (2/2) | 0% (0/2) | 0 | 0 |
| `unencrypted_db` | policy | 2 | 100% (2/2) | 100% (2/2) | 100% (2/2) | 0% (0/2) | 0 | 0 |
| `tag_override` | policy (plan-grounded) | 5 | 100% (5/5) | 100% (5/5) | 0% (0/5) | 0% (0/5) | 0 | 0 |
| `dependency_cycle` | schema | 4 | 100% (4/4) | 100% (4/4) | 0% (0/4) | 0% (0/4) | 0 | 4 |
| `residency_breach` | policy | 5 | 100% (5/5) | n/a | 0% (0/5) | 0% (0/5) | 0 | 0 |
| `unknown_resource` | harmonizer | 5 | 100% (5/5) | 100% (5/5) | 0% (0/5) | 0% (0/5) | 0 | 5 |
| `missing_required` | schema | 2 | 100% (2/2) | 100% (2/2) | 0% (0/2) | 0% (0/2) | 0 | 2 |
| `invalid_value` | schema | 2 | 100% (2/2) | 100% (2/2) | 0% (0/2) | 0% (0/2) | 0 | 2 |
| **all** | | **27** | **100% (27/27)** | **100% (22/22)** | **15% (4/27)** | **0% (0/27)** | **0** | **13** |

**Nodes touched: 0**, of which 0 beyond the faulted node. Every fault here is *in* the graph, so by the presence rule in `orchestrator/intent.py` a **policy** objecting to one is held and offered rather than reversed - those cases should touch nothing at all. Schema errors are still repaired, and those are what the count is.

**On the detection column.** Every fault here is one this system has a validator for, so a high detection rate is the expected result rather than a finding - a benchmark of a system against its own feature list cannot be surprised. The columns that carry information are **attribution** (a validator firing is not the same as it pointing at the right place), the **ablation** table below (which component is actually load-bearing for which fault), and **collateral** (what else the fault set off). Detection becomes informative only when the corpus grows faults nobody designed a rule for.

Collateral findings (alarms the fault caused beyond its own): 5 of 27 cases.
  unknown_resource / three_tier: resource_registry_match
  unknown_resource / static_site: resource_registry_match
  unknown_resource / serverless_api: resource_registry_match
  unknown_resource / queue_worker: resource_registry_match
  unknown_resource / data_store: resource_registry_match


## Ablation — detection rate per fault class

| Fault | full | - prover | - devops | - harmonizer | - repair |
|---|---|---|---|---|---|
| `public_acl` | 100% (2/2) | 0% (0/2) | 100% (2/2) | 100% (2/2) | 100% (2/2) |
| `unencrypted_db` | 100% (2/2) | 0% (0/2) | 100% (2/2) | 100% (2/2) | 100% (2/2) |
| `tag_override` | 100% (5/5) | 0% (0/5) | 0% (0/5) | 100% (5/5) | 100% (5/5) |
| `dependency_cycle` | 100% (4/4) | 100% (4/4) | 100% (4/4) | 100% (4/4) | 100% (4/4) |
| `residency_breach` | 100% (5/5) | 0% (0/5) | 100% (5/5) | 100% (5/5) | 100% (5/5) |
| `unknown_resource` | 100% (5/5) | 100% (5/5) | 100% (5/5) | 0% (0/5) | 100% (5/5) |
| `missing_required` | 100% (2/2) | 100% (2/2) | 100% (2/2) | 100% (2/2) | 100% (2/2) |
| `invalid_value` | 100% (2/2) | 100% (2/2) | 100% (2/2) | 100% (2/2) | 100% (2/2) |


## Ablation — fix-offered rate

| Fault | full | - prover | - devops | - harmonizer | - repair |
|---|---|---|---|---|---|
| `public_acl` | 100% (2/2) | 0% (0/2) | 100% (2/2) | 100% (2/2) | 0% (0/2) |
| `unencrypted_db` | 100% (2/2) | 0% (0/2) | 100% (2/2) | 100% (2/2) | 0% (0/2) |
| `tag_override` | 0% (0/5) | 0% (0/5) | 0% (0/5) | 0% (0/5) | 0% (0/5) |
| `dependency_cycle` | 0% (0/4) | 0% (0/4) | 0% (0/4) | 0% (0/4) | 0% (0/4) |
| `residency_breach` | 0% (0/5) | 0% (0/5) | 0% (0/5) | 0% (0/5) | 0% (0/5) |
| `unknown_resource` | 0% (0/5) | 0% (0/5) | 0% (0/5) | 0% (0/5) | 0% (0/5) |
| `missing_required` | 0% (0/2) | 0% (0/2) | 0% (0/2) | 0% (0/2) | 0% (0/2) |
| `invalid_value` | 0% (0/2) | 0% (0/2) | 0% (0/2) | 0% (0/2) | 0% (0/2) |

Wrote benchmark/results.json

---

## What this run says

**Attribution is the number that matters: 100% of 22 attributable cases.** A
validator firing is not the same as it pointing at the right place, and a
finding the canvas cannot address to a node is one it cannot draw. The five
`residency_breach` cases are excluded from that denominator because the fault
belongs to the project rather than to any resource — counting them either way
would misreport the system.

**The ablation table is where the components earn their place.** Each column
removes one and shows exactly which faults go undetected:

| Removing | Costs | Which is the argument for |
|---|---|---|
| the prover | 14 of 27 cases | OPA over the IR *and* the plan |
| the DevOps validator | 5 of 27 — **all of them `tag_override`** | running a real `terraform plan` at all |
| the harmonizer | 5 of 27 | checking the graph is expressible before compiling it |
| the repair loop | 0 detections, but **every offered fix** | the loop is what turns a finding into a decision |

The `- devops` row is the one worth reading twice. It removes exactly one fault
class and nothing else, because `tag_override` is the only fault in this corpus
that a plan can see and the IR cannot — the IR holds
`tags = merge(local.default_tags, …)` as text, which still satisfies every IR
rule. That single row is the whole justification for W2.

**Nodes touched: 0.** Not one of the 27 injected faults was silently rewritten.
Every fault is *in* the graph, so by the presence rule a policy objecting to it
is held and its fix offered rather than applied. This is the measurement of
that claim, not an assertion of it.

**Collateral: 5 of 27**, all the same case — an unmapped resource type is
reported twice, by the harmonizer (`registry_coverage`) and by the compiler
(`resource_registry_match`). Both are true and they say different things, so
this is duplication in the *presentation* rather than a false alarm.

## With a real Architect

`--model` swaps the stub for the real one. It costs money and is not
reproducible, so it is not the committed run — but the repair columns read as
"not measured" without it, and leaving a metric unmeasurable is worse than
paying for a sample. One class, `gpt-4.1-mini`, same day:

| Fault | Cases | Detection | Attribution | Repaired | Nodes touched | Beyond the faulted node |
|---|---|---|---|---|---|---|
| `dependency_cycle` | 4 | 100% (4/4) | 100% (4/4) | 25% (1/4) | 1 | **0** |

One cycle of four cleared in a single round, and the repair touched exactly the
node that was broken and nothing else. That is MACOG's "minimal edits, not
speculative rewrites" as a number rather than a claim — on a sample of one, which
is stated rather than rounded up.

## Two defects this benchmark found on its first run

Neither was reachable by reading the code, which is the argument for having
built it:

1. **`region_not_allowed` was spending a model round in every single run and
   never clearing it.** The region is a *project setting*; no edit to any node
   can change one. It is now in `NEEDS_HUMAN`.
2. **The presence rule was holding schema errors as intent.** `bucket = ""` is
   not a bucket name somebody prefers — it is a graph that cannot compile, and
   there is no version of honouring that intent. The rule now applies only to
   policy and cost violations (`ARGUABLE` in
   `orchestrator/agents/repair.py`), so a non-compiling graph is repaired again.

A third was in the harness rather than the system, and is worth recording for
the same reason: **detection was being scored on the final counterexample list**,
so a fault the repair loop successfully cleared read as one that was never
found. It surfaced the moment a real model was put behind it, and it is why
`Orchestrator.run` now returns `initial_counterexamples` separately.
