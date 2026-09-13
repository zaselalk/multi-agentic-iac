"""
HTTP front door for the multi-agent orchestrator.

    uvicorn orchestrator.server:app --port 8080

The canvas (visual-devops-builder) talks to this; this talks MCP to
mcp-server. One chat turn is one pass of the state machine in
state_machine.py, which is MACOG's orchestration loop with the human's canvas
as a first-class writer.

Work is organised into projects: one named graph with its own Terraform
settings, persisted to disk (see projects.py). The MCP server's in-memory
sessions act as a compute cache, keyed by project id and rehydrated from the
stored graph before every operation.
"""

import json
import logging
import os
import queue
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import llm
from .adapters import canvas_to_nodes, nodes_to_canvas
from .intent import apply_patch
from .mcp_client import MCPClient
from .projects import ProjectError, store
from .state_machine import Orchestrator

log = logging.getLogger(__name__)

# How long a streamed turn may stay silent before a keepalive comment is sent.
# Comfortably under the 30s an idle connection is usually cut at, and well
# under how long the Architect can take to answer.
STREAM_HEARTBEAT_S = 10.0

app = FastAPI(title="MACOG Orchestrator", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("VISOR_CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

mcp = MCPClient()
_orchestrator: Optional[Orchestrator] = None


# =========================================================
# MODELS
# =========================================================
class ProjectCreate(BaseModel):
    name: str
    description: str = ""
    settings: Optional[Dict[str, Any]] = None
    nodes: List[Dict[str, Any]] = Field(default_factory=list)
    edges: List[Dict[str, Any]] = Field(default_factory=list)


class ProjectPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None


class GraphSave(BaseModel):
    nodes: List[Dict[str, Any]] = Field(default_factory=list)
    edges: List[Dict[str, Any]] = Field(default_factory=list)


class ProjectChat(BaseModel):
    message: str
    nodes: List[Dict[str, Any]] = Field(default_factory=list)
    edges: List[Dict[str, Any]] = Field(default_factory=list)
    model: Optional[str] = None
    # The human has already accepted a breakpoint this turn would raise, so
    # destructive edits go through instead of stopping the run.
    approved: bool = False


class ProposalApply(BaseModel):
    """The rows of an offered fix the human has decided to take."""
    patch: List[Dict[str, Any]] = Field(default_factory=list)


class ProjectImport(BaseModel):
    payload: Dict[str, Any]
    name: Optional[str] = None


class TerraformImport(BaseModel):
    """One or more .tf files, concatenated."""
    terraform: str
    name: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None


class CompileRequest(BaseModel):
    nodes: List[Dict[str, Any]] = Field(default_factory=list)
    edges: List[Dict[str, Any]] = Field(default_factory=list)
    sessionId: str = "default"
    settings: Optional[Dict[str, Any]] = None


# =========================================================
# LIFECYCLE
# =========================================================
@app.on_event("startup")
def startup():
    global _orchestrator
    mcp.start()
    _orchestrator = Orchestrator(mcp, llm.setup_client(), llm.DEFAULT_MODEL)


@app.on_event("shutdown")
def shutdown():
    mcp.stop()


# =========================================================
# HELPERS
# =========================================================
def _load(project_id: str) -> Dict[str, Any]:
    record = store.get(project_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No project '{project_id}'.")
    return record


def _compile(record: Dict[str, Any]) -> Dict[str, Any]:
    """Rehydrate the MCP session from the stored graph, then compile it."""
    mcp.call_tool("set_graph", {"session_id": record["id"], "nodes": record.get("nodes", [])})
    return mcp.call_tool(
        "compile_terraform",
        {"session_id": record["id"], "settings": record.get("settings") or {}},
    )


def _canonical_graph(project_id: str) -> List[Dict[str, Any]]:
    """
    The graph as the MCP server holds it, in dependency order.

    Read back from the server rather than returned from storage, so it carries
    the server-assigned tf_name and the topological ordering the compiler
    actually used. Call only after _compile has hydrated the session.
    """
    return mcp.call_tool("get_graph", {"session_id": project_id}).get("nodes", [])


def _import_report(report: Dict[str, Any]) -> Dict[str, Any]:
    """The parts of an import result the canvas shows. Nodes are not among them."""
    return {
        "parser": report.get("parser", ""),
        "coverage": report.get("coverage", {}),
        "variables": sorted(report.get("variables", {})),
        "unmapped": report.get("unmapped", []),
        "refused": report.get("refused", []),
        "unsupported": report.get("unsupported", []),
        "skipped": report.get("skipped", []),
        "warnings": report.get("warnings", []),
    }


def _project_payload(record: Dict[str, Any], compiled: Dict[str, Any]) -> Dict[str, Any]:
    errors = compiled.get("errors", [])
    nodes, edges = store.to_canvas(record, errors)
    return {
        "project": store.summarise(record) | {"settings": record.get("settings", {})},
        "nodes": nodes,
        "edges": edges,
        # The two intermediate forms between canvas and HCL: the canonical
        # graph the MCP server holds, and the IR the compiler derives from it.
        "graph": _canonical_graph(record["id"]),
        "terraform": compiled.get("hcl", ""),
        "terraformIr": compiled.get("terraform_ir", {}),
        "errors": errors,
        "warnings": compiled.get("warnings", []),
        "chat": record.get("chat", []),
    }


# =========================================================
# ROUTES - system
# =========================================================
@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": llm.DEFAULT_MODEL,
        "mcp_server": mcp.server_path,
        "project_dir": store.directory,
        "tools": [t["name"] for t in mcp.list_tools()],
        # Which validators can actually prove anything right now. A validator
        # whose tool is missing reports unavailable rather than passing
        # silently - an unproven obligation must never read as a satisfied one.
        "validators": {
            name: validator.availability()
            for name, validator in (_orchestrator.validators if _orchestrator else {}).items()
        },
    }


# =========================================================
# ROUTES - projects
# =========================================================
@app.get("/projects")
def projects_list():
    return {"projects": store.list()}


@app.post("/projects", status_code=201)
def projects_create(request: ProjectCreate):
    try:
        record = store.create(
            name=request.name,
            description=request.description,
            settings=request.settings,
            nodes=canvas_to_nodes(request.nodes, request.edges),
        )
    except ProjectError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _project_payload(record, _compile(record))


@app.post("/projects/import", status_code=201)
def projects_import(request: ProjectImport):
    try:
        record = store.import_project(request.payload, request.name)
    except ProjectError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _project_payload(record, _compile(record))


@app.post("/projects/import/terraform", status_code=201)
def projects_import_terraform(request: TerraformImport):
    """
    Open somebody else's Terraform as a canvas.

    The other import endpoint takes a file this system wrote. This one takes a
    file it did not, which is the difference between a round trip and adoption:
    nobody starts from an empty canvas.

    The response carries an `import` report beside the project, and it is not
    decoration. A resource type with no registry entry, a resource whose
    `count` means one node would misrepresent it, a nested block that could not
    be carried, a module that was not expanded - each is named. An importer
    that shows a tidy canvas and stays quiet about the third of the file it
    dropped is worse than one that refuses, because the canvas looks right.

    Nothing is imported when nothing could be: a project holding none of the
    file is not a useful thing to have created, so that is a 400 carrying the
    report rather than an empty project.
    """
    if not request.terraform.strip():
        raise HTTPException(status_code=400, detail="No Terraform supplied.")

    report = mcp.call_tool("import_terraform", {"hcl": request.terraform})
    if report.get("status") == "failed":
        raise HTTPException(status_code=400, detail=report.get("error", "Could not parse."))

    nodes = report.get("nodes", [])
    if not nodes:
        raise HTTPException(status_code=400, detail={
            "message": "Nothing in that file could be represented on the canvas.",
            "import": _import_report(report),
        })

    # Variable declarations the file's own resources reference. They have no
    # node to live in, and without them the compiled Terraform references
    # variables nobody declared and fails `terraform validate` - so the import
    # is visible but not usable, which is not an import.
    settings = dict(request.settings or {})
    if report.get("variables"):
        settings["variables"] = {**report["variables"], **(settings.get("variables") or {})}

    try:
        record = store.create(
            name=request.name or "Imported Terraform",
            description=f'Imported from Terraform: {len(nodes)} resources.',
            settings=settings or None,
            nodes=nodes,
        )
    except ProjectError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return _project_payload(record, _compile(record)) | {"import": _import_report(report)}


@app.get("/projects/{project_id}")
def project_read(project_id: str):
    record = _load(project_id)
    return _project_payload(record, _compile(record))


@app.patch("/projects/{project_id}")
def project_patch(project_id: str, request: ProjectPatch):
    _load(project_id)
    try:
        record = store.update(
            project_id,
            name=request.name,
            description=request.description,
            settings=request.settings,
        )
    except ProjectError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # Settings feed the compiler preamble, so a settings change changes the HCL.
    return _project_payload(record, _compile(record))


@app.delete("/projects/{project_id}")
def project_delete(project_id: str):
    if not store.delete(project_id):
        raise HTTPException(status_code=404, detail=f"No project '{project_id}'.")
    return {"deleted": project_id}


@app.get("/projects/{project_id}/export")
def project_export(project_id: str):
    try:
        return store.export(project_id)
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/projects/{project_id}/graph")
def project_save_graph(project_id: str, request: GraphSave):
    """
    Persist a hand edit, recompile, and prove it. No model call.

    This is the validation loop's human side, and it is what the canvas calls
    on every drag, drop and field edit. It used to compile and return only the
    compiler's schema errors, which meant a human could set a bucket's ACL to
    `public-read` and hear nothing until they happened to start a chat turn -
    the exact conflict this research is about, detectable by the system and not
    surfaced when it actually happened.

    It reports and stops there. A hand edit never triggers a repair: the agent
    silently rewriting what someone just drew is the failure mode in G6, and
    the deliberate position here is that the system tells the human and waits.
    Escalating to an agent turn is the human's call, through /chat.
    """
    _load(project_id)
    if _orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator is not started.")

    record = store.save_graph(project_id, request.nodes, request.edges)
    outcome = _orchestrator.run(
        intent="",
        nodes=record.get("nodes", []),
        session_id=project_id,
        settings=record.get("settings"),
        repair=False,
    )
    compiled = outcome["compiled"]
    return {
        "graph": outcome["graph"],
        "terraform": compiled.get("hcl", ""),
        "terraformIr": compiled.get("terraform_ir", {}),
        "errors": compiled.get("errors", []),
        "warnings": compiled.get("warnings", []),
        # What the edit is now known to violate, each addressed to a node.
        "validators": outcome["validators"],
        "counterexamples": outcome["counterexamples"],
        # Whether the Terraform this produced still describes the graph.
        "roundTrip": outcome["round_trip"],
        "score": outcome["score"],
        "updatedAt": record["updated_at"],
    }


def _run_chat_turn(
    project_id: str,
    request: ProjectChat,
    record: Dict[str, Any],
    on_event: Optional[Callable[[str, Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """
    One turn, and everything that has to happen around it.

    Shared by POST /chat and POST /chat/stream so the two can never disagree
    about what a turn does. The only difference between them is whether the
    caller watches it happen; the work, the persistence and the payload are the
    same, which is the point of factoring it out rather than writing it twice.
    """
    def _stored_now() -> List[Dict[str, Any]]:
        """The graph as stored right now - a /graph save may have landed mid-turn."""
        latest = store.get(project_id)
        return (latest or {}).get("nodes", [])

    # The agent works in its own MCP session, not the project's. A /graph save
    # arriving mid-turn calls set_graph on the project session; sharing one
    # would let that land inside the graph the agent is holding, so the human's
    # edit would come back out as part of the agent's result and the two would
    # be indistinguishable. One turn session per project, reused - turns for a
    # project are serial, so this stays bounded.
    outcome = _orchestrator.run(
        intent=request.message,
        nodes=canvas_to_nodes(request.nodes, request.edges),
        session_id=f"{project_id}#turn",
        settings=record.get("settings"),
        approved=request.approved,
        reread=_stored_now,
        on_event=on_event,
    )

    nodes, edges = nodes_to_canvas(
        outcome["graph"], outcome["compiled"].get("errors", [])
    )

    # Two reasons not to write this turn's graph, both released the same way -
    # re-send with approved: true. A conflict means the human changed a node
    # this turn also changed, so their version stands and the agent's is
    # offered. A destructive edit means the agent removed something nobody has
    # agreed to lose, and announcing a deletion that has already happened is
    # not asking.
    held = bool(outcome["withheld"])
    if held:
        record = store.get(project_id) or record
        nodes, edges = store.to_canvas(record, outcome["compiled"].get("errors", []))
    elif outcome["resolution"] is not None:
        # The two edits compose: apply the merge, not the agent's graph, which
        # does not contain the human's mid-turn edit. Reached either because
        # the human approved a mergeable conflict, or because they changed
        # something the agent never touched and there was nothing to ask about.
        nodes, edges = nodes_to_canvas(
            outcome["resolution"], outcome["compiled"].get("errors", [])
        )
        record = store.save_graph(project_id, nodes, edges)
    else:
        record = store.save_graph(project_id, nodes, edges)

    record = store.append_chat(project_id, [
        {"role": "user", "content": request.message, "timestamp": record["updated_at"]},
        {"role": "ai", "content": outcome["reply"], "timestamp": record["updated_at"]},
    ])

    return {
        "chatResponse": outcome["reply"] or "Updated the infrastructure graph.",
        "nodes": nodes,
        "edges": edges,
        "graph": outcome["graph"],
        "terraform": outcome["compiled"].get("hcl", ""),
        "terraformIr": outcome["compiled"].get("terraform_ir", {}),
        "errors": outcome["compiled"].get("errors", []),
        "warnings": outcome["compiled"].get("warnings", []),
        # The multi-agent surface the canvas renders: which validators ran and
        # what they said, the failures addressed to specific nodes, and the
        # breakpoints waiting on a human.
        "validators": outcome["validators"],
        "counterexamples": outcome["counterexamples"],
        "roundTrip": outcome["round_trip"],
        "breakpoints": outcome["breakpoints"],
        # Nodes the human and the agent both changed during this turn. When
        # non-empty and unapproved, `applied` is false and the graph above is
        # the human's, not the agent's.
        "conflicts": outcome["conflicts"],
        "resolution": outcome["resolution"],
        # "" when the turn was written, otherwise why it was not.
        "withheld": outcome["withheld"],
        # A fix a policy asked for that the human's own request forbids. Offered
        # as a diff, never applied here - POST /proposal takes it.
        "proposal": outcome["proposal"],
        "applied": not held,
        "repairs": outcome["repairs"],
        "evidence": outcome["bundle"],
        "toolTrace": outcome["trace"],
        "project": store.summarise(record) | {"settings": record.get("settings", {})},
        "chat": record.get("chat", []),
    }


@app.post("/projects/{project_id}/chat")
def project_chat(project_id: str, request: ProjectChat):
    """One turn of the state machine against this project, persisted on the way out."""
    record = _load(project_id)
    if _orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator is not started.")
    return _run_chat_turn(project_id, request, record)


@app.post("/projects/{project_id}/chat/stream")
def project_chat_stream(project_id: str, request: ProjectChat):
    """
    The same turn, watched as it happens.

    A turn takes seconds, and most of that is one model call. Reporting only
    the finished bundle leaves the human in front of a spinner with no idea
    whether an agent is thinking, compiling, or already stopped to ask them
    something - so the states and the blackboard writes are streamed as
    server-sent events, and the identical payload `/chat` returns arrives last
    as the `done` event.

    The turn runs on a worker thread and this generator drains its queue. That
    is deliberate: the orchestrator is synchronous and calls blocking things -
    the model, opa, terraform - so running it inline would block the event loop
    and nothing would be delivered until the end, which is the problem this
    endpoint exists to solve.
    """
    record = _load(project_id)
    if _orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator is not started.")

    events: "queue.Queue[Optional[Tuple[str, Dict[str, Any]]]]" = queue.Queue()

    def work() -> None:
        try:
            payload = _run_chat_turn(
                project_id, request, record,
                on_event=lambda kind, data: events.put((kind, data)),
            )
            events.put(("done", payload))
        except Exception as error:  # noqa: BLE001 - reported to the client, not swallowed
            log.exception("streamed chat turn failed")
            events.put(("failed", {"message": str(error) or error.__class__.__name__}))
        finally:
            # Always: the generator below blocks on this queue, so a turn that
            # raises before reaching either put would hang the response open.
            events.put(None)

    worker = threading.Thread(target=work, name=f"chat-{project_id}", daemon=True)
    worker.start()

    def stream():
        while True:
            try:
                item = events.get(timeout=STREAM_HEARTBEAT_S)
            except queue.Empty:
                # A comment frame. Proxies and load balancers drop a connection
                # that says nothing, and the Architect's model call can be
                # quiet for a while.
                yield ": keepalive\n\n"
                continue
            if item is None:
                return
            kind, data = item
            yield f"event: {kind}\ndata: {json.dumps(data, default=str)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            # Nginx buffers event streams into uselessness without this.
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/projects/{project_id}/proposal")
def project_apply_proposal(project_id: str, request: ProposalApply):
    """
    Take a fix the last turn offered. No model call.

    The offer is a list of attribute rows, and they are applied to the graph as
    it stands right now rather than by storing the proposal's own node list. An
    offer sits on screen for as long as the human takes to read it, and in that
    time they may have edited something else; replacing the whole graph would
    quietly roll those edits back, which is the same failure this feature
    exists to prevent, arriving through the fix instead of the repair.

    Refusing an offer needs no endpoint. The graph already says what the human
    asked for - the violation simply stays visible on the node.
    """
    record = _load(project_id)
    if _orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator is not started.")
    if not request.patch:
        raise HTTPException(status_code=400, detail="No patch rows to apply.")

    patched, stale = apply_patch(record.get("nodes", []), request.patch)
    record = store.update(project_id, nodes=patched)

    outcome = _orchestrator.run(
        intent="",
        nodes=record.get("nodes", []),
        session_id=project_id,
        settings=record.get("settings"),
        repair=False,
    )
    compiled = outcome["compiled"]
    nodes, edges = store.to_canvas(record, compiled.get("errors", []))
    return {
        "nodes": nodes,
        "edges": edges,
        "graph": outcome["graph"],
        "terraform": compiled.get("hcl", ""),
        "terraformIr": compiled.get("terraform_ir", {}),
        "errors": compiled.get("errors", []),
        "warnings": compiled.get("warnings", []),
        "validators": outcome["validators"],
        "counterexamples": outcome["counterexamples"],
        "roundTrip": outcome["round_trip"],
        "score": outcome["score"],
        # Rows that named a node which is no longer there. Reported rather than
        # ignored: the human should know their decision was partly moot.
        "stale": stale,
        "updatedAt": record["updated_at"],
    }


@app.post("/projects/{project_id}/verify")
def project_verify(project_id: str):
    """
    Run every validator against the stored graph. Observation only.

    This is the human's side of the validation loop: the canvas asks for the
    graph as it stands to be proven, rather than waiting for the next chat
    turn. No model is called and the graph is not edited - the answer has to be
    about the graph the human drew, not about one an agent silently repaired
    on the way past. `terraform validate` always runs here, unlike in a chat
    turn.
    """
    record = _load(project_id)
    if _orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator is not started.")

    outcome = _orchestrator.run(
        intent="",
        nodes=record.get("nodes", []),
        session_id=project_id,
        settings=record.get("settings"),
        deploy_validation=True,
        repair=False,
    )
    return {
        "validators": outcome["validators"],
        "counterexamples": outcome["counterexamples"],
        "roundTrip": outcome["round_trip"],
        "score": outcome["score"],
        "evidence": outcome["bundle"],
    }


@app.get("/projects/{project_id}/drift")
def project_drift(project_id: str):
    record = _load(project_id)
    _compile(record)
    return mcp.call_tool("drift_check", {"session_id": project_id})


# =========================================================
# ROUTES - stateless utilities
# =========================================================
@app.post("/graph/compile")
def graph_compile(request: CompileRequest):
    """Compile a graph without storing it. Used by tooling and tests."""
    mcp.call_tool("set_graph", {
        "session_id": request.sessionId,
        "nodes": canvas_to_nodes(request.nodes, request.edges),
    })
    compiled = mcp.call_tool(
        "compile_terraform",
        {"session_id": request.sessionId, "settings": request.settings or {}},
    )
    return {
        "terraform": compiled.get("hcl", ""),
        "terraformIr": compiled.get("terraform_ir", {}),
        "errors": compiled.get("errors", []),
        "warnings": compiled.get("warnings", []),
    }
