"""
Memory Curator. NOT IMPLEMENTED - interface only.

MACOG stores verified tuples (P, T, Pi) and serves typed motifs back to the
Architect so a plan that matches a known-good structure is seeded rather than
re-derived. Its ablation is the mildest of the eight (74.02 -> 72.17 on
IaC-Eval), which is why it is the last thing built here rather than the first.

For this research it matters more than it does for MACOG, because the motifs
are *visual*: a verified motif is a subgraph plus its layout, so reusing one
restores the arrangement the human recognises, not just the resources. That is
the "Verified Visual Motifs" line in the proposal, and it is the thing the
canvas would offer as a suggestion.

To implement:

1. `store()` - on a turn that ends `done` with every validator passing, write
   {graph subgraph, compiled HCL digest, evidence bundle, view positions}
   under a structural key.
2. Key on graph *shape*, not text: (sorted resource kinds, edge multiset)
   canonicalised, so "VPC + 2 subnets + ALB" retrieves regardless of naming.
3. `retrieve()` - called before the Architect plans, injecting matching motifs
   into its context as typed fragments, never as raw HCL (MACOG S4.10: typed
   motifs avoid version drift).
4. Persist alongside projects (see projects.py), not in memory.

Until then `retrieve()` returns nothing and the Architect plans unseeded, which
is exactly the "- Memory Curator" ablation row.
"""

from typing import Any, Dict, List


class MemoryCurator:
    name = "curator"

    def retrieve(self, nodes: List[Dict[str, Any]], intent: str) -> List[Dict[str, Any]]:
        """Verified motifs matching this graph's shape. Always empty for now."""
        return []

    def store(self, nodes: List[Dict[str, Any]], compiled: Dict[str, Any],
              bundle: Dict[str, Any]) -> None:
        """Record a fully-validated turn as a reusable motif. No-op for now."""
        return None

    @staticmethod
    def shape_key(nodes: List[Dict[str, Any]]) -> str:
        """
        The structural key motifs would be indexed by.

        Implemented now because it is the part that has to be agreed before
        anything can be stored, and it is testable without a store.
        """
        kinds = sorted(n.get("resource", "") for n in nodes)
        edges = sorted(
            f'{dep}->{n.get("resource", "")}'
            for n in nodes for dep in n.get("depends_on", [])
        )
        return "|".join(kinds) + "#" + str(len(edges))
