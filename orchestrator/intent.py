"""
What the human actually asked for, and what to do when a rule says no.

MACOG's repair loop (S4.6, Algorithm 1) treats every counterexample the same
way: route it to an admissible edit and try again until J stops falling. That
is correct when the only author is an agent. It is wrong here, because one of
the authors is a person, and the loop cannot tell these two apart:

    the human asked for an unencrypted database, and a policy forbids it
    nobody mentioned encryption, and a policy requires it

The second is an omission and fixing it silently is a service. The first is a
contradiction, and fixing it silently means the system did the opposite of what
it was asked and said nothing - which is the failure this module exists to stop.

The distinction is drawn deterministically, with no extra model call:

    intent   = every desired_state key that is *there*. Either the human drew
               it on the canvas, or the Architect wrote it while acting on this
               turn's request. Both are statements someone made on purpose.
    omission = a failure about a key that is absent, or about no key at all - a
               missing companion resource, absent default tags, an unencrypted
               root volume nobody configured. These are the compiler's own
               invariants, and no one has an opinion about them to override.

Presence is the whole test, and it is a better test than asking the model what
it meant. `storage_encrypted: false` in a node is somebody's decision, whoever
made it and however long ago; no `storage_encrypted` key at all is nobody's.
That also makes the decision stick: refuse the offered fix once, and the value
stays in the graph, so the next unrelated turn will not quietly reverse it.

A contradiction is escalated to a breakpoint instead of repaired, and where the
violated rule names its own fix (see `patch` in validators/base.py) the fix is
offered as a diff the human can take or refuse. Offering is not applying: the
graph that gets stored is still the one the human asked for.

Limitation, deliberate and recorded: presence cannot distinguish a value the
human chose from one a default put there. It errs towards asking, which is the
safe direction - the cost is a question that did not need asking, and the cost
the other way is the system doing the opposite of what it was told.
"""

import copy
from typing import Any, Dict, List, Optional, Tuple

# Tools whose arguments carry an opinion about an attribute. delete_node is not
# here: it removes a node rather than asserting anything about its state, and
# it already raises a breakpoint of its own.
WRITE_TOOLS = {"create_node", "update_node"}


