"""
Memory Curator - verified visual motifs.

MACOG stores verified tuples (P, T, Pi) and serves typed motifs back to the
Architect so a plan matching a known-good structure is seeded rather than
re-derived. Its ablation is the mildest of the eight (74.02 -> 72.17 on
IaC-Eval), which is why it was the last thing built here.

For this research it carries more weight than it does for MACOG, because the
motifs are *visual*. A motif here is a subgraph **plus its layout**, so reusing
one restores the arrangement the human recognises rather than only the
resources. That is the "Verified Visual Motifs" line in the proposal.

Three rules this implementation keeps:

- **Typed fragments, never raw HCL** (MACOG S4.10). A motif carries nodes -
  resource kinds, desired_state keys, positions. The compiled HCL is kept only
  as a digest, as a fingerprint of what was verified, never as text to be
  pasted back. HCL ages with the provider; a graph does not.
- **Only verified turns are stored.** A motif is written when a turn reaches
  `done` with no counterexamples and no breakpoints. Anything less is a guess,
  and a library of guesses is worse than an empty one.
- **Retrieval suggests, it never edits.** Motifs reach the Architect as
  context. Every edit that results still goes through harmonize, validate and
  the ordinary breakpoint flow.

What this is *not*: the seeded-fault benchmark runs with `intent=""` and so
never enters the `plan` state, which is the only place `retrieve()` is called.
A `- Memory Curator` row in `benchmark/RESULTS.md` would therefore measure
nothing. Its effect is on planning quality, which needs the A3/A4 protocol -
see docs/FUTURE-WORK.md.
"""

import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..ledger import digest

MOTIF_DIR = os.environ.get(
    "VISOR_MOTIF_DIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".visor", "motifs")),
)

# How many motifs to hand the Architect. More than a few stops being context
# and starts being noise that crowds out the actual request.
MAX_RETURNED = 3
# A motif must share this much of its shape with the current graph to be worth
# offering. Below it, "related" is doing no work.
MIN_SCORE = 0.25
# Intents kept per motif, newest last - evidence of what this shape was asked
# for, not an unbounded log.
MAX_INTENTS = 5


def _kinds(nodes: List[Dict[str, Any]]) -> List[str]:
    return sorted(str(n.get("resource") or "") for n in nodes if n.get("resource"))


def _edges(nodes: List[Dict[str, Any]]) -> List[str]:
    """
    The edge multiset, in resource-kind space rather than node-id space.

    This is what makes the key structural: two graphs that wire a subnet to a
    VPC match whether the nodes are called `web`/`main` or `a`/`b`.
    """
    resource_of = {n.get("node_id"): str(n.get("resource") or "") for n in nodes}
    pairs = []
    for node in nodes:
        target = str(node.get("resource") or "")
        for dep in node.get("depends_on") or []:
            source = resource_of.get(dep)
            if source and target:
                pairs.append(f"{source}->{target}")
    return sorted(pairs)


