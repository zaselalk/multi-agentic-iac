"""
The Error-to-Edit mapper (MACOG S4.6, Eq. 12).

    E : CE -> delta,  delta in A(CE)

MACOG routes a counterexample to an admissible edit, preferring plan-level
edits for structural violations and field-level patches for local ones, and
maintains a partial order over edits so the loop converges instead of
oscillating.

This implements the routing decision - which counterexamples are worth another
model round, which need a human, and which the loop cannot make progress on -
without yet implementing the deterministic edits themselves. Every repair here
goes back through the Architect. See docs/RESEARCH-GAPS.md: the deterministic
half is where the loop stops depending on the model for mechanical fixes.
"""

from typing import Any, Dict, List, Optional, Tuple

from ..intent import contradicts

# Ordered cheapest-to-fix first, which is also MACOG's preference for
# structural edits before field-level patches.
PRIORITY = {
    "round_trip": 0,
    "dag_cycle_detection": 0,
    "harmonization": 1,
    "schema_validation": 2,
    "policy_violation": 3,
    "deploy_error": 4,
    "cost_violation": 5,
}

# Failures no model round can clear, because the fix is outside the graph:
# the registry, the policy set or the price book has to change first.
#
# round_trip_equivalence is the sharpest case. The graph is not what is wrong -
# something the compiler emitted cannot be read back - so handing it to the
# Architect would have it edit a correct graph to work around a compiler
# defect, which is worse than reporting the defect.
NEEDS_HUMAN = {"registry_coverage", "round_trip_equivalence"}


class ErrorToEdit:
    name = "repair"

    def route(
        self,
        counterexamples: List[Dict[str, Any]],
        intended: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Split counterexamples into (repairable by the Architect, needs a human).

        Warnings are carried to the user but never trigger a repair round -
        spending a model call on a passed-through attribute the provider may
        well accept is how a repair loop starts oscillating.

        `intended` is every attribute somebody has actually asserted - drawn on
        the canvas, or written by the Architect acting on this request (see
        intent.py). A failure landing on one of those is escalated rather than
        repaired: the edit that would clear it is the edit that reverses a
        decision, and MACOG's admissible-edit set A(CE) has no member that both
        satisfies the validator and honours the intent. Every escalated
        counterexample is stamped with which of the two reasons it was.
        """
        intended = intended or {}
        repairable, escalate = [], []
        for ce in counterexamples:
            if ce.get("severity") != "error":
                continue
            if ce.get("rule") in NEEDS_HUMAN:
                escalate.append({**ce, "escalation": "needs_human"})
            elif contradicts(ce, intended):
                escalate.append({**ce, "escalation": "contradicts_intent"})
            else:
                repairable.append(ce)

        repairable.sort(key=lambda c: PRIORITY.get(c.get("type", ""), 99))
        return repairable, escalate

    @staticmethod
    def score(results: Dict[str, Dict[str, Any]]) -> float:
        """
        The routing objective J (MACOG Eq. 4), used only to decide whether the
        turn is done and to assert the loop is making progress.

        Weights follow the paper's ordering - a graph that will not compile is
        worse than one that compiles but violates a policy.
        """
        weights = {"schema": 4.0, "policy": 3.0, "deploy": 2.0, "cost": 1.0}
        total = 0.0
        for name, weight in weights.items():
            outcome = results.get(name, {})
            if outcome.get("status") == "fail":
                blocking = sum(
                    1 for c in outcome.get("counterexamples", [])
                    if c.get("severity") == "error"
                )
                total += weight * max(blocking, 1)
        return total
