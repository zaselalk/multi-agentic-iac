# Orchestrator

The agent runtime. One chat turn is one pass of the state machine in
`state_machine.py` — MACOG's orchestration loop, with the human's canvas as a
first-class writer to the blackboard.

```
visual-devops-builder  ──HTTP──>  orchestrator  ──MCP/stdio──>  mcp-server
   (React Flow canvas)             (this dir)                   (graph + compiler)
                                        │
                                        ├── opa        policies/*.rego
                                        └── terraform  validate
```

## Layout

| File | Role |
|---|---|
| `server.py` | FastAPI front door. |
| `state_machine.py` | The orchestrator: MACOG Eq. 14 states + Algorithm 1's repair loop. |
| `blackboard.py` | Typed, versioned artifact store; emits the evidence bundle. |
| `llm.py` | Azure AI Foundry client. The only place a model is configured. |
| `mcp_client.py` | JSON-RPC 2.0 MCP client over stdio; one long-lived server process. |
| `adapters.py` | React Flow `{id, type, position, data.details}` <-> canonical `{node_id, resource, desired_state, depends_on, view}`. |
| `projects.py` | Project storage — one JSON file per project, written atomically. |
| `conflict.py` | Concurrent-edit detection and the attribute-level merge. |
| `agents/` | Architect (LLM), Provider Harmonizer, Error-to-Edit router, Memory Curator. |
| `validators/` | The validator family v = (schema, policy, cost, deploy). |

`agents/__init__.py` carries the full MACOG role mapping, including which
roles are deterministic code rather than prompts. `validators/__init__.py`
carries the envelope contract.

## The turn

```
load ─> plan ─> harmonize ─> compile ─> review ─> prove ─> price ─> deploy ─┐
  │       │                     ▲                                           │
  │       └── breakpoint        └──────────── repair ◀── J > 0 ─────────────┤
  │           (destructive edit)                 (K = 2)                    │
  └── the human's canvas is written first                          J = 0 ─> done
```

- **load** — the canvas is authoritative at turn start. It is written to the
  blackboard as author `human`, so a hand edit made between turns is never
  lost and is attributable in the trail.
- **plan** — the Architect edits the graph through MCP tools. It is the only
  agent that calls a model, and it never writes HCL.
- **breakpoint** — a destructive edit (`delete_node`) stops the run and waits
  for the human. Send the turn again with `approved: true` to proceed.
- **harmonize** — is every node expressible in the registry? Catches a
  resource that would otherwise vanish silently from the compiled Terraform.
- **compile** — `mcp-server` lowers the graph to HCL deterministically. This is
  MACOG's Engineer, as a compiler rather than a constrained decoder.
- **review / prove / price / deploy** — the four validators.
- **repair** — failures go back to the Architect as structured counterexamples,
  each naming the node it belongs to, bounded at `VISOR_MAX_REPAIRS` attempts.
  A repair that does not reduce J stops the loop rather than thrashing.
- **reconcile** — did the human edit while this turn was running? A model turn
  takes seconds and they are not idle for them. A node both sides changed is
  held, not overwritten; where the two edits touch no attribute in common they
  are merged, and approval applies *that* rather than the agent's graph, which
  does not contain the human's edit.

Agent turns run in their own MCP session (`{project_id}#turn`). A `/graph` save
arriving mid-turn calls `set_graph` on the project session; sharing one would
let that land inside the graph the agent is holding, and the human's edit would
come back out as part of the agent's result.

## Validators

| Validator | Implementation | Status |
|---|---|---|
| `schema` | Reads the compiler's own validation report. | Working |
| `policy` | `opa eval` over `policies/*.rego`, against the typed IR. | Working |
| `deploy` | `terraform init -backend=false` + `terraform validate`. | Working |
| `cost` | — | **Not implemented** (interface only) |

A validator whose tool is missing returns `skipped`, never `pass`. `GET /health`
reports which can actually prove anything right now.

Policy runs against the IR rather than `terraform plan` JSON so that every
violation already carries a `node_id` and can be drawn on the canvas. See
`policies/README.md` for what that costs.

## Running

```shell
./venv/bin/uvicorn orchestrator.server:app --port 8080
```

Credentials come from the repo-root `.env`. The canvas never holds cloud keys.