class MemoryCurator:
    name = "curator"

    def __init__(self, directory: str = MOTIF_DIR):
        self.directory = directory
        self._lock = threading.Lock()

    # -----------------------------------------------------
    # THE KEY
    # -----------------------------------------------------
    @staticmethod
    def shape_key(nodes: List[Dict[str, Any]]) -> str:
        """
        The structural key motifs are indexed by.

        Kinds and edges, both canonicalised and both in resource-kind space, so
        "VPC + 2 subnets + ALB" retrieves regardless of what anything is named.
        Readable on purpose: this string appears in the ledger and in stored
        motifs, and an opaque hash would make a wrong match impossible to
        diagnose.
        """
        return ",".join(_kinds(nodes)) + "#" + ",".join(_edges(nodes))

    # -----------------------------------------------------
    # RETRIEVAL
    # -----------------------------------------------------
    def retrieve(self, nodes: List[Dict[str, Any]], intent: str) -> List[Dict[str, Any]]:
        """
        Verified motifs worth showing the Architect for this graph and request.

        Scored on two signals, because either alone is misleading: shape
        overlap with what is already on the canvas, and word overlap with what
        is being asked for. A graph that looks like a stored motif is relevant;
        so is a request phrased like one that produced it.
        """
        stored = self._load_all()
        if not stored:
            return []

        want_kinds = set(_kinds(nodes))
        want_edges = set(_edges(nodes))
        words = _words(intent)

        scored: List[Tuple[float, Dict[str, Any]]] = []
        for motif in stored:
            text = max(
                (_overlap(words, _words(past)) for past in motif.get("intents") or []),
                default=0.0,
            )
            if want_kinds:
                score = (
                    _overlap(want_kinds, set(motif.get("kinds") or [])) * 0.6
                    + _overlap(want_edges, set(motif.get("edges") or [])) * 0.2
                    + text * 0.2
                )
            else:
                # Nothing on the canvas to compare a shape against, so the
                # request is the only signal there is. Weighting shape at 0.6
                # here would make motifs unreachable from an empty canvas -
                # which is the case they exist for: seeding a new design from
                # a structure already known to pass.
                score = text
            score = round(score, 3)
            if score >= MIN_SCORE:
                scored.append((score, _as_fragment(motif, score)))

        scored.sort(key=lambda pair: (-pair[0], pair[1]["shape_key"]))
        return [fragment for _, fragment in scored[:MAX_RETURNED]]

    # -----------------------------------------------------
    # STORAGE
    # -----------------------------------------------------
    def store(self, nodes: List[Dict[str, Any]], compiled: Dict[str, Any],
              bundle: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Record a fully-validated turn as a reusable motif.

        The caller already checks there were no counterexamples and no
        breakpoints; this checks the bundle agrees, because `store` is the one
        place a bad motif becomes permanent. A validator that was skipped is
        not a validator that passed, but skipping is a configuration choice
        rather than a fault - so a skipped validator is allowed and recorded,
        and a failed one is refused.
        """
        if not nodes:
            return None
        if any(status == "fail" for status in (bundle.get("validators") or {}).values()):
            return None
        if bundle.get("breakpoints"):
            return None

        key = self.shape_key(nodes)
        if key == "#":
            return None

        with self._lock:
            os.makedirs(self.directory, exist_ok=True)
            path = self._path(key)
            record = _read(path) or {
                "shape_key": key,
                "kinds": _kinds(nodes),
                "edges": _edges(nodes),
                "intents": [],
                "times_verified": 0,
                "first_stored_at": _now(),
            }
            # The newest verified layout wins: a motif is a suggestion, and the
            # most recently proved arrangement is the better suggestion.
            resource_of = {n.get("node_id"): str(n.get("resource") or "") for n in nodes}
            record["nodes"] = [_typed(n, resource_of) for n in nodes]
            record["hcl_digest"] = digest(compiled.get("hcl", ""))
            record["validators"] = bundle.get("validators") or {}
            record["times_verified"] = int(record.get("times_verified", 0)) + 1
            record["last_stored_at"] = _now()
            intent = (bundle.get("intent") or "").strip()
            if intent and intent not in record["intents"]:
                record["intents"] = (record["intents"] + [intent])[-MAX_INTENTS:]
            _write(path, record)
            return record

    # -----------------------------------------------------
    def _path(self, key: str) -> str:
        return os.path.join(self.directory, f"{digest(key)}.json")

    def _load_all(self) -> List[Dict[str, Any]]:
        if not os.path.isdir(self.directory):
            return []
        out = []
        for name in sorted(os.listdir(self.directory)):
            if not re.fullmatch(r"[0-9a-f]{16}\.json", name):
                continue
            record = _read(os.path.join(self.directory, name))
            if record:
                out.append(record)
        return out


# =========================================================
# helpers
# =========================================================
def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _words(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2}


def _overlap(a: set, b: set) -> float:
    """Jaccard. Two empty sets overlap in nothing, not in everything."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _typed(node: Dict[str, Any], resource_of: Dict[str, str]) -> Dict[str, Any]:
    """
    One node, reduced to what a motif is allowed to carry.

    Layout is kept - it is half of what makes the motif visual. Values inside
    `desired_state` are kept because a verified motif's settings are the point
    (an encrypted bucket's motif is worth nothing without the encryption), but
    identifiers are not: `node_id` and `tf_name` belong to the graph that was
    stored, not to the one being planned.

    Nesting has to survive that stripping, so `parent_id` is rewritten to the
    parent's *resource kind*. A motif saying "nested in vpc" is a template;
    one saying "nested in v1" is a dangling reference to a graph nobody has.
    """
    view = node.get("view") or {}
    parent = view.get("parent_id")
    return {
        "resource": node.get("resource"),
        "provider": node.get("provider", "aws"),
        "desired_state": node.get("desired_state") or {},
        "view": {
            "position": view.get("position"),
            "parent": resource_of.get(parent) if parent else None,
        },
    }


def _as_fragment(motif: Dict[str, Any], score: float) -> Dict[str, Any]:
    """What retrieval hands back: typed, scored, and free of HCL."""
    return {
        "shape_key": motif.get("shape_key", ""),
        "kinds": motif.get("kinds") or [],
        "edges": motif.get("edges") or [],
        "nodes": motif.get("nodes") or [],
        "times_verified": motif.get("times_verified", 0),
        "intents": motif.get("intents") or [],
        "score": score,
    }


def _read(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        # A motif is a cache of something already proved. A corrupt or missing
        # one costs a suggestion, never a turn.
        return None


def _write(path: str, record: Dict[str, Any]) -> None:
    # Write-then-replace, as projects.py does: a crash mid-save must not leave
    # a truncated motif that then fails to parse forever.
    handle, temp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(handle, "w") as f:
            json.dump(record, f, indent=2)
        os.replace(temp, path)
    except BaseException:
        if os.path.exists(temp):
            os.unlink(temp)
        raise
