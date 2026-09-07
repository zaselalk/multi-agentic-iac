"""
v_schema - the Reviewer's static check.

MACOG's Reviewer runs `terraform validate`, HCL linters and interface sanity
checks. Here the equivalent runs one stage earlier and is free: the
deterministic compiler in mcp-server already validates every node against the
resource registry while it lowers the graph, so this validator reads that
report rather than re-deriving it.

That ordering is the point. Because the compiler cannot emit HCL that strays
outside the registry, whole classes of error MACOG has to catch after
generation cannot occur here at all - the schema check is about the *graph*
being well-formed, not about the text being parseable. `terraform validate`
still runs, in the deploy validator, as the independent confirmation.
"""

from typing import Any, Dict

from .base import counterexample, result


class SchemaValidator:
    name = "schema"

    def run(self, compiled: Dict[str, Any], **_) -> Dict[str, Any]:
        errors = compiled.get("errors") or []
        warnings = compiled.get("warnings") or []

        found = [
            counterexample(
                node_id=e.get("node_id", ""),
                type_=e.get("type", "schema_validation"),
                message=e.get("message", ""),
                severity=e.get("severity", "error"),
                fix_hint=_hint(e),
                attribute=e.get("attribute", ""),
            )
            for e in errors
        ]
        found += [
            counterexample(
                node_id=w.get("node_id", ""),
                type_="schema_validation",
                message=w.get("message", ""),
                severity="warning",
                fix_hint=w.get("recommendation", ""),
                attribute=w.get("attribute", ""),
            )
            for w in warnings
        ]

        blocking = [c for c in found if c["severity"] == "error"]
        return result(
            self.name,
            "fail" if blocking else "pass",
            counterexamples=found,
            evidence={"errors": len(errors), "warnings": len(warnings)},
        )


    def availability(self):
        """Always available - it reads a report the compiler already produced."""
        return {"available": True, "reason": ""}

def _hint(error: Dict[str, Any]) -> str:
    kind = error.get("type", "")
    if kind == "dag_cycle_detection":
        return "Break the cycle: remove one of the depends_on edges between these nodes."
    message = error.get("message", "")
    if message.startswith("Missing required attribute"):
        return "Set that attribute on the node with update_node."
    if "does not match" in message:
        return "Correct the value to satisfy the registry's pattern for that attribute."
    return ""