| Variable | Default | Purpose |
|---|---|---|
| `VISOR_AGENT_MODEL` | `gpt-4.1-mini` | Foundry deployment name for the Architect. |
| `VISOR_MCP_SERVER` | `../mcp-server` | Path to the mcp-server checkout. |
| `VISOR_POLICY_DIR` | `../policies` | Where the Security Prover reads `.rego` from. |
| `VISOR_MAX_TOOL_ROUNDS` | `12` | Tool-call rounds before a turn is cut off. |
| `VISOR_MAX_REPAIRS` | `2` | Repair attempts K per turn. |
| `VISOR_DEPLOY_VALIDATION` | `0` | Run `terraform validate` on every chat turn. |
| `VISOR_CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed origins. |
| `VISOR_PROJECT_DIR` | `../.visor/projects` | Where project files are stored. |

`terraform validate` adds seconds to a turn, so it is off by default for chat
and always on for `POST /projects/{id}/verify`.

## Projects

A **project** is one named infrastructure graph with its own Terraform
settings. Staging and production are separate projects: separate graphs,
separate regions, separate default tags, separate chat history.

Projects are stored as one JSON file each under `VISOR_PROJECT_DIR`, written
atomically (temp file, then `os.replace`) so a crash mid-save cannot truncate
one. The MCP server's in-memory sessions are a compute cache keyed by project
id, rehydrated from the stored graph before every compile — so a restart of
either process loses nothing.

Per-project `settings` feed the compiler preamble and the policy input:

```json
{ "region": "eu-west-1",
  "default_tags": { "Owner": "platform", "Environment": "staging" },
  "allowed_regions": ["eu-west-1", "eu-central-1"] }
```

Changing them recompiles and re-proves, because they change both the emitted
HCL and what the residency policy is checked against.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Model, MCP path, project dir, tool list, validator availability. |
| `GET` | `/projects` | Summaries: name, resource count and kinds, region, timestamps. |
| `POST` | `/projects` | Create, optionally seeded with canvas nodes and edges. |
| `GET` | `/projects/{id}` | Canvas graph, canonical graph, IR, compiled HCL, validation, chat. |
| `PATCH` | `/projects/{id}` | Name, description, settings. Recompiles. |
| `DELETE` | `/projects/{id}` | Remove the project. |
| `POST` | `/projects/{id}/graph` | Persist a hand edit, recompile and prove it. **No model call, no repair.** |
| `POST` | `/projects/{id}/chat` | One full turn of the state machine, persisted on the way out. |
| `POST` | `/projects/{id}/verify` | Run every validator. **Observation only** — no model call, no edit. |
| `GET` | `/projects/{id}/drift` | Desired vs. last-compiled state. |
| `GET` | `/projects/{id}/export` | Portable JSON export. |
| `POST` | `/projects/import` | Create a project from an export. |
| `POST` | `/graph/compile` | Stateless compile, for tooling and tests. |

A chat response carries the multi-agent surface the canvas renders:
`validators`, `counterexamples` (each addressed to a node), `breakpoints`,
`conflicts`, `resolution` (the merged graph, when the edits compose),
`applied` (false when a conflict held the agent's graph back), `repairs`, and
`evidence` — the proof-carrying bundle for the turn.

## Design notes

- **The canvas is authoritative at the start of a turn.** Incoming nodes and
  edges are loaded with `set_graph` before the Architect runs.
- **The Architect cannot call `set_graph`.** It is on a denylist — the model
  reaching for it would wipe the graph rather than edit it.
- **The agent never writes HCL.** It edits the graph; `mcp-server`'s
  deterministic compiler emits Terraform. MACOG needs grammar-constrained
  decoding because its Engineer generates HCL text; here there is no decoding
  step to constrain, so a hallucinated provider field cannot be emitted at all.
- **`/verify` never repairs.** A human asking whether what they drew is
  compliant must get an answer about *their* graph, not about one an agent
  quietly fixed on the way past.
- **A hand edit is validated but never repaired.** `/graph` runs the full
  validator pass on every drag, drop and field edit (~110 ms; `terraform
  validate` stays off), and returns `counterexamples` addressed to nodes. It
  stops there. The agent rewriting what someone just drew is the failure mode
  in gap G6, so the position taken here is that the system tells the human and
  waits - escalating to an agent turn is their call, through `/chat`.
- **Skipped is not passed.** An unproven obligation is reported as unproven,
  in the turn's response and in the evidence bundle.
