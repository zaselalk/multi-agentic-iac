"""
Concurrent-edit detection.

schema.json declares

    "conflict_resolution": { "strategy": "human_in_the_loop",
                             "fallback": "agentic_merge_with_approval" }

and until now nothing implemented either. The canvas was unconditionally
authoritative at turn start and the agent's result was unconditionally written
at turn end, so a human edit landing *during* a turn was overwritten without
anyone being told it had existed.

That is the case this detects: three states, not two.

    base     the graph as the turn started
    human    the graph as stored now - a /graph save may have landed since
    agent    the graph the Architect produced from base

A node both sides changed is a conflict. A node only one side changed is not,
and is not worth stopping a turn for.

Two things are deliberately *not* conflicts:

- Layout. A human dragging a node while an agent edits its attributes has not
  disagreed with anything, so comparison is over `desired_state` and
  `depends_on` only - never `view`.
- Identical outcomes. If both sides made the same change, there is nothing to
  resolve.
"""

from typing import Any, Dict, List, Optional

from .blackboard import digest


def _semantic(node: Dict[str, Any]) -> Dict[str, Any]:
    """The parts of a node that compile. Position and style are not opinions."""
    return {
        "desired_state": node.get("desired_state") or {},
        "depends_on": sorted(node.get("depends_on") or []),
    }


def _by_id(nodes: Optional[List[Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    return {n["node_id"]: n for n in (nodes or []) if n.get("node_id")}


def _changed_attributes(before: Dict[str, Any], after: Dict[str, Any]) -> List[str]:
    a, b = (before or {}).get("desired_state", {}), (after or {}).get("desired_state", {})
    keys = sorted(set(a) | set(b))
    changed = [k for k in keys if a.get(k) != b.get(k)]
    if (before or {}).get("depends_on") != (after or {}).get("depends_on"):
        changed.append("depends_on")
    return changed


def detect(
    base: List[Dict[str, Any]],
    human: List[Dict[str, Any]],
    agent: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Nodes both the human and the agent changed away from `base`.

    Returns one record per conflicted node, naming what each side did and where
    they overlap, so a resolution UI has everything it needs without re-diffing.
    """
    b, h, a = _by_id(base), _by_id(human), _by_id(agent)

    conflicts: List[Dict[str, Any]] = []
    for node_id in sorted(set(h) | set(a)):
        was = _semantic(b[node_id]) if node_id in b else None
        now_h = _semantic(h[node_id]) if node_id in h else None
        now_a = _semantic(a[node_id]) if node_id in a else None

        human_touched = now_h != was
        agent_touched = now_a != was
        if not (human_touched and agent_touched):
            continue
        if now_h == now_a:
            # Both arrived at the same place. Nothing to resolve.
            continue

        human_changed = _changed_attributes(was, now_h)
        agent_changed = _changed_attributes(was, now_a)
        overlap = sorted(set(human_changed) & set(agent_changed))
        deleted = now_h is None or now_a is None

        conflicts.append({
            "node_id": node_id,
            "kind": _kind(was, now_h, now_a),
            # schema.json offers `agentic_merge_with_approval` as the fallback
            # to `human_in_the_loop`. This is the test for which applies: two
            # edits to the same node that touch no attribute in common are not
            # a disagreement, they are a merge. Two edits to the same attribute
            # are a disagreement, and no merge rule can settle it - only the
            # human knows which they meant.
            "resolution": "human_required" if (overlap or deleted) else "merge_available",
            "human": {"digest": digest(now_h), "changed": human_changed, "deleted": now_h is None},
            "agent": {"digest": digest(now_a), "changed": agent_changed, "deleted": now_a is None},
            # Where they actually disagree - the resolution UI's shortlist.
            "attributes": overlap,
        })
    return conflicts


def _kind(was, human, agent) -> str:
    if human is None and agent is None:
        return "both_deleted"
    if human is None:
        return "human_deleted_agent_modified"
    if agent is None:
        return "agent_deleted_human_modified"
    if was is None:
        return "both_created"
    return "both_modified"


def summarise(conflicts: List[Dict[str, Any]]) -> str:
    """One line for the breakpoint message."""
    if not conflicts:
        return ""
    nodes = ", ".join(c["node_id"] for c in conflicts[:3])
    more = f" and {len(conflicts) - 3} more" if len(conflicts) > 3 else ""
    return (
        f"You and the agent both changed {nodes}{more} during this turn. "
        f"Your version is kept; review the agent's before applying it."
    )


def mergeable(conflicts: List[Dict[str, Any]]) -> bool:
    """True when every conflict can be merged without discarding an edit."""
    return bool(conflicts) and all(
        c["resolution"] == "merge_available" for c in conflicts
    )


def merge(
    base: List[Dict[str, Any]],
    human: List[Dict[str, Any]],
    agent: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    The human's graph with the agent's non-conflicting changes folded in.

    Applying the agent's graph wholesale on approval would discard whatever the
    human changed mid-turn - which is the exact loss this whole path exists to
    prevent, arriving one step later. So the human's version is the base and
    only attributes they did not touch are taken from the agent.

    Nodes the agent created are added; nodes it deleted are not removed, since
    a deletion against a live human edit is `human_required` and never reaches
    here.
    """
    b, h, a = _by_id(base), _by_id(human), _by_id(agent)
    merged: List[Dict[str, Any]] = []

    for node_id, node in h.items():
        if node_id not in a:
            merged.append(node)
            continue

        was = (b.get(node_id) or {}).get("desired_state", {})
        mine = dict(node.get("desired_state") or {})
        theirs = (a[node_id].get("desired_state") or {})

        for key, value in theirs.items():
            # Take the agent's value only where the human left the attribute
            # as it was - never overwrite something they deliberately set.
            if mine.get(key) == was.get(key) and value != was.get(key):
                mine[key] = value

        node = dict(node)
        node["desired_state"] = mine
        if not node.get("depends_on") and a[node_id].get("depends_on"):
            node["depends_on"] = a[node_id]["depends_on"]
        merged.append(node)

    # Nodes the agent added during the turn.
    merged.extend(a[node_id] for node_id in a if node_id not in h)
    return merged
