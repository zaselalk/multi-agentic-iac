# Visor — bi-directional synchronisation of visual infrastructure models and Terraform

Research implementation for *A Universal Schema for Bi-Directional
Synchronization of Visual Infrastructure Models and Declarative IaC through
Agentic AI Orchestration* (Group 10 — TG/2021/1066, TG/2021/1043).

A human and a team of agents co-design cloud infrastructure on a shared visual
canvas. The canvas, the agents and the compiler all read and write **one**
graph, so the diagram and the Terraform cannot drift apart — they are two
renderings of the same state.

### What "universal" claims, and what it does not

The title's *universal* is claimed over the **synchronisation mechanism**, not
over the resource vocabulary. Stated as three separate things, because they
are at three different stages:

| | Claim | Status |
|---|---|---|
| **Mechanism** | The way visual state and declarative state are kept in correspondence is independent of provider and of IaC target | **Claimed.** `view` / `desired_state` separation with `view` never compiled; spatial nesting lowered to `depends_on` but gated by the registry so it cannot invent a relationship Terraform has no way to express; round-trip `equiv(P₁, P*)` checked on every compile; intent inferred from presence. None of it names AWS or Terraform. |
| **Provider** | The same schema admits providers other than AWS without redesign | **Designed for, not yet demonstrated.** `node_model.provider` is a free key and the registry is data, but it holds 11 AWS types and nothing else, and four sites still emit `aws` literally. See `docs/DEV-PLAN.md` §2. |
| **IaC target** | The same schema compiles to something other than Terraform | **Not claimed.** `desired_state` is Terraform's attribute vocabulary — `schema.json` says so itself — and registry entries carry `terraform_type` and raw HCL. Pulumi or Bicep would need an IR layer beneath this one. Out of scope, deliberately. |

The middle row has a one-day experiment attached, with a binary answer: can a
provider be added without touching Python? Until that is run, "universal
across providers" is a design property and is described as one.

```
visual-devops-builder  ──HTTP──>  multi-agentic-iac/orchestrator  ──MCP/stdio──>  mcp-server
   (React Flow canvas)              (agents, state machine)                (graph + Terraform compiler)
                                            │
                                            ├── opa        policies/*.rego
                                            └── terraform  validate
```

`mcp-server/schema.json` is the contract shared verbatim by all three repos.

## Where this sits relative to MACOG

The system is MACOG (Khan et al. 2025, arXiv:2510.03902) restructured around a
human who is present for the whole design session rather than only at the end.

| | MACOG | Here |
|---|---|---|
| Input | Natural-language text | Visual graph + spatial metadata, or text |
| Core representation | Typed I-IR, agent-facing | One schema shared by human, agent and compiler |
| Synthesis | LLM + grammar-constrained decoding | Deterministic compiler from the graph |
| Feedback | Log files and JSON traces | Counterexamples addressed to canvas nodes |
| Protocol | Internal shared blackboard | **MCP.** The blackboard is replaced, not extended — see below |
| HITL | Named as future work | Agentic breakpoints as ordinary control flow |

The synthesis row is the one that matters most. MACOG needs constrained
decoding because its Engineer generates HCL text; here the graph is lowered to
HCL by a deterministic compiler, so there is no decoding step to constrain and
a hallucinated provider field cannot be emitted at all.

The protocol row is the one most easily misread. MACOG's blackboard is how its
agents *communicate*: an agent learns what another did by reading the store.
Here no agent reads one. Coordination runs through the schema instance held by
the MCP server — the controller pushes the canvas with `set_graph` and re-reads
an agent's edits with `get_graph` — and agents are handed typed arguments and
return typed results. What survives from MACOG is its evidence discipline, not
its coordination substrate: `orchestrator/ledger.py` records order, authorship
and timing, and emits the S4.9 bundle. It is written to on every turn and read
by nothing. A schema instance says what *is*; the ledger says who decided it,
and when.

## Repository

