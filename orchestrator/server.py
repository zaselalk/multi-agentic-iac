"""
HTTP front door for the multi-agent orchestrator.

    uvicorn orchestrator.server:app --port 8080

The canvas (visual-devops-builder) talks to this; this talks MCP to
mcp-server; generation goes through evaluation/eval.py's Azure AI Foundry
client, so the research pipeline and the product share one backend.

Work is organised into projects: one named graph with its own Terraform
settings, persisted to disk (see projects.py). The MCP server's in-memory
sessions act as a compute cache, keyed by project id and rehydrated from the
stored graph before every operation.
"""

import os
import sys
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "evaluation"))
)

import eval as pipeline  # noqa: E402  - also loads ../.env via python-dotenv

from .adapters import canvas_to_nodes, nodes_to_canvas  # noqa: E402
from .agent import GraphAgent, DEFAULT_MODEL  # noqa: E402
from .mcp_client import MCPClient  # noqa: E402
from .projects import ProjectError, store  # noqa: E402

app = FastAPI(title="MACOG Orchestrator", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("VISOR_CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

mcp = MCPClient()
_retriever = None


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
    useRag: bool = False
    model: Optional[str] = None


class ProjectImport(BaseModel):
    payload: Dict[str, Any]
    name: Optional[str] = None


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
    mcp.start()
    pipeline.setup_azure_foundry_client()


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
        "model": DEFAULT_MODEL,
        "mcp_server": mcp.server_path,
        "project_dir": store.directory,
        "tools": [t["name"] for t in mcp.list_tools()],
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
    """Persist a hand edit and recompile. No model call."""
    _load(project_id)
    record = store.save_graph(project_id, request.nodes, request.edges)
    compiled = _compile(record)
    return {
        "graph": _canonical_graph(project_id),
        "terraform": compiled.get("hcl", ""),
        "terraformIr": compiled.get("terraform_ir", {}),
        "errors": compiled.get("errors", []),
        "warnings": compiled.get("warnings", []),
        "updatedAt": record["updated_at"],
    }


@app.post("/projects/{project_id}/chat")
def project_chat(project_id: str, request: ProjectChat):
    """One agent turn against this project's graph, persisted on the way out."""
    record = _load(project_id)

    knowledge, rag_error = "", None
    if request.useRag:
        knowledge, rag_error = _ground(request.message)

    agent = GraphAgent(mcp, pipeline.azure_foundry_client, model=request.model)
    result = agent.run(
        message=request.message,
        canvas_nodes=request.nodes,
        canvas_edges=request.edges,
        session_id=project_id,
        knowledge=knowledge,
        settings=record.get("settings"),
    )

    record = store.save_graph(project_id, result["nodes"], result["edges"])
    record = store.append_chat(project_id, [
        {"role": "user", "content": request.message, "timestamp": record["updated_at"]},
        {"role": "ai", "content": result["chatResponse"], "timestamp": record["updated_at"]},
    ])
    result["project"] = store.summarise(record) | {"settings": record.get("settings", {})}
    result["chat"] = record.get("chat", [])
    result["graph"] = _canonical_graph(project_id)

    if rag_error:
        result.setdefault("warnings", []).append({
            "node_id": "",
            "message": f"Retrieval grounding unavailable: {rag_error}",
            "recommendation": "Run without RAG, or rebuild retriever/aws-index against the configured embedding model.",
        })
    return result


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


# =========================================================
# RAG
# =========================================================
def _ground(query: str):
    """Retrieval grounding, reusing the evaluation pipeline's retriever."""
    global _retriever
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        if _retriever is None:
            import llama_index_retriever
            _retriever = llama_index_retriever.Retriever(
                stored_index=os.path.join(here, "..", "retriever", "aws-index"),
                path=os.path.join(here, "..", "retriever", "terraform-provider-aws",
                                  "website", "docs", "r"),
            )
        return pipeline.rag_knowledge(_retriever, query), None
    except Exception as e:
        _retriever = None
        return "", str(e)
