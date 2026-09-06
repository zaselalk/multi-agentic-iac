"""
The orchestrator: a deterministic controller over the blackboard.

MACOG (S4.7, Eq. 14) advances a finite-state machine

    S in {plan, harmonize, compile, review, prove, price, deploy, repair, done}

with transitions guarded by contract predicates, and runs the
counterexample-guided repair loop of Algorithm 1. This is that machine, with
two states the paper does not have:

    load        the human's canvas is written to the blackboard first, so the
                turn starts from what the human actually drew rather than from
                the agent's memory of it.

    breakpoint  a high-consequence edit stops the run and waits. MACOG lists
                targeted human-in-the-loop checkpoints as future work; here
                they are ordinary control flow, because the human is present
                for the whole turn rather than only at the end.

The controller is deterministic. Only the `plan` and `repair` states call a
model, and both go through the Architect.
"""

import os
from typing import Any, Dict, List, Optional

from .agents.architect import Architect
from .agents.curator import MemoryCurator
from .agents.harmonizer import ProviderHarmonizer
from .agents.repair import ErrorToEdit
from .blackboard import Blackboard
from .validators import CostValidator, DeployValidator, PolicyValidator, SchemaValidator

# Attempt budget K in Algorithm 1. Each attempt is one model round plus a full
# validator pass, so this bounds both latency and spend.
MAX_REPAIR_ATTEMPTS = int(os.environ.get("VISOR_MAX_REPAIRS", "2"))

# terraform init/validate adds seconds to a turn, so it is opt-in for
# interactive chat and always on for an explicit verification request.
DEPLOY_VALIDATION = os.environ.get("VISOR_DEPLOY_VALIDATION", "0") == "1"

# Tool calls that destroy something a human may not expect to lose. Hitting one
# of these is what raises an agentic breakpoint.
DESTRUCTIVE_TOOLS = {"delete_node"}