def from_trace(trace: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    node_id -> {attribute: value} the Architect set in response to the request.

    Only successful calls count. A rejected create_node asserts nothing about
    the graph, and treating its arguments as intent would hold the turn open
    over an attribute that was never written.
    """
    intended: Dict[str, Dict[str, Any]] = {}
    for call in trace:
        if call.get("tool") not in WRITE_TOOLS:
            continue
        result = call.get("result") or {}
        if result.get("status") != "success":
            continue
        arguments = call.get("arguments") or {}
        node_id = result.get("node_id") or arguments.get("node_id")
        state = arguments.get("desired_state")
        if not node_id or not isinstance(state, dict):
            continue
        intended.setdefault(node_id, {}).update(state)
    return intended


def from_graph(nodes: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    node_id -> {attribute: value} the graph already asserts.

    Everything in a node's desired_state got there because somebody put it
    there - the human on the canvas, or the agent on a previous turn that the
    human accepted by not objecting. A repair loop reversing any of it without
    saying so is the failure this module exists to prevent, so all of it counts
    as intent.
    """
    return {
        node["node_id"]: dict(node.get("desired_state") or {})
        for node in nodes
        if node.get("node_id")
    }


def merge(*maps: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Later maps win, per attribute."""
    merged: Dict[str, Dict[str, Any]] = {}
    for source in maps:
        for node_id, attributes in source.items():
            merged.setdefault(node_id, {}).update(attributes)
    return merged


def contradicts(ce: Dict[str, Any], intended: Dict[str, Dict[str, Any]]) -> bool:
    """
    Does this counterexample land on something the human asked for?

    Requires the validator to have named the attribute. A rule that does not
    say which key it is about cannot be matched against intent without guessing
    from its message, and a false positive here stops a turn that should have
    completed - so an unnamed attribute is treated as an omission.
    """
    attribute = ce.get("attribute") or ""
    if not attribute:
        return False
    return attribute in intended.get(ce.get("node_id") or "", {})


def split(
    counterexamples: List[Dict[str, Any]],
    intended: Dict[str, Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(contradicting the request, everything else), preserving order."""
    against, rest = [], []
    for ce in counterexamples:
        (against if contradicts(ce, intended) else rest).append(ce)
    return against, rest


# ---------------------------------------------------------
# THE OFFER
# ---------------------------------------------------------
def propose(
    nodes: List[Dict[str, Any]],
    counterexamples: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    The graph as it would be if every named fix were taken - not stored.

    Returns {"patch": [row, ...], "nodes": [...]} or None when nothing on offer.
    Each row is one attribute, with what it is now and what it would become, so
    the canvas can draw before -> after rather than a whole second graph the
    human has to diff by eye.
    """
    proposed = copy.deepcopy(nodes)
    index = {node.get("node_id"): node for node in proposed}
    rows: List[Dict[str, Any]] = []

    for ce in counterexamples:
        patch = ce.get("patch")
        node = index.get(ce.get("node_id") or "")
        if not isinstance(patch, dict) or node is None:
            continue
        state = node.setdefault("desired_state", {})
        for key, value in patch.items():
            before = state.get(key)
            if value is None:
                if key not in state:
                    continue
                state.pop(key)
            else:
                if before == value:
                    continue
                state[key] = value
            rows.append({
                "node_id": node["node_id"],
                "attribute": key,
                "current": before,
                # None means "remove this attribute", not "set it to null".
                "proposed": value,
                "rule": ce.get("rule", ""),
                "message": ce.get("message", ""),
                "severity": ce.get("severity", "error"),
                "fix_hint": ce.get("fix_hint", ""),
            })

    if not rows:
        return None
    return {"patch": rows, "nodes": proposed}


def apply_patch(
    nodes: List[Dict[str, Any]],
    rows: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Take an offer, against whatever the graph is now.

    Applied row by row against the current nodes rather than by storing the
    proposal's own node list, because the human may have edited something else
    while the offer sat on screen. Accepting a fix for one attribute must not
    roll the rest of the graph back to when the offer was made.

    Returns (patched nodes, ids of rows that no longer apply).
    """
    patched = copy.deepcopy(nodes)
    index = {node.get("node_id"): node for node in patched}
    stale: List[str] = []

    for row in rows:
        node = index.get(row.get("node_id"))
        if node is None:
            stale.append(f"{row.get('node_id')}.{row.get('attribute')}")
            continue
        state = node.setdefault("desired_state", {})
        key = row.get("attribute")
        if not key:
            continue
        if row.get("proposed") is None:
            state.pop(key, None)
        else:
            state[key] = row["proposed"]

    return patched, stale


# ---------------------------------------------------------
# SAYING SO
# ---------------------------------------------------------
# Why a turn's work was not written, in the words the human needs.
WITHHELD_COPY = {
    "concurrent_edit":
        "None of this has been applied yet - you changed the same nodes while "
        "I was working, so your version is what is on the canvas.",
    "destructive_edit":
        "Nothing has been deleted yet. Removing resources is not something I "
        "will do without being asked twice - approve it and I will.",
}


def compose_reply(
    reply: str,
    repaired: List[Dict[str, Any]],
    held: List[Dict[str, Any]],
    withheld: str = "",
) -> str:
    """
    Append what the turn actually did to what the agent said it would do.

    The Architect writes its reply before the validators run, so on its own it
    describes the plan rather than the outcome. When a repair round changed
    something afterwards, or a rule blocked what was asked for, that reply is
    not merely incomplete - it is wrong, and it is the last thing the human
    reads. This is deterministic text appended after the loop settles, which is
    the only point at which the outcome is known.
    """
    parts = [reply.strip()] if reply.strip() else []

    if withheld:
        parts.append(WITHHELD_COPY.get(
            withheld, "None of this has been applied yet."
        ))

    if repaired:
        rules = sorted({c.get("rule") or c.get("type") or "a check" for c in repaired})
        parts.append(
            "I also adjusted things you did not ask about, to clear "
            + _join(rules)
            + "."
        )

    for ce in held:
        node = ce.get("node_id") or "the graph"
        parts.append(
            f"I have left {node} as you asked, but {ce.get('rule') or 'a policy'} "
            f"rejects it: {ce.get('message', '').rstrip('.')}. "
            + (
                f"{ce.get('fix_hint').rstrip('.')} - take that fix, or keep what you asked for."
                if ce.get("fix_hint")
                else "Decide which way you want it."
            )
        )

    return " ".join(parts).strip()


def _join(items: List[str]) -> str:
    items = list(items)
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]
