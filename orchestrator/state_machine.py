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

The repair loop also differs. MACOG repairs every counterexample it can reach;
this one first asks whether the failure is a contradiction of what the human
asked for, and if it is, offers the fix instead of taking it. See intent.py.

The controller is deterministic. Only the `plan` and `repair` states call a
model, and both go through the Architect.
"""

import os
from typing import Any, Callable, Dict, List, Optional

from .agents.architect import Architect
from .agents.curator import MemoryCurator
from .agents.harmonizer import ProviderHarmonizer
from .agents.repair import ErrorToEdit
from .blackboard import Blackboard
from .conflict import (
    detect as detect_conflicts,
    diverged,
    merge as merge_graphs,
    mergeable,
    summarise as summarise_conflicts,
)
from .intent import (
    compose_reply,
    from_graph as intent_from_graph,
    from_trace as intent_from_trace,
    merge as merge_intent,
    propose,
)
from .validators import (
    ORDER as VALIDATOR_ORDER,
    CostValidator,
    DeployValidator,
    PolicyValidator,
    SchemaValidator,
    terraform,
)

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
        reread: Optional[Callable[[], List[Dict[str, Any]]]] = None,
        on_event: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """
        One turn. `nodes` are canonical nodes (see adapters.canvas_to_nodes).

        `approved=True` means the human has already accepted a breakpoint this
        turn would otherwise raise, so destructive edits proceed.

        `repair=False` makes the turn observation-only: validators run and
        report, but nothing calls a model and nothing edits the graph. That is
        what a human asking "is what I have drawn compliant?" needs - a repair
        loop would answer for a graph they never approved.

        `on_event(kind, data)` is called as the turn progresses - `state` when
        the machine enters one, `write` for every blackboard entry. It is for
        watching, not steering: nothing it does changes the outcome, and an
        exception from it is swallowed rather than failing the turn.

        `reread` returns the stored graph as it is *now*. A model turn takes
        seconds and the human is not idle for them, so the world may have moved
        underneath: without this the agent's result is written over whatever
        they saved meanwhile, and nobody is told it existed.
        """
        settings = settings or {}
        # `on_event` turns the turn into something watchable: the same states
        # and writes the bundle records, reported as they happen. It observes
        # only - a turn behaves identically with or without a subscriber.
        board = Blackboard(session_id, intent, listener=on_event)
        run_deploy = DEPLOY_VALIDATION if deploy_validation is None else deploy_validation

        # --- load: the human's canvas is authoritative at turn start --------
        board.enter_state("load")
        self.mcp.call_tool("set_graph", {"session_id": session_id, "nodes": nodes})
        board.write("graph", "human", nodes, count=len(nodes))

        # --- plan: intent -> graph edits ------------------------------------
        # What is already asserted on the canvas counts as asked for: the human
        # drew it, or accepted it on an earlier turn. See intent.py.
        intended: Dict[str, Dict[str, Any]] = intent_from_graph(nodes)

        reply, trace, truncated = "", [], False
        if intent.strip():
            board.enter_state("plan")
            motifs = self.curator.retrieve(nodes, intent)
            if motifs:
                board.write("motif", "curator", motifs)

            planned = self.architect.plan(intent, session_id, knowledge)
            reply, trace, truncated = planned["reply"], planned["trace"], planned["truncated"]
            board.write("edit", "architect", trace, truncated=truncated)

            # Plus the keys the Architect wrote acting on this request. A
            # validator objecting to any of these is objecting to something
            # somebody chose, not to something nobody thought about.
            intended = merge_intent(intended, intent_from_trace(trace))
            board.write("intent", "architect", intended, nodes=len(intended))

            # --- breakpoint: high-consequence edits wait for a human --------
            destructive = [c for c in trace if c["tool"] in DESTRUCTIVE_TOOLS]
            if destructive and not approved:
                board.enter_state("breakpoint")
                board.breakpoint(
                    "destructive_edit",
                    {
                        "tools": sorted({c["tool"] for c in destructive}),
                        "nodes": [c["arguments"].get("node_id") for c in destructive],
                        "message": "The agent wants to remove these. Nothing has "
                                   "been deleted - approve it, or say what to do instead.",
                    },
                )

        # --- harmonize: is the graph expressible before we compile it? ------
        board.enter_state("harmonize")
        current = self.mcp.call_tool("get_graph", {"session_id": session_id}).get("nodes", [])
        harmonized = self.harmonizer.run(current, settings)
        board.write("harmonization", "harmonizer", harmonized)

        # --- compile / review / prove / price / deploy ----------------------
        compiled, results = self._validate(session_id, settings, board, run_deploy)
        counterexamples = (
            harmonized["counterexamples"]
            + _round_trip_counterexamples(compiled)
            + _all_counterexamples(results)
        )
        # What was wrong before anything was done about it. The returned
        # `counterexamples` are what is *still* wrong at the end, and the two
        # are different questions: "did a validator catch this" is answered
        # here, "is it still broken" is answered there. Anything measuring
        # detection against the final list scores a successful repair as a
        # miss - which is exactly what the seeded-fault benchmark did until it
        # was run with a real Architect.
        initial = list(counterexamples)

        # --- repair: counterexample-guided, bounded -------------------------
        # Only failures the human did not ask for are repaired here. The rest
        # are escalated with a reason and dealt with after the loop.
        attempts = 0
        score = self.router.score(results)
        budget = MAX_REPAIR_ATTEMPTS if repair else 0
        escalated: List[Dict[str, Any]] = []
        cleared: List[Dict[str, Any]] = []

        while budget:
            repairable, escalated = self.router.route(counterexamples, intended)
            if not repairable or attempts >= budget:
                break

            board.enter_state("repair")
            attempts += 1
            patched = self.architect.repair(repairable, session_id)
            trace += patched["trace"]
            board.write("edit", "architect", patched["trace"], repair_attempt=attempts)

            compiled, results = self._validate(session_id, settings, board, run_deploy)
            current = self.mcp.call_tool("get_graph", {"session_id": session_id}).get("nodes", [])
            harmonized = self.harmonizer.run(current, settings)
            counterexamples = (
                harmonized["counterexamples"]
                + _round_trip_counterexamples(compiled)
                + _all_counterexamples(results)
            )

            # Which of the failures this round set out to fix are actually
            # gone. The reply says so afterwards; a silent fix the human is
            # never told about is only half an improvement on a silent
            # override.
            outstanding = {_identity(c) for c in counterexamples}
            cleared += [c for c in repairable if _identity(c) not in outstanding]

            # Algorithm 1 requires J to be non-increasing; if a repair made
            # things worse, stop rather than let the loop thrash.
            new_score = self.router.score(results)
            if new_score >= score and new_score > 0:
                board.write("counterexample", "orchestrator", counterexamples,
                            note="repair did not reduce J; loop stopped")
                break
            score = new_score

        # --- intent: a rule refusing what the human explicitly asked for ----
        # Not repaired, and not quietly accepted either. The graph keeps what
        # was asked for, the violation stays visible on the node, and where the
        # rule named its own fix that fix is offered as a diff.
        held = [c for c in escalated if c.get("escalation") == "contradicts_intent"]
        blocked = [c for c in escalated if c.get("escalation") == "needs_human"]
        proposal = propose(current, held) if held else None

        if held:
            board.write("counterexample", "orchestrator", held,
                        note="contradicts the request; held for a human")
            board.breakpoint("intent_conflict", {
                "nodes": sorted({c["node_id"] for c in held if c.get("node_id")}),
                "counterexamples": held,
                "patch": (proposal or {}).get("patch", []),
                "message": (
                    "You asked for something a policy rejects. What you asked "
                    "for is what is on the canvas - nothing has been changed "
                    "behind you."
                ),
            })
        if blocked:
            board.breakpoint("unrepairable", {
                "nodes": sorted({c["node_id"] for c in blocked if c.get("node_id")}),
                "counterexamples": blocked,
                "message": "These need a change outside the graph - the registry, "
                           "the policy set or the price book.",
            })

        # --- conflict: did the human edit while this turn was running? -----
        conflicts: List[Dict[str, Any]] = []
        resolution: Optional[List[Dict[str, Any]]] = None
        if reread is not None and intent.strip():
            board.enter_state("reconcile")
            latest = reread() or []
            board.write("graph", "human", latest, count=len(latest), when="turn_end")
            conflicts = detect_conflicts(nodes, latest, current)
            if not conflicts and diverged(nodes, latest):
                # The human changed something the agent never touched. Nobody
                # disagrees, so there is nothing to stop for - but the agent's
                # graph was built from the canvas as it was at turn start and
                # does not contain the change, so writing it would drop the
                # edit. Merge it back without asking.
                resolution = merge_graphs(nodes, latest, current)
                board.write("edit", "orchestrator", resolution, resolution="auto_merge")
            if conflicts:
                board.write("conflict", "orchestrator", conflicts)
                # Where every conflict is disjoint, the two edits compose and
                # the merge is what approval should apply - handing over the
                # agent's graph instead would discard the human's mid-turn edit,
                # which is the loss this whole path exists to prevent, arriving
                # one step later.
                if mergeable(conflicts):
                    resolution = merge_graphs(nodes, latest, current)
                    board.write("edit", "orchestrator", resolution, resolution="merge")
                if not approved:
                    board.breakpoint("concurrent_edit", {
                        "nodes": [c["node_id"] for c in conflicts],
                        "conflicts": conflicts,
                        "resolution": "merge_available" if mergeable(conflicts) else "human_required",
                        "message": summarise_conflicts(conflicts),
                    })

        # --- the reply, composed now that the outcome is known --------------
        # The Architect wrote its sentence in the plan state, before any
        # validator ran. On its own it describes an intention; this makes it
        # describe the result.
        # Work the human has not agreed to is not written, and the reply has to
        # say so - "I deleted the bucket" while the bucket is still there is the
        # same failure as a silent repair, wearing the opposite face.
        withheld = ""
        if not approved:
            if conflicts:
                withheld = "concurrent_edit"
            elif any(b["reason"] == "destructive_edit" for b in board.breakpoints):
                withheld = "destructive_edit"
        reply = compose_reply(reply, cleared, held, withheld=withheld)

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
            # equiv(P, decompile(compile(P))): whether the generated Terraform
            # still describes the graph it came from.
            "round_trip": compiled.get("round_trip", {}),
            "graph": current,
            "validators": results,
            "counterexamples": counterexamples,
            # The first pass, before any repair. See above.
            "initial_counterexamples": initial,
            "breakpoints": board.breakpoints,
            "conflicts": conflicts,
            # The human's graph with the agent's non-conflicting changes folded
            # in. Set whenever the human edited mid-turn and the two can be
            # composed; None when they cannot, or when nothing moved.
            "resolution": resolution,
            # A fix offered rather than applied: {"patch": [...], "nodes": [...]}.
            # None when nothing was held back. The nodes are what the graph
            # would become; the patch is the same thing attribute by attribute,
            # which is what the canvas draws.
            "proposal": proposal,
            # Why this turn's graph must not be written, or "" if it may be.
            # The caller does the storing, so the decision belongs here and the
            # test belongs in one place.
            "withheld": withheld,
            "repairs": attempts,
            "score": score,
            "bundle": board.bundle(),
        }

    # =====================================================
    def _validate(self, session_id, settings, board: Blackboard, run_deploy: bool):
        """compile -> deploy -> review -> prove -> price, recording each on the board."""
        board.enter_state("compile")
        compiled = self.mcp.call_tool(
            "compile_terraform", {"session_id": session_id, "settings": settings}
        )
        board.write("terraform_ir", "engineer", compiled.get("terraform_ir", {}))
        board.write("hcl", "engineer", compiled.get("hcl", ""))

        # --- equiv(P, decompile(compile(P))) - MACOG Eq. 11 ----------------
        # The direction that did not exist. Cheap enough to run on every
        # compile, and running it every time is the difference between "the
        # compiler preserves intent" as a claim and as something checked.
        compiled["round_trip"] = self.mcp.call_tool(
            "round_trip_check", {"session_id": session_id, "settings": settings}
        )
        board.write("round_trip", "engineer", compiled["round_trip"])

        # --- ground the graph against the provider, if asked ---------------
        # This runs before proving, which is not MACOG's order. The paper's
        # DevOps sandbox is a final gate; here the plan is an *input* to the
        # Security Prover, because a resolved `tags_all` or an expanded
        # provider default is exactly what the IR cannot carry. Proving after
        # grounding is the only order in which a plan-grounded policy exists.
        if run_deploy:
            board.enter_state("deploy")
            compiled["plan"] = self._ground(session_id, settings, compiled)
            board.write("deploy_log", "devops", _loggable(compiled["plan"]))

        states = {"schema": "review", "policy": "prove", "cost": "price", "deploy": "deploy"}
        authors = {"schema": "reviewer", "policy": "prover", "cost": "planner", "deploy": "devops"}

        results: Dict[str, Dict[str, Any]] = {}
        for name in VALIDATOR_ORDER:
            if name == "deploy" and not run_deploy:
                results[name] = {
                    "name": name, "status": "skipped", "counterexamples": [], "evidence": {},
                    "reason": "deploy validation is off for this turn "
                              "(set VISOR_DEPLOY_VALIDATION=1 or request verification).",
                }
            else:
                # Deploy's state was entered above, around the work itself;
                # re-entering it here would log a state the machine was not in.
                if name != "deploy":
                    board.enter_state(states[name])
                results[name] = self.validators[name].run(compiled, settings=settings)
            board.write(f"{name}_result", authors[name], results[name])

        return compiled, results

    def _ground(self, session_id, settings, compiled) -> Dict[str, Any]:
        """
        Compile a second time in plan mode, and run Terraform over it.

        Twice, because the HCL a human reads must not carry placeholder
        credentials and skip flags - those exist so `terraform plan` can run
        with no cloud account, and putting them in an export would be handing
        someone a configuration that quietly skips its own safety checks. Both
        forms come out of the same deterministic compiler; see
        `compiler.preamble.plan_mode` in schema.json.
        """
        plan_mode = self.mcp.call_tool("compile_terraform", {
            "session_id": session_id,
            "settings": {**(settings or {}), "plan_mode": True},
        })
        return terraform.normalise(terraform.ground(plan_mode.get("hcl", "")), compiled)


def _round_trip_counterexamples(compiled: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    A failed round trip, as findings the canvas can draw.

    Addressed to a node like every other counterexample, but never repairable:
    the graph is not what is wrong. Something the compiler emitted cannot be
    read back, which is a defect in the compiler or in a registry entry, and no
    edit to the user's graph will fix it. `round_trip_equivalence` is in
    NEEDS_HUMAN for exactly that reason.
    """
    outcome = compiled.get("round_trip") or {}
    if outcome.get("equivalent", True):
        return []
    return [
        {
            "node_id": difference.get("node_id", ""),
            "type": "round_trip",
            "rule": "round_trip_equivalence",
            "message": difference.get("message", ""),
            "severity": "error",
            "fix_hint": "The generated Terraform no longer describes the graph it came "
                        "from. Check the registry entry for this resource in "
                        "mcp-server/schema.json - a lost companion, static block or "
                        "attribute mapping is the usual cause.",
            "attribute": difference.get("attribute", ""),
            "patch": None,
        }
        for difference in outcome.get("differences", [])
    ]


def _loggable(artifact: Dict[str, Any]) -> Dict[str, Any]:
    """The plan artifact minus the parts nobody audits - stdout and per-resource
    values. The blackboard is the trail of what happened, not a second copy of
    the plan."""
    return {
        "status": artifact.get("status"),
        "stage": artifact.get("stage"),
        "reason": artifact.get("reason", ""),
        "terraform_version": artifact.get("terraform_version", ""),
        "summary": artifact.get("summary", {}),
        "resources": [
            {"address": r["address"], "node_id": r["node_id"], "actions": r["actions"]}
            for r in artifact.get("resources", [])
        ],
        "diagnostics": artifact.get("diagnostics", []),
    }


def _identity(counterexample: Dict[str, Any]) -> tuple:
    """Enough of a counterexample to recognise it again after a repair round."""
    return (
        counterexample.get("node_id", ""),
        counterexample.get("type", ""),
        counterexample.get("rule", ""),
        counterexample.get("message", ""),
    )


def _all_counterexamples(results: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    for outcome in results.values():
        found.extend(outcome.get("counterexamples", []))
    return found