| Path | What |
|---|---|
| `orchestrator/` | The agent runtime — state machine, evidence ledger, agents, validators. |
| `policies/` | Rego rules the Security Prover evaluates every turn. |
| `docs/RESEARCH-GAPS.md` | **What is still missing, and why.** The register — plus `D1`–`D4`, the four mechanisms the proposal named that were built differently, and why each is a decision rather than a shortfall. |
| `docs/PLAN.md` | **How the rest got finished.** Four workstreams, sequenced. W1–W3 done. |
| `docs/FUTURE-WORK.md` | **What is left, and why.** What the research still needs, what was deliberately left as an interface, and the limits of what was built. |
| `benchmark/` | **The seeded-fault benchmark.** 27 cases, four ablation rows, a committed run in `RESULTS.md`. |
| `docs/MANUAL-TEST.md` | **How to try it by hand.** Four levels, cheapest first; the first two need no model. |
| `.visor/` | Project storage (gitignored). |

## Setup

```shell
python3 -m venv venv
./venv/bin/pip install -r orchestrator/requirements.txt
cp .env.example .env      # fill in the two Azure AI Foundry values
```

Two optional binaries on `PATH` — each validator reports `skipped` rather than
passing when its tool is missing:

```shell
# terraform >= 1.5    deploy validator
# opa >= 1.0          security prover (policies use Rego v1 syntax)
curl -L -o opa https://openpolicyagent.org/downloads/latest/opa_linux_amd64_static
chmod +x opa && mv opa ~/.local/bin/
```

## Running

```shell
# 1. the orchestrator (spawns mcp-server itself over stdio)
./venv/bin/uvicorn orchestrator.server:app --port 8080

# 2. the canvas
cd ../visual-devops-builder && npm run dev
```

`GET /health` reports which validators can actually prove anything:

```json
{ "validators": {
    "schema": {"available": true},
    "policy": {"available": true, "policies": ["data_residency.rego", "encryption_at_rest.rego", "no_public_s3.rego"]},
    "cost":   {"available": false, "reason": "not implemented: no price book configured."},
    "deploy": {"available": true} } }
```

Ask a project to prove itself, with no model call:

```shell
curl -sX POST localhost:8080/projects/<id>/verify
```

## Status

Working end to end: the canvas, the graph, the deterministic compiler, the
Architect's tool-calling loop, the counterexample-guided repair loop, agentic
breakpoints on destructive edits, and three of the four validators.

Closed so far: G1, G2, G3, G4, G5, G6, G8 — the IR describes the emitted HCL,
nesting compiles to real references, every hand edit is validated as it is made
and never silently repaired, a rule that contradicts what someone asked for
offers its fix instead of taking it, the graph is proved against a real
`terraform plan` offline, the generated Terraform is read back and checked
against the graph on every compile, somebody else's `.tf` file opens as a
canvas, and findings are drawn on the nodes that caused them.

Measured: `python -m benchmark.run --ablate` injects one known fault into each
of five clean graphs and scores detection, **attribution to the right node**,
and whether anything was silently rewritten. Committed run in
[benchmark/RESULTS.md](benchmark/RESULTS.md).

Not built: cost estimation, the Memory Curator, real-state drift, and the
half of the evaluation that needs people — **the last of which is the only one
that blocks the result.** Each is written up in
[docs/RESEARCH-GAPS.md](docs/RESEARCH-GAPS.md); what remains, why, and in what
order is [docs/FUTURE-WORK.md](docs/FUTURE-WORK.md). The workstream plan that
got the rest done is [docs/PLAN.md](docs/PLAN.md).

## History

This repository began as a fork of **IaC-Eval** (Kon et al., NeurIPS 2024) and
carried its benchmark harness, RAG retriever and per-task Rego ground truth.
All of it has been removed: the baselines it measured (few-shot, CoT,
multi-turn, RAG) compare single-shot text-to-HCL systems, and this system is
neither single-shot nor text-first — a human edits the artefact mid-run, so
task-success-at-first-try is not a measurement it admits. What replaces it is
open, and is gap **G7**.

Reference: `git log` before the MACOG restructure, and
<https://huggingface.co/datasets/autoiac-project/iac-eval>.