class Orchestrator:
    """One instance per process; `run` is one turn."""

    def __init__(self, mcp, chat_client, model: str):
        self.mcp = mcp
        self.architect = Architect(mcp, chat_client, model)
        self.harmonizer = ProviderHarmonizer()
        self.curator = MemoryCurator()
        self.router = ErrorToEdit()
        self.validators = {
            "schema": SchemaValidator(),
            "policy": PolicyValidator(),
            "cost": CostValidator(),
            "deploy": DeployValidator(),
        }

    # =====================================================
    def run(
        self,
        intent: str,
        nodes: List[Dict[str, Any]],
        session_id: str,
        settings: Optional[Dict[str, Any]] = None,
        knowledge: str = "",
        deploy_validation: Optional[bool] = None,
        approved: bool = False,
        repair: bool = True,
    ) -> Dict[str, Any]:
        """
        One turn. `nodes` are canonical nodes (see adapters.canvas_to_nodes).

        `approved=True` means the human has already accepted a breakpoint this
        turn would otherwise raise, so destructive edits proceed.

        `repair=False` makes the turn observation-only: validators run and
        report, but nothing calls a model and nothing edits the graph. That is
        what a human asking "is what I have drawn compliant?" needs - a repair
        loop would answer for a graph they never approved.
        """
        settings = settings or {}
        board = Blackboard(session_id, intent)
        run_deploy = DEPLOY_VALIDATION if deploy_validation is None else deploy_validation

        # --- load: the human's canvas is authoritative at turn start --------
        board.enter_state("load")
        self.mcp.call_tool("set_graph", {"session_id": session_id, "nodes": nodes})
        board.write("graph", "human", nodes, count=len(nodes))

        # --- plan: intent -> graph edits ------------------------------------
        reply, trace, truncated = "", [], False
        if intent.strip():
            board.enter_state("plan")
            motifs = self.curator.retrieve(nodes, intent)
            if motifs:
                board.write("motif", "curator", motifs)

            planned = self.architect.plan(intent, session_id, knowledge)
            reply, trace, truncated = planned["reply"], planned["trace"], planned["truncated"]
            board.write("edit", "architect", trace, truncated=truncated)

            # --- breakpoint: high-consequence edits wait for a human --------
            destructive = [c for c in trace if c["tool"] in DESTRUCTIVE_TOOLS]
            if destructive and not approved:
                board.enter_state("breakpoint")
                board.breakpoint(
                    "destructive_edit",
                    {
                        "tools": sorted({c["tool"] for c in destructive}),
                        "nodes": [c["arguments"].get("node_id") for c in destructive],
                        "message": "The agent deleted resources. Review before this is kept.",
                    },
                )

        # --- harmonize: is the graph expressible before we compile it? ------
        board.enter_state("harmonize")
        current = self.mcp.call_tool("get_graph", {"session_id": session_id}).get("nodes", [])
        harmonized = self.harmonizer.run(current, settings)
        board.write("harmonization", "harmonizer", harmonized)

        # --- compile / review / prove / price / deploy ----------------------
        compiled, results = self._validate(session_id, settings, board, run_deploy)
        counterexamples = harmonized["counterexamples"] + _all_counterexamples(results)

        # --- repair: counterexample-guided, bounded -------------------------
        attempts = 0
        score = self.router.score(results)
        budget = MAX_REPAIR_ATTEMPTS if repair else 0
        while attempts < budget:
            repairable, escalate = self.router.route(counterexamples)
            if escalate and not repairable:
                board.breakpoint("unrepairable", {"counterexamples": escalate})
            if not repairable:
                break

            board.enter_state("repair")
            attempts += 1
            patched = self.architect.repair(repairable, session_id)
            trace += patched["trace"]
            board.write("edit", "architect", patched["trace"], repair_attempt=attempts)

            compiled, results = self._validate(session_id, settings, board, run_deploy)
            current = self.mcp.call_tool("get_graph", {"session_id": session_id}).get("nodes", [])
            harmonized = self.harmonizer.run(current, settings)
            counterexamples = harmonized["counterexamples"] + _all_counterexamples(results)

            # Algorithm 1 requires J to be non-increasing; if a repair made
            # things worse, stop rather than let the loop thrash.
            new_score = self.router.score(results)
            if new_score >= score and new_score > 0:
                board.write("counterexample", "orchestrator", counterexamples,
                            note="repair did not reduce J; loop stopped")
                break
            score = new_score

        board.enter_state("done" if score == 0 else "unsatisfied")
        if not repair and score > 0:
            board.write("counterexample", "orchestrator", counterexamples,
                        note="observation-only run; no repair was attempted")
        board.write("counterexample", "orchestrator", counterexamples)

        if score == 0 and not board.breakpoints:
            self.curator.store(current, compiled, board.bundle())

        return {
            "reply": reply,
            "trace": trace,
            "truncated": truncated,
            "compiled": compiled,
            "graph": current,
            "validators": results,
            "counterexamples": counterexamples,
            "breakpoints": board.breakpoints,
            "repairs": attempts,
            "score": score,
            "bundle": board.bundle(),
        }

    # =====================================================
    def _validate(self, session_id, settings, board: Blackboard, run_deploy: bool):
        """compile -> review -> prove -> price -> deploy, recording each on the board."""
        board.enter_state("compile")
        compiled = self.mcp.call_tool(
            "compile_terraform", {"session_id": session_id, "settings": settings}
        )
        board.write("terraform_ir", "engineer", compiled.get("terraform_ir", {}))
        board.write("hcl", "engineer", compiled.get("hcl", ""))

        states = {"schema": "review", "policy": "prove", "cost": "price", "deploy": "deploy"}
        authors = {"schema": "reviewer", "policy": "prover", "cost": "planner", "deploy": "devops"}

        results: Dict[str, Dict[str, Any]] = {}
        for name, validator in self.validators.items():
            if name == "deploy" and not run_deploy:
                results[name] = {
                    "name": name, "status": "skipped", "counterexamples": [], "evidence": {},
                    "reason": "deploy validation is off for this turn "
                              "(set VISOR_DEPLOY_VALIDATION=1 or request verification).",
                }
            else:
                board.enter_state(states[name])
                results[name] = validator.run(compiled, settings=settings)
            board.write(f"{name}_result", authors[name], results[name])

        return compiled, results


def _all_counterexamples(results: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    for outcome in results.values():
        found.extend(outcome.get("counterexamples", []))
    return found
