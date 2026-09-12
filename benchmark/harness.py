"""
Running one case and scoring it, with no model and no judgement.

Two decisions here shape every number this benchmark produces, and both are
consequences of what the system is rather than conveniences.

**The Architect is stubbed.** A real model round would make the results
non-reproducible, cost money, and measure the model rather than the
architecture. The stub accepts a repair request, changes nothing, and counts
itself. That turns "how often did the loop reach for a model" into a *reported
number* instead of a hidden cost - and on this system that number is
interesting, because most of the loop is deterministic.

**Repair rate is reported as `remediated`, and it is not MACOG's quantity.**
MACOG repairs every counterexample it can reach. This system does not, on
purpose: a fault injected into a graph is, by the presence rule in
`orchestrator/intent.py`, something *somebody asked for*, so it is held and its
fix offered rather than applied. Measuring "was it silently fixed" would score
the system down for its central design decision. `remediated` therefore means
**fixed, or a concrete fix offered** - and `nodes_touched` is reported beside
it, because "offered and changed nothing" is the claim being tested.
"""

import copy
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from orchestrator.mcp_client import MCPClient
from orchestrator.state_machine import Orchestrator
from orchestrator.validators.base import result as validator_result

from .corpus import SETTINGS, clone
from .faults import FAULTS, VALIDATOR


# =========================================================
# STUBS
# =========================================================
class StubArchitect:
    """Accepts a repair request, changes nothing, and counts itself."""

    name = "architect"

    def __init__(self):
        self.plans = 0
        self.repairs = 0

    def plan(self, intent, session_id, knowledge=""):
        self.plans += 1
        return {"reply": "", "trace": [], "truncated": False}

    def repair(self, counterexamples, session_id):
        self.repairs += 1
        return {"reply": "", "trace": [], "truncated": False}


class _Counted:
    """The real Architect, wearing the stub's counter so both runs report alike."""

    name = "architect"

    def __init__(self, architect):
        self._architect = architect
        self.plans = 0
        self.repairs = 0

    def plan(self, intent, session_id, knowledge=""):
        self.plans += 1
        return self._architect.plan(intent, session_id, knowledge)

    def repair(self, counterexamples, session_id):
        self.repairs += 1
        return self._architect.repair(counterexamples, session_id)


class SilentHarmonizer:
    """The `- Harmonizer` ablation row."""

    name = "harmonizer"

    def run(self, nodes, settings=None):
        return {"pinning": {}, "counterexamples": []}


class SilentValidator:
    """A validator turned off for an ablation, reported as skipped not passed."""

    def __init__(self, name: str):
        self.name = name

    def run(self, compiled, **_):
        return validator_result(self.name, "skipped", reason="ablated for this run.")

    def availability(self):
        return {"available": False, "reason": "ablated."}


# =========================================================
# CONFIGURATION
# =========================================================
@dataclass(frozen=True)
class Config:
    """One row of the ablation table."""
    name: str = "full"
    prover: bool = True
    deploy: bool = True
    harmonizer: bool = True
    repair: bool = True


ABLATIONS: List[Config] = [
    Config("full"),
    Config("- prover", prover=False),
    Config("- devops", deploy=False),
    Config("- harmonizer", harmonizer=False),
    Config("- repair", repair=False),
]


