"""
Translation between the canvas's React Flow model and the canonical node model
in mcp-server/schema.json.

The canvas thinks in {id, type, position, data.details}; the MCP server thinks
in {node_id, resource, desired_state, depends_on, view}. Neither repo knew
about the other's shape before - this module is the single place the mapping
lives.
"""

import json
import os
from typing import Any, Dict, List, Tuple

from .mcp_client import DEFAULT_MCP_PATH

SCHEMA_PATH = os.environ.get(
    "VISOR_SCHEMA", os.path.join(DEFAULT_MCP_PATH, "schema.json")
)

with open(SCHEMA_PATH) as f:
    SCHEMA = json.load(f)

UI_TYPE_MAP: Dict[str, str] = SCHEMA["ui_binding"]["type_map"]          # 's3' -> 's3_bucket'
RESOURCE_TO_UI: Dict[str, str] = {v: k for k, v in UI_TYPE_MAP.items()}
REGISTRY = SCHEMA["resource_registry"]
SPATIAL = SCHEMA.get("spatial_semantics", {})

# Canvas layout constants, used only for nodes the agent created that have no
# position yet. Existing nodes keep whatever the user dragged them to.
COLUMN_WIDTH = 300
ROW_HEIGHT = 170
ORIGIN = (80, 60)


# =========================================================
# CANVAS -> CANONICAL
# =========================================================
def implies_dependency(child_resource: str, parent_resource: str, provider: str = "aws") -> bool:
    """
    Does nesting this child in this parent mean anything to Terraform?

    The registry is the gate (schema.json `spatial_semantics.nesting`): an EC2
    inside a subnet implies `subnet_id` because the registry declares that
    reference; an EC2 inside a VPC implies nothing, because it declares no
    aws_instance -> aws_vpc reference. Without the gate, nesting could invent a
    relationship Terraform has no way to express.
    """
    entry = REGISTRY.get(provider, {}).get(child_resource)
    if not entry:
        return False
    return any(
        reference.get("from_resource") == parent_resource
        for reference in entry.get("references", [])
    )


