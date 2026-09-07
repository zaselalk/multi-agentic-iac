"""
Provider Harmonizer.

MACOG's harmonizer instantiates abstract resources against provider schemas,
resolves version constraints and expands defaults. Two of those three already
happen deterministically here: the compiler expands registry defaults while it
lowers each node, and the preamble pins the provider version.

What is left is the part that has no home elsewhere - checking that the graph
the Architect produced is actually expressible in the registry, before the
compiler silently drops a node it does not recognise. Running this before
compilation turns "the resource vanished from my Terraform" into a named
diagnostic on the right canvas node.

It resolves nothing it cannot resolve deterministically, and calls no model.
"""

import json
import os
from typing import Any, Dict, List

from ..mcp_client import DEFAULT_MCP_PATH

SCHEMA_PATH = os.environ.get("VISOR_SCHEMA", os.path.join(DEFAULT_MCP_PATH, "schema.json"))


class ProviderHarmonizer:
    name = "harmonizer"

    def __init__(self, schema: Dict[str, Any] = None):
        if schema is None:
            with open(SCHEMA_PATH) as handle:
                schema = json.load(handle)
        self.schema = schema
        self.registry = schema.get("resource_registry", {})
        self.preamble = schema.get("compiler", {}).get("preamble", {})

    def run(self, nodes: List[Dict[str, Any]], settings: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Returns {"pinning": ..., "counterexamples": [...]}.

        Counterexamples use the same shape the validators emit, so the repair
        loop consumes them without a special case.
        """
        settings = settings or {}
        found: List[Dict[str, Any]] = []

        for node in nodes:
            provider = node.get("provider", "aws")
            resource = node.get("resource")
            node_id = node.get("node_id", "")

            if provider not in self.registry:
                found.append(_ce(
                    node_id, f'No registry for provider "{provider}".',
                    "Only providers present in schema.json can be compiled; "
                    "add a registry entry or change the node's provider.",
                ))
                continue

            entry = self.registry[provider].get(resource)
            if entry is None:
                available = ", ".join(sorted(self.registry[provider]))
                found.append(_ce(
                    node_id,
                    f'Resource "{resource}" is not in the {provider} registry, '
                    f"so it will not appear in the compiled Terraform.",
                    f"Use one of: {available} - or add a registry entry for "
                    f'"{resource}" in mcp-server/schema.json.',
                ))
                continue

            # A desired_state key the registry neither maps nor defaults is not
            # an error - the compiler passes unknown keys through to the
            # provider - but it is unproven, and terraform validate is the
            # thing that will catch it. Flag it as a warning so the trail says
            # where an unrecognised field came from.
            known = (
                set(entry.get("attribute_map", {}))
                | set(entry.get("attribute_map", {}).values())
                | set(entry.get("defaults", {}))
                | set(entry.get("required_attributes", []))
                | {r["attribute"] for r in entry.get("references", [])}
                # Virtual attributes are registry concepts even though they are
                # never emitted as fields - `versioning` on a bucket drives the
                # aws_s3_bucket_versioning companion. Omitting them here flagged
                # a documented attribute as unrecognised.
                | set(entry.get("virtual_attributes", {}))
                | {
                    derived
                    for spec in entry.get("virtual_attributes", {}).values()
                    for derived in spec.get("derived", {})
                }
                # Attributes the compiler fills in itself - an RDS instance's
                # `identifier`, its `password` variable reference. Setting one
                # explicitly overrides the computation; it is not unrecognised.
                | set(entry.get("computed_attributes", {}))
                # Every taggable resource takes tags, and the compiler folds a
                # node's own map into the merge() it emits. The registry does
                # not list `tags` per resource because `taggable: true` already
                # says it.
                | ({"tags"} if entry.get("taggable") else set())
            )
            for key in node.get("desired_state", {}):
                if key not in known:
                    found.append(_ce(
                        node_id,
                        f'"{key}" is not described by the registry entry for '
                        f'{entry["terraform_type"]}; it is passed through unchecked.',
                        "Confirm it against the provider docs, or add it to the "
                        "registry so it is validated.",
                        severity="warning",
                    ))

        return {
            "pinning": {
                "required_version": self.preamble.get("required_version"),
                "aws_provider_version": self.preamble.get("aws_provider_version"),
                "region": settings.get("region") or self.preamble.get("region_variable", {}).get("default"),
            },
            "counterexamples": found,
        }


def _ce(node_id: str, message: str, fix_hint: str, severity: str = "error") -> Dict[str, Any]:
    return {
        "node_id": node_id,
        "type": "harmonization",
        "rule": "registry_coverage",
        "message": message,
        "severity": severity,
        "fix_hint": fix_hint,
    }
