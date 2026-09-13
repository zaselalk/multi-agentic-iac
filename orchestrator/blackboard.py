"""
The typed blackboard.

MACOG (Khan et al. 2025, S4.7) has every agent read and write one shared,
versioned artifact store rather than passing messages: I-IR versions, compiler
outputs, validator traces, deploy logs and policy proofs, each stamped with
content hashes so a run can be replayed and audited.

This is that store, for one turn. Two things differ from the paper, both
because a human is in the loop here rather than only at the end:

- Entries carry an `author` that can be `human`, not just an agent name. A
  canvas edit is a first-class blackboard write, which is what makes conflict
  detection between a human change and an agent-known policy expressible at
  all.
- `bundle()` emits the proof-carrying evidence bundle (S4.9) for the turn,
  which is the thing the canvas renders as its audit trail.

It is deliberately in-memory and per-turn. Anything that must outlive the turn
is persisted by projects.py.
"""

import hashlib
import json
import time
from typing import Any, Callable, Dict, List, Optional

# Who may write to the blackboard. "human" is not in MACOG; it is the
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


class Blackboard:
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
        take down the run producing the work. The blackboard is the record of
        the turn; delivering it is strictly secondary to making it.
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
            raise ValueError(f"unknown blackboard author {author!r}")
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
        recorded on the blackboard like any other artifact.
        """
        record = {"reason": reason, "detail": detail, "at": round(time.time() - self.started_at, 3)}
        self.breakpoints.append(record)
        self.write("breakpoint", "orchestrator", record)
        return record

    # -----------------------------------------------------
    # READING
    # -----------------------------------------------------
    def latest(self, kind: str) -> Optional[Any]:
        for entry in reversed(self.entries):
            if entry["kind"] == kind:
                return entry["payload"]
        return None

    def all_of(self, kind: str) -> List[Any]:
        return [e["payload"] for e in self.entries if e["kind"] == kind]

    def counterexamples(self) -> List[Dict[str, Any]]:
        """Every unresolved counterexample from the most recent validation pass."""
        return self.latest("counterexample") or []

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
                name: (self.latest(f"{name}_result") or {}).get("status", "not_run")
                for name in ("schema", "policy", "cost", "deploy")
            },
        }
