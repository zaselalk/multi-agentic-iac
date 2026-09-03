# MACOG Orchestrator

The agent runtime that connects the three repos.

```
visual-devops-builder  ──HTTP──>  orchestrator  ──MCP/stdio──>  mcp-server
   (React Flow canvas)             (this dir)                   (graph + compiler)
                                        │
                                        └── evaluation/eval.py (Azure AI Foundry, RAG)
```

It turns a chat message into MCP tool calls against the infrastructure graph,
then hands back the edited graph in canvas shape plus deterministically
compiled Terraform.

## Why it exists

Before this, the three repos had never been connected. `eval.py` could turn
intent into HCL text but had no notion of a graph and no MCP client;
`mcp-server` exposed graph tools nobody called; the canvas called Azure
directly and generated HCL in the browser. This closes that loop, and makes the
research pipeline and the product share one model backend.

## Layout

| File | Role |
|---|---|
| `mcp_client.py` | JSON-RPC 2.0 MCP client over stdio; keeps one long-lived server process so graph sessions survive between turns. |
| `adapters.py` | React Flow `{id, type, position, data.details}` <-> canonical `{node_id, resource, desired_state, depends_on, view}`. Edges become `depends_on`; new nodes get a dependency-depth auto-layout. |
| `prompts.py` | The graph agent's system prompt - the tool-calling sibling of `eval.py`'s `build_multi_agent_prompt`. |
| `agent.py` | The tool-calling loop over Azure AI Foundry. |
| `projects.py` | Project storage - one JSON file per project, written atomically. |
| `server.py` | FastAPI front door. |

## Running

```shell
./venv/bin/uvicorn orchestrator.server:app --port 8080
```

Credentials come from the repo-root `.env` (loaded by `eval.py`), so the
canvas never holds cloud keys.

| Variable | Default | Purpose |
|---|---|---|
| `VISOR_MCP_SERVER` | `../mcp-server` | Path to the mcp-server checkout. |
| `VISOR_AGENT_MODEL` | `gpt-4.1-mini` | Foundry deployment name for the agent. |
| `VISOR_MAX_TOOL_ROUNDS` | `12` | Tool-call rounds before the turn is cut off. |
| `VISOR_CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed origins. |
| `VISOR_PROJECT_DIR` | `../.visor/projects` | Where project files are stored. |

## Projects

A **project** is one named infrastructure graph with its own Terraform
settings. Staging and production are separate projects: separate graphs,
separate regions, separate default tags, separate chat history.

Projects are stored as one JSON file each under `VISOR_PROJECT_DIR`, written
atomically (temp file, then `os.replace`) so a crash mid-save cannot truncate
one. The MCP server's in-memory sessions are a compute cache keyed by project
id, rehydrated from the stored graph before every compile - so a restart of
either process loses nothing.

Per-project `settings` feed the compiler preamble, overriding the schema's
defaults:

```json
{ "region": "eu-west-1",
  "default_tags": { "Owner": "platform", "Environment": "staging" } }
```

Changing them recompiles, because they change the emitted HCL.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Model, MCP path, project dir, tool list. |
| `GET` | `/projects` | Summaries: name, resource count and kinds, region, timestamps. |
| `POST` | `/projects` | Create, optionally seeded with canvas nodes and edges. |
| `GET` | `/projects/{id}` | Canvas graph, canonical graph, IR, compiled HCL, validation, chat history. |
| `PATCH` | `/projects/{id}` | Name, description, settings. Recompiles. |
| `DELETE` | `/projects/{id}` | Remove the project. |
| `POST` | `/projects/{id}/graph` | Persist a hand edit and recompile. **No model call.** |
| `POST` | `/projects/{id}/chat` | One agent turn against this project, persisted on the way out. |
| `GET` | `/projects/{id}/export` | Portable JSON export. |
| `POST` | `/projects/import` | Create a project from an export. |
| `GET` | `/projects/{id}/drift` | Desired vs. last-compiled state. |
| `POST` | `/graph/compile` | Stateless compile, for tooling and tests. |

## Design notes

- **The canvas is authoritative at the start of a turn.** Every `/agent/chat`
  call loads the incoming nodes and edges with `set_graph` before the agent
  runs, so hand edits made between turns are never lost.
- **The agent cannot call `set_graph`.** It is on a denylist - the model
  reaching for it would wipe the graph rather than edit it.
- **Every response carries all three stages.** `graph` is the canonical node
  model read back from the MCP server (so it carries the server-assigned
  `tf_name` and the dependency ordering the compiler used), `terraformIr` is
  the compiler's typed intermediate representation, and `terraform` is the
  rendered HCL. The canvas shows all three, which makes the deterministic
  compile inspectable rather than a black box.
- **The agent never writes HCL.** It edits the graph; `mcp-server`'s
  deterministic compiler emits Terraform, which is where the compliance
  constraints in `eval.py`'s multi-agent prompt are actually enforced.
- **RAG is opt-in** (`useRag: true`) and currently fails: the checked-in
  `retriever/aws-index` holds 1536-dimension vectors while the configured
  embedding deployment is 3072-dimension. The failure is reported as a warning
  rather than breaking the turn.