# =========================================================
# THE RUNNER
# =========================================================
@dataclass
class Runner:
    mcp: MCPClient = field(default_factory=MCPClient)
    orchestrator: Optional[Orchestrator] = None
    architect: Any = field(default_factory=StubArchitect)
    # Opt-in. The default run is deterministic, free and reproducible; a real
    # Architect is none of those, and it measures the model rather than the
    # architecture. It is here because `repair rate` cannot be measured without
    # one, and leaving the metric unmeasurable would be worse than making the
    # run cost something on request.
    use_model: bool = False
    model: str = ""
    _baselines: Dict[str, Set[tuple]] = field(default_factory=dict)

    def __enter__(self):
        self.mcp.start()
        # No chat client by default: nothing here calls a model, and passing
        # one would invite something to.
        self.orchestrator = Orchestrator(self.mcp, None, "")
        if self.use_model:
            from orchestrator import llm
            from orchestrator.agents.architect import Architect
            self.model = llm.DEFAULT_MODEL
            self.architect = _Counted(
                Architect(self.mcp, llm.setup_client(), self.model)
            )
        self.orchestrator.architect = self.architect
        self._live = {
            "policy": self.orchestrator.validators["policy"],
            "harmonizer": self.orchestrator.harmonizer,
        }
        return self

    def __exit__(self, *_):
        self.mcp.stop()

    # -----------------------------------------------------
    def _apply(self, config: Config):
        self.orchestrator.validators["policy"] = (
            self._live["policy"] if config.prover else SilentValidator("policy")
        )
        self.orchestrator.harmonizer = (
            self._live["harmonizer"] if config.harmonizer else SilentHarmonizer()
        )

    def _run(self, graph, settings, session_id, config: Config, deploy: bool):
        self._apply(config)
        return self.orchestrator.run(
            intent="",
            nodes=list(graph.values()),
            session_id=session_id,
            settings=settings,
            deploy_validation=deploy and config.deploy,
            repair=config.repair,
        )

    # -----------------------------------------------------
    def baseline(self, graph_name: str, config: Config, deploy: bool) -> Dict[str, Any]:
        """
        The clean graph, unmodified.

        Two jobs. It is the false-positive measurement - a base graph that
        reports anything makes every number measured against it the sum of two
        effects. And its findings are subtracted from the faulted run, so
        `collateral` counts alarms the *fault* caused rather than ones that
        were always there.
        """
        key = f"{graph_name}|{config.name}|{deploy}"
        graph = clone(graph_name)
        outcome = self._run(
            graph, copy.deepcopy(SETTINGS), f"bench-base-{key}", config, deploy
        )
        errors = _errors(outcome["initial_counterexamples"])
        self._baselines[key] = {_identity(c) for c in errors}
        return {
            "graph": graph_name,
            "config": config.name,
            "clean": not errors,
            "findings": [c["rule"] or c["type"] for c in errors],
            "score": outcome["score"],
        }

    # -----------------------------------------------------
    def case(self, fault_name: str, graph_name: str, config: Config) -> Optional[Dict[str, Any]]:
        """One fault in one graph under one configuration, scored."""
        graph = clone(graph_name)
        settings = copy.deepcopy(SETTINGS)
        expected = FAULTS[fault_name](graph, settings)
        if expected is None:
            return None  # this fault does not apply to this shape

        deploy = bool(expected.get("needs_plan"))
        key = f"{graph_name}|{config.name}|{deploy}"
        if key not in self._baselines:
            self.baseline(graph_name, config, deploy)

        before = getattr(self.architect, "repairs", 0)
        outcome = self._run(
            graph, settings, f"bench-{fault_name}-{key}", config, deploy
        )
        # Detection is scored on the *first* pass, before the repair loop had a
        # chance to clear anything. Scoring it on the final list marks a
        # successful repair as a failure to detect, which is what this harness
        # did until the first --model run made the mistake visible.
        found = _errors(outcome["initial_counterexamples"])
        remaining = _errors(outcome["counterexamples"])

        hits = [c for c in found if _matches(c, expected)]
        detected = bool(hits)
        attributed = _attribution(hits, expected)
        offered = _offered(outcome.get("proposal"), expected)
        # Silently fixed: it was found, and by the end it is gone.
        repaired = detected and not any(_matches(c, expected) for c in remaining)

        return {
            "fault": fault_name,
            "graph": graph_name,
            "config": config.name,
            "validator": VALIDATOR[fault_name],
            "needs_plan": deploy,
            "detected": detected,
            # None where the fault belongs to no node - a project-level
            # setting has nothing on the canvas to point at.
            "attributed": attributed,
            "offered": offered,
            "repaired": repaired,
            "remediated": offered or repaired,
            # Everything the fault set off that the clean graph did not.
            "collateral": sorted(
                {c["rule"] or c["type"] for c in found
                 if not _matches(c, expected)
                 and _identity(c) not in self._baselines[key]}
            ),
            # Nodes whose desired_state the system changed. The presence rule
            # says this should be zero for every injected fault; measuring it
            # is how that stops being an assertion.
            "nodes_touched": _touched(graph, outcome["graph"]),
            # Which nodes the fault was injected into, so minimality can be
            # read as "changed beyond the one that was broken".
            "faulted": sorted(expected.get("node") or []),
            "model_rounds": getattr(self.architect, "repairs", 0) - before,
            "score": outcome["score"],
        }


# =========================================================
# SCORING
# =========================================================
def _errors(counterexamples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [c for c in counterexamples if c.get("severity") == "error"]


def _identity(counterexample: Dict[str, Any]) -> tuple:
    return (
        counterexample.get("node_id", ""),
        counterexample.get("rule", ""),
        counterexample.get("type", ""),
    )


def _matches(counterexample: Dict[str, Any], expected: Dict[str, Any]) -> bool:
    """Is this the finding the injected fault was supposed to produce?"""
    if expected.get("rule"):
        return counterexample.get("rule") == expected["rule"]
    return counterexample.get("type") == expected["type"]


def _attribution(hits: List[Dict[str, Any]], expected: Dict[str, Any]) -> Optional[bool]:
    """
    Did the finding name the right node? None when the fault has no node.

    A cycle is the one case where several node ids are correct, and the
    compiler names them all in a single comma-joined finding - so membership,
    not equality. Everywhere else equality is the test, or a finding naming
    two nodes would pass by accident.
    """
    if expected.get("node") is None or not hits:
        return None if expected.get("node") is None else False
    for hit in hits:
        named = hit.get("node_id", "")
        found = set(named.split(",")) if expected.get("cycle") else {named}
        if found & expected["node"]:
            return True
    return False


def _offered(proposal: Optional[Dict[str, Any]], expected: Dict[str, Any]) -> bool:
    """Was a concrete fix put on the table for the right node and attribute?"""
    rows = (proposal or {}).get("patch", [])
    wanted_nodes = expected.get("node") or set()
    attribute = expected.get("attribute", "")
    return any(
        row.get("node_id") in wanted_nodes and (not attribute or row.get("attribute") == attribute)
        for row in rows
    )


def _semantic(entry: Dict[str, Any]) -> tuple:
    """The parts of a node that compile. Layout is not a change to anything."""
    return (
        entry.get("desired_state") or {},
        sorted(entry.get("depends_on") or []),
    )


def _touched(before: Dict[str, Dict[str, Any]], after: List[Dict[str, Any]]) -> List[str]:
    """
    Nodes the system changed during the turn.

    Dependencies count, not just attributes: repairing a cycle changes only
    `depends_on`, and a minimality measure that cannot see that would report
    zero for the one repair that did happen.
    """
    now = {n["node_id"]: _semantic(n) for n in after}
    changed = [
        node_id for node_id, entry in before.items()
        if node_id in now and now[node_id] != _semantic(entry)
    ]
    changed += [node_id for node_id in now if node_id not in before]
    return sorted(changed)
