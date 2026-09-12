"""
One fault, one defined right answer.

Every injector takes a clean graph and does exactly one thing to it, and
declares which rule should fire and on which node. That declaration is what
makes scoring mechanical: no judgement, no model, no reading of messages. If a
rule fires on the wrong node the benchmark says so, which is the measurement
this system exists to make possible.

Three details worth knowing before reading the table:

- **`node` can be a set.** A dependency cycle belongs to every node in it, and
  the compiler names them all, so "the right node" is a membership test rather
  than an equality one. Pretending otherwise would either fail a correct answer
  or accept a wrong one.
- **`node` can be `None`.** A residency breach is a property of the project,
  not of any resource. Attribution is *not applicable* there, and scoring it as
  a failure would understate the system; scoring it as a success would
  overstate it. It is reported separately.
- **`needs_plan`.** One fault is invisible to the IR and only appears in a real
  `terraform plan`. It is the case that justifies running the provider at all,
  so it is marked rather than quietly given a longer timeout.

`broken_invariant` - a registry entry losing its `companion_resources` - is
deliberately absent. It is a fault in the *compiler's own configuration* rather
than in a graph, so injecting it means mutating a schema the MCP server loads
in another process. It is covered instead by
`mcp-server/tests/test_round_trip.py::BrokenRegistryTest`, which breaks the
registry on purpose and asserts the round-trip check reports it. Listing it
here and skipping it would be worse than saying where it actually lives.
"""

from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .corpus import Graph, node

Expected = Dict[str, Any]
Injector = Callable[[Graph, Dict[str, Any]], Optional[Expected]]


def _first(graph: Graph, resource: str) -> Optional[str]:
    for node_id, entry in graph.items():
        if entry.get("resource") == resource:
            return node_id
    return None


def _first_taggable(graph: Graph) -> Optional[str]:
    taggable = {"vpc", "subnet", "ec2", "rds", "s3_bucket", "lambda", "dynamodb", "sqs"}
    for node_id, entry in graph.items():
        if entry.get("resource") in taggable:
            return node_id
    return None


# ---------------------------------------------------------
# THE INJECTORS
# ---------------------------------------------------------
def public_acl(graph: Graph, settings: Dict[str, Any]) -> Optional[Expected]:
    """A bucket made publicly readable - the canonical visual-edit violation."""
    target = _first(graph, "s3_bucket")
    if not target:
        return None
    graph[target]["desired_state"]["acl"] = "public-read"
    return {"rule": "s3_public_acl", "node": {target}, "attribute": "acl"}


def unencrypted_db(graph: Graph, settings: Dict[str, Any]) -> Optional[Expected]:
    """Encryption at rest turned off on a database."""
    target = _first(graph, "rds")
    if not target:
        return None
    graph[target]["desired_state"]["storage_encrypted"] = False
    return {
        "rule": "rds_storage_encrypted",
        "node": {target},
        "attribute": "storage_encrypted",
    }


def tag_override(graph: Graph, settings: Dict[str, Any]) -> Optional[Expected]:
    """
    A node tag shadowing a project default.

    The IR cannot see this: it holds `tags = merge(local.default_tags, ...)` as
    text, which still composes the defaults and satisfies every IR rule. Only a
    real plan resolves `tags_all` and shows the override. This is the fault
    that justifies the DevOps validator, and the ablation row that removes it.
    """
    target = _first_taggable(graph)
    if not target:
        return None
    owner = settings.get("default_tags", {}).get("Owner", "visor")
    graph[target]["desired_state"]["tags"] = {"Owner": f"not-{owner}"}
    return {
        "rule": "plan_default_tags_resolved",
        "node": {target},
        "attribute": "tags",
        "needs_plan": True,
    }


def dependency_cycle(graph: Graph, settings: Dict[str, Any]) -> Optional[Expected]:
    """A back-edge across an existing dependency, making the DAG not one."""
    for node_id, entry in graph.items():
        for dep in entry.get("depends_on", []):
            if dep in graph:
                graph[dep]["depends_on"].append(node_id)
                return {
                    "type": "dag_cycle_detection",
                    # A cycle belongs to every node in it, and the compiler
                    # names them all in one finding.
                    "node": {node_id, dep},
                    "attribute": "depends_on",
                    "cycle": True,
                }
    return None


def residency_breach(graph: Graph, settings: Dict[str, Any]) -> Optional[Expected]:
    """A project region outside its own allowed set. Belongs to no node."""
    region = settings.get("region", "eu-west-1")
    others = ["us-east-1", "ap-southeast-2"]
    settings["allowed_regions"] = [r for r in others if r != region]
    return {"rule": "region_not_allowed", "node": None, "attribute": "region"}


def unknown_resource(graph: Graph, settings: Dict[str, Any]) -> Optional[Expected]:
    """A resource type the registry has never heard of."""
    graph["rogue-cluster"] = node("rogue-cluster", "eks_cluster", {"name": "rogue"})
    return {"rule": "registry_coverage", "node": {"rogue-cluster"}, "attribute": ""}


def missing_required(graph: Graph, settings: Dict[str, Any]) -> Optional[Expected]:
    """
    A required attribute emptied out.

    Emptied rather than deleted, because every required attribute in this
    registry has a default or is computed - deleting one is invisible, which is
    itself a small result about how hard the compiler makes this class of fault
    to produce.
    """
    target = _first(graph, "s3_bucket")
    if not target:
        return None
    graph[target]["desired_state"]["bucket"] = ""
    return {"type": "schema_validation", "node": {target}, "attribute": "bucket"}


def invalid_value(graph: Graph, settings: Dict[str, Any]) -> Optional[Expected]:
    """A value failing the registry's own pattern for that attribute."""
    target = _first(graph, "rds")
    if not target:
        return None
    graph[target]["desired_state"]["instance_class"] = "t3.small"  # needs db.*
    return {"type": "schema_validation", "node": {target}, "attribute": "instance_class"}


FAULTS: Dict[str, Injector] = {
    "public_acl": public_acl,
    "unencrypted_db": unencrypted_db,
    "tag_override": tag_override,
    "dependency_cycle": dependency_cycle,
    "residency_breach": residency_breach,
    "unknown_resource": unknown_resource,
    "missing_required": missing_required,
    "invalid_value": invalid_value,
}

# What each one is meant to exercise, for the results table.
VALIDATOR: Dict[str, str] = {
    "public_acl": "policy",
    "unencrypted_db": "policy",
    "tag_override": "policy (plan-grounded)",
    "dependency_cycle": "schema",
    "residency_breach": "policy",
    "unknown_resource": "harmonizer",
    "missing_required": "schema",
    "invalid_value": "schema",
}
