"""
The evidence ledger.

This is where this system parts company with MACOG (Khan et al. 2025, S4.7).

MACOG coordinates through a shared blackboard: every agent reads and writes
one artifact store, and an agent learns what another agent did by looking it
up there. The blackboard is the communication medium.

Here it is not. Coordination happens through the schema instance held by the
MCP server - `set_graph` puts the canvas there, `get_graph` reads back what an
agent changed, and the controller re-reads it from MCP rather than from this
file precisely because MCP holds the one canonical, schema-validated graph
while this holds undifferentiated history. Agents receive typed arguments and
return typed results; none of them is given a ledger, and none of them reads
one.

So this class is append-only by design, not by accident: it is written to and
never consulted. What it records is what the schema instance cannot carry -
order, authorship and timing:

- `author` can be `human`, not just an agent name. A canvas edit is a
  first-class ledger entry, which is what makes a conflict between a human
  change and an agent-known policy expressible at all.
- `bundle()` emits the proof-carrying evidence bundle (S4.9) for the turn,
  which is the thing the canvas renders as its audit trail.
- `listener` reports entries as they are made, so a turn can be watched while
  it runs rather than only read afterwards.

A schema instance says what *is*. This says who decided it, and when. Keeping
MACOG's evidence discipline while replacing its coordination substrate is the
point, so the S4.9 bundle format is deliberately unchanged.

It is in-memory and per-turn. Anything that must outlive the turn is persisted
by projects.py.
"""

import hashlib
import json
import time
from typing import Any, Callable, Dict, List, Optional

# Who may write to the ledger. "human" is not in MACOG; it is the
# addition this research makes.
AUTHORS = {
    "human",
    "orchestrator",
    "architect",
    "harmonizer",
    "engineer",
    "reviewer",
    "prover",
    "planner",
    "devops",
    "curator",
}


def digest(payload: Any) -> str:
    """Stable content hash of an artifact, for reproducibility stamps."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


class EvidenceLedger:
    def __init__(
        self,
        session_id: str,
        intent: str = "",
        author: str = "human",
        listener: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ):
        self.session_id = session_id
        self.intent = intent
        self.origin = author
        self.started_at = time.time()
        self.entries: List[Dict[str, Any]] = []
        self.state_log: List[str] = []
        self.breakpoints: List[Dict[str, Any]] = []
        # Called as writes happen, so a caller can watch the turn instead of
        # waiting for it. The bundle at the end is unchanged either way: this
        # reports the same record as it is being made, and never alters it.
        self.listener = listener

    def _emit(self, event: str, data: Dict[str, Any]) -> None:
        """
        Tell the listener, and never let it break the turn.

        A subscriber that raises - a closed connection, a full queue - must not
        take down the run producing the work. The ledger is the record of the
        turn; delivering it is strictly secondary to making it.
        """
        if self.listener is None:
            return
        try:
            self.listener(event, data)
        except Exception:
            pass

    # -----------------------------------------------------
    # WRITING
    # -----------------------------------------------------
    def write(self, kind: str, author: str, payload: Any, **meta) -> Dict[str, Any]:
        """
        Record one artifact.

        `kind` is the artifact class - graph, terraform_ir, hcl, diagnostics,
        policy_trace, cost_sheet, deploy_log, counterexample, edit, motif.
        """
        if author not in AUTHORS:
            raise ValueError(f"unknown ledger author {author!r}")
        entry = {
            "seq": len(self.entries),
            "kind": kind,
            "author": author,
            "at": round(time.time() - self.started_at, 3),
            "digest": digest(payload),
            "payload": payload,
            **meta,
        }
        self.entries.append(entry)
        # Payload is deliberately not sent: a live watcher gets the same
        # metadata the evidence bundle carries, not a second copy of every
        # artifact streamed over the wire.
        self._emit("write", {k: v for k, v in entry.items() if k != "payload"})
        return entry

    def enter_state(self, state: str):
        self.state_log.append(state)
        self._emit("state", {
            "state": state,
            "at": round(time.time() - self.started_at, 3),
        })

    def breakpoint(self, reason: str, detail: Dict[str, Any]):
        """
        An agentic breakpoint: the run stops and waits for a human.

        MACOG names targeted human-in-the-loop checkpoints as future work; in
        this system they are a normal control-flow outcome, so they are
        recorded on the ledger like any other artifact.
        """
        record = {"reason": reason, "detail": detail, "at": round(time.time() - self.started_at, 3)}
        self.breakpoints.append(record)
        self.write("breakpoint", "orchestrator", record)
        return record

    # -----------------------------------------------------
    # READING - private, and there is exactly one reader
    # -----------------------------------------------------
    # Nothing outside this class reads the ledger. That is the architectural
    # claim, so it is enforced here rather than left to habit: the only lookup
    # is private and the only caller is bundle(). An agent that needs an
    # artifact is handed it, or reads the graph from MCP.
    #
    # Public `all_of()` and `counterexamples()` used to live here. Both were
    # dead - the remains of a read channel from when this was a blackboard -
    # and are removed rather than kept against a future that would contradict
    # the design.
    def _latest(self, kind: str) -> Optional[Any]:
        for entry in reversed(self.entries):
            if entry["kind"] == kind:
                return entry["payload"]
        return None

    # -----------------------------------------------------
    # EVIDENCE BUNDLE
    # -----------------------------------------------------
    def bundle(self) -> Dict[str, Any]:
        """
        The proof-carrying bundle for this turn (MACOG S4.9).

        Payloads are dropped in favour of hashes: this is the audit trail, not
        a second copy of the artifacts. The canvas renders it as the record of
        why the turn ended the way it did.
        """
        return {
            "session_id": self.session_id,
            "intent": self.intent,
            "states": self.state_log,
            "duration_s": round(time.time() - self.started_at, 3),
            "breakpoints": self.breakpoints,
            "trail": [
                {k: v for k, v in entry.items() if k != "payload"}
                for entry in self.entries
            ],
            "validators": {
                name: (self._latest(f"{name}_result") or {}).get("status", "not_run")
                for name in ("schema", "policy", "cost", "deploy")
            },
        }
