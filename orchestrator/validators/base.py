"""
The envelope every validator returns.

Kept in its own module so the validators can import it without going through
the package __init__ that imports them.
"""

from typing import Any, Dict, List, Optional

STATUSES = ("pass", "fail", "skipped")


def result(name: str, status: str, counterexamples: Optional[List[Dict[str, Any]]] = None,
           reason: str = "", evidence: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build a validator envelope."""
    if status not in STATUSES:
        raise ValueError(f"validator status must be one of {STATUSES}, got {status!r}")
    return {
        "name": name,
        "status": status,
        "reason": reason,
        "counterexamples": counterexamples or [],
        "evidence": evidence or {},
    }


def counterexample(node_id: str, type_: str, message: str, rule: str = "",
                   severity: str = "error", fix_hint: str = "",
                   attribute: str = "",
                   patch: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    The machine-readable form a repair is derived from.

    `node_id` is what makes this different from MACOG's counterexamples: it
    addresses the failure to a canvas node, so the same object drives both the
    Error-to-Edit mapping and the visual overlay the human sees.

    `attribute` names the desired_state key the failure is about, when there is
    one. It is what lets the router tell an omission from a contradiction: a
    failure on an attribute the human asked for is not the same event as one on
    an attribute nobody mentioned, and only the first should stop the run.

    `patch` is the deterministic fix, as desired_state keys to write - a value
    of None meaning "remove this key". Where a validator can name it, the
    system can offer the repair without a model round, which is what makes the
    offer reproducible and cheap enough to make every time.
    """
    return {
        "node_id": node_id or "",
        "type": type_,
        "rule": rule,
        "message": message,
        "severity": severity,
        "fix_hint": fix_hint,
        "attribute": attribute,
        "patch": patch,
    }
