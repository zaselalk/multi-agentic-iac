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
                   severity: str = "error", fix_hint: str = "") -> Dict[str, Any]:
    """
    The machine-readable form a repair is derived from.

    `node_id` is what makes this different from MACOG's counterexamples: it
    addresses the failure to a canvas node, so the same object drives both the
    Error-to-Edit mapping and the visual overlay the human sees.
    """
    return {
        "node_id": node_id or "",
        "type": type_,
        "rule": rule,
        "message": message,
        "severity": severity,
        "fix_hint": fix_hint,
    }
