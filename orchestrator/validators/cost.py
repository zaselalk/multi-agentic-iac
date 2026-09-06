"""
v_cost - the Cost and Capacity Planner. NOT IMPLEMENTED.

This is a deliberate stub with a settled interface, not an oversight. MACOG
computes deterministic estimates from pinned price catalogues; doing that
honestly needs a versioned price book (region x instance family x storage
class), and inventing numbers would be worse than reporting nothing - a cost
figure nobody can trace is exactly the kind of evidence a proof-carrying
bundle is supposed to exclude.

To implement:

1. Add `price_book.json`: {"<terraform_type>": {"<region>": {"<sku>": <usd_per_month>}}},
   stamped with the catalogue date it was pulled from, so a run is reproducible.
2. Fill in `estimate()` below - walk `compiled["terraform_ir"]["resources"]`,
   look each up, sum, and attach the line items as evidence.
3. Emit a `cost_violation` counterexample per resource when the total exceeds
   `settings["budget"]`, with the over-budget node named so the canvas can
   highlight it.

Until then this returns `skipped`, which the orchestrator reports as an
unproven obligation rather than a pass.
"""

from typing import Any, Dict

from .base import result


class CostValidator:
    name = "cost"

    def run(self, compiled: Dict[str, Any], settings: Dict[str, Any] = None, **_) -> Dict[str, Any]:
        return result(
            self.name, "skipped",
            reason="no price book configured; cost estimation is not implemented "
                   "(see orchestrator/validators/cost.py).",
        )

    def estimate(self, compiled: Dict[str, Any], region: str) -> Dict[str, Any]:
        """Per-resource line items and a total. Returns {} until a price book exists."""
        return {}


    def availability(self):
        return {"available": False, "reason": "not implemented: no price book configured."}