def canvas_to_nodes(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    React Flow nodes + edges -> canonical nodes.

    An edge source->target is read as "target depends on source", matching how
    the canvas draws VPC -> Subnet -> EC2.

    Containment is read too. A node dropped inside a subnet box has said
    something, and the graph would otherwise lose it - see `spatial_semantics`
    in schema.json for how much of that is binding.
    """
    depends: Dict[str, List[str]] = {}
    implied: Dict[str, List[str]] = {}
    ids = {n.get("id") for n in nodes}

    for edge in edges or []:
        # An implied edge is this function's own output coming back round. Skip
        # it and re-derive from parent_id, so un-nesting a node removes the
        # dependency rather than baking it in as an explicit one.
        if (edge.get("data") or {}).get("implied"):
            continue
        source, target = edge.get("source"), edge.get("target")
        if source in ids and target in ids and source != target:
            depends.setdefault(target, [])
            if source not in depends[target]:
                depends[target].append(source)

    # Nesting -> implied dependency, gated on the registry.
    resource_of = {
        n.get("id"): UI_TYPE_MAP.get(n.get("type"))
        for n in nodes or []
        if n.get("id")
    }
    for node in nodes or []:
        node_id, parent_id = node.get("id"), node.get("parentId")
        if not node_id or not parent_id or parent_id not in ids:
            continue
        child_resource, parent_resource = resource_of.get(node_id), resource_of.get(parent_id)
        if not child_resource or not parent_resource:
            continue
        if not implies_dependency(child_resource, parent_resource):
            continue
        if parent_id not in depends.get(node_id, []):
            depends.setdefault(node_id, []).append(parent_id)
            implied.setdefault(node_id, []).append(parent_id)

    canonical: List[Dict[str, Any]] = []
    for node in nodes or []:
        node_id = node.get("id")
        ui_type = node.get("type")
        resource = UI_TYPE_MAP.get(ui_type)
        if not node_id or not resource:
            continue

        data = node.get("data") or {}
        details = data.get("details") or {}

        view: Dict[str, Any] = {"ui_type": ui_type}
        if node.get("position"):
            view["position"] = node["position"]
        if node.get("parentId"):
            view["parent_id"] = node["parentId"]
        if node.get("style"):
            view["style"] = node["style"]
        # Which of this node's dependencies came from nesting rather than a
        # drawn edge. Kept in `view` because it is a fact about the visual
        # model, and so the canvas can draw those edges as derived.
        if implied.get(node_id):
            view["implied_depends_on"] = implied[node_id]

        canonical.append({
            "node_id": node_id,
            "provider": "aws",
            "resource": resource,
            "desired_state": dict(details),
            "depends_on": depends.get(node_id, []),
            "view": view,
            "status": data.get("status", "synced"),
        })
    return canonical


# =========================================================
# CANONICAL -> CANVAS
# =========================================================
def _auto_layout(nodes: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    """Column per dependency depth, row per node within that depth."""
    by_id = {n["node_id"]: n for n in nodes}
    depth: Dict[str, int] = {}

    def compute(node_id: str, seen: frozenset = frozenset()) -> int:
        if node_id in depth:
            return depth[node_id]
        if node_id in seen:
            return 0
        parents = [d for d in by_id[node_id].get("depends_on", []) if d in by_id]
        value = 0 if not parents else 1 + max(
            compute(p, seen | {node_id}) for p in parents
        )
        depth[node_id] = value
        return value

    for node in nodes:
        compute(node["node_id"])

    rows: Dict[int, int] = {}
    positions: Dict[str, Dict[str, float]] = {}
    for node in nodes:
        d = depth[node["node_id"]]
        row = rows.get(d, 0)
        rows[d] = row + 1
        positions[node["node_id"]] = {
            "x": ORIGIN[0] + d * COLUMN_WIDTH,
            "y": ORIGIN[1] + row * ROW_HEIGHT,
        }
    return positions


def nodes_to_canvas(
    nodes: List[Dict[str, Any]],
    errors: List[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Canonical nodes -> (React Flow nodes, React Flow edges)."""
    errors = errors or []
    failed = {e.get("node_id") for e in errors}
    layout = _auto_layout(nodes)

    canvas_nodes: List[Dict[str, Any]] = []
    canvas_edges: List[Dict[str, Any]] = []

    for node in nodes:
        node_id = node["node_id"]
        resource = node.get("resource")
        entry = REGISTRY.get(node.get("provider", "aws"), {}).get(resource, {})
        view = node.get("view") or {}

        status = "error" if node_id in failed else "synced"

        canvas_node: Dict[str, Any] = {
            "id": node_id,
            "type": RESOURCE_TO_UI.get(resource, "s3"),
            "position": view.get("position") or layout[node_id],
            "data": {
                "resourceName": f'{entry.get("terraform_type", resource)}.{node.get("tf_name", node_id)}',
                "status": status,
                "terraformType": entry.get("terraform_type", resource),
                "details": {k: _stringify(v) for k, v in (node.get("desired_state") or {}).items()},
            },
        }
        if view.get("parent_id"):
            canvas_node["parentId"] = view["parent_id"]
            canvas_node["extent"] = "parent"
        if view.get("style"):
            canvas_node["style"] = view["style"]

        canvas_nodes.append(canvas_node)

        derived = set(view.get("implied_depends_on") or [])
        for dep in node.get("depends_on", []):
            edge: Dict[str, Any] = {
                "id": f"{dep}-{node_id}",
                "source": dep,
                "target": node_id,
                "type": "smoothstep",
            }
            if dep in derived:
                # Drawn dashed, and ignored on the way back in - the nesting is
                # the source of truth for this edge, not the edge itself.
                edge["data"] = {"implied": True}
                edge["animated"] = False
                edge["style"] = {"strokeDasharray": "6 4", "opacity": 0.75}
            canvas_edges.append(edge)

    return canvas_nodes, canvas_edges


def _stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return str(value)
