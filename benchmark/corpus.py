"""
Graphs that pass everything, before anything is done to them.

A seeded-fault benchmark measures the difference a fault makes, so the baseline
has to be clean: if a base graph already violates something, every number
measured against it is the sum of two effects and worth nothing. `verify_clean`
is therefore not a convenience - it is the precondition the whole experiment
rests on, and the harness refuses to score a corpus that fails it.

The five shapes are chosen to spread across the registry rather than to be
realistic. Between them they use all ten registered resource types, both
reference kinds (attribute and `@block:`), companion emission, virtual
attributes and the variable fallback - so a fault injected into any of them is
being injected into machinery that is actually exercised.
"""

from typing import Any, Dict, List

Graph = Dict[str, Dict[str, Any]]


def node(node_id: str, resource: str, desired: Dict[str, Any] = None,
         depends: List[str] = None) -> Dict[str, Any]:
    return {
        "node_id": node_id,
        "provider": "aws",
        "resource": resource,
        "desired_state": dict(desired or {}),
        "depends_on": list(depends or []),
        "view": {},
        "status": "active",
    }


def _graph(*nodes: Dict[str, Any]) -> Graph:
    return {n["node_id"]: n for n in nodes}


# ---------------------------------------------------------
# THE CORPUS
# ---------------------------------------------------------
CORPUS: Dict[str, Graph] = {
    # Network, compute and a database behind it. The shape most people draw
    # first, and the only one exercising a required reference (subnet -> vpc).
    "three_tier": _graph(
        node("app-vpc", "vpc", {"cidr_block": "10.0.0.0/16"}),
        node("app-subnet", "subnet", {"cidr_block": "10.0.1.0/24"}, ["app-vpc"]),
        node("web", "ec2", {"instance_type": "t3.small"}, ["app-subnet"]),
        node("orders-db", "rds", {"engine": "postgres", "allocated_storage": 50}),
    ),

    # Object storage behind a CDN. Exercises the `@block:` reference and the
    # three S3 compliance companions.
    "static_site": _graph(
        node("site-assets", "s3_bucket", {"bucket": "visor-bench-assets", "versioning": True}),
        node("site-cdn", "cloudfront", {}, ["site-assets"]),
    ),

    # No servers at all. Exercises computed attributes and extra_variables.
    "serverless_api": _graph(
        node("api", "apigateway", {}),
        node("handler", "lambda", {"runtime": "python3.11"}, ["api"]),
        node("sessions", "dynamodb", {"hash_key": "session_id"}, ["handler"]),
    ),

    # A queue in front of a worker. Two nodes of the same shape as the
    # serverless case but wired the other way round, which is where dependency
    # direction faults land differently.
    "queue_worker": _graph(
        node("jobs", "sqs", {}),
        node("worker", "lambda", {"runtime": "nodejs18.x"}, ["jobs"]),
        node("results", "dynamodb", {"hash_key": "job_id"}, ["worker"]),
    ),

    # Storage only. The smallest graph that can carry both an S3 and an RDS
    # fault, so it is the cheapest case to debug an injector against.
    "data_store": _graph(
        node("archive", "s3_bucket", {"bucket": "visor-bench-archive"}),
        node("ledger", "rds", {"engine": "mysql", "instance_class": "db.t3.small"}),
    ),
}

SETTINGS: Dict[str, Any] = {
    "region": "eu-west-1",
    "default_tags": {"Owner": "visor", "Environment": "bench", "CostCenter": "0000"},
}


def clone(name: str) -> Graph:
    """A fresh copy, because every injector mutates."""
    import copy
    return copy.deepcopy(CORPUS[name])
