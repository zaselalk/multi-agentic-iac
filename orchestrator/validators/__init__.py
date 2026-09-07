"""
The validator family V (MACOG S4.1, Eq. 2).

    v(T, C) = (v_schema, v_policy, v_cost, v_deploy)

Each validator returns the same envelope so the orchestrator can score a turn
and route repairs without knowing which validator produced what:

    {
      "name":            "schema" | "policy" | "cost" | "deploy",
      "status":          "pass" | "fail" | "skipped",
      "reason":          why it was skipped, when it was,
      "counterexamples": [ ... ],
      "evidence":        raw tool output, for the proof bundle
    }

A counterexample is the machine-readable form a repair is derived from, and
the shape the canvas needs to draw the failure on the right node:

    {
      "node_id":  which canvas node is at fault ("" if none),
      "type":     schema_validation | policy_violation | cost_violation | deploy_error,
      "rule":     the policy/check identifier,
      "message":  human-readable,
      "severity": "error" | "warning",
      "fix_hint": what the repair should try, when known
    }

`skipped` is a first-class outcome, not a failure: a validator whose tool is
not installed must not silently read as a pass. The orchestrator surfaces
skipped validators in the evidence bundle so nobody mistakes an unproven
configuration for a proven one.
"""

from . import terraform
from .base import counterexample, result
from .cost import CostValidator
from .deploy import DeployValidator
from .policy import PolicyValidator
from .schema import SchemaValidator

__all__ = [
    "terraform",
    "SchemaValidator",
    "PolicyValidator",
    "CostValidator",
    "DeployValidator",
    "result",
    "counterexample",
]

# The order the orchestrator runs them in.
#
# Deploy is first, which is not MACOG's order and is deliberate. The paper runs
# the DevOps sandbox last, as a final gate. Here `terraform plan` produces an
# artifact the Security Prover reads - post-expansion values the IR cannot have
# - so proving has to come after grounding or a plan-grounded policy cannot
# exist at all. It is also the only one that can be skipped for cost, and
# knowing that early is what lets the rest report honestly about what was
# proven.
ORDER = ("deploy", "schema", "policy", "cost")

# What the canvas shows, which is a different question: cheapest and most
# localising first, so a reader meets a compile failure before a cost estimate.
DISPLAY_ORDER = ("schema", "policy", "cost", "deploy")
