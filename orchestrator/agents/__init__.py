"""
The agent roster, and how it maps onto MACOG's.

MACOG (Khan et al. 2025, S4.2) names eight roles around a blackboard. Not all
of them need to be an LLM here, and saying which are not is the point of this
file - a role implemented as deterministic code is a stronger result than the
same role implemented as a prompt, and pretending otherwise would overstate
what the system does.

| MACOG role            | Here                          | Kind          |
|-----------------------|-------------------------------|---------------|
| Architect             | agents/architect.py           | LLM           |
| Provider Harmonizer   | agents/harmonizer.py          | deterministic |
| Engineer              | mcp-server/compiler.py        | deterministic |
| Reviewer              | validators/schema.py          | deterministic |
| Security Prover       | validators/policy.py (OPA)    | deterministic |
| Cost & Capacity       | validators/cost.py            | NOT BUILT     |
| DevOps                | validators/deploy.py          | deterministic |
| Memory Curator        | agents/curator.py             | deterministic |
| Orchestrator          | state_machine.py              | deterministic |
| Blackboard            | ledger.py (see below)         | deterministic |
| -                     | agents/repair.py (Error->Edit)| deterministic |

Only the Architect calls a model. MACOG's Engineer needs grammar-constrained
decoding because it generates HCL text; here the compiler emits HCL from the
graph deterministically, so there is no decoding step to constrain and no
opportunity for the model to hallucinate a field. That is why the Engineer row
is a compiler and not a prompt.

MACOG's Blackboard row is the one that is not a like-for-like mapping. There,
the blackboard is how agents communicate: an agent learns what another did by
reading it. Here no agent reads it - coordination runs through the
schema instance held by the MCP server, and agents are handed typed arguments.
What `ledger.py` keeps is the evidence discipline: order, authorship, timing
and the S4.9 bundle. It is written to and never consulted. See its module
docstring.

The role MACOG does not have is the human. The canvas writes to the same
ledger the agents do (author `human`), which is what makes a conflict between
a human edit and an agent-known policy something the system can represent
rather than something it discovers only at apply time.
"""

from .architect import Architect
from .curator import MemoryCurator
from .harmonizer import ProviderHarmonizer
from .repair import ErrorToEdit

__all__ = ["Architect", "ProviderHarmonizer", "MemoryCurator", "ErrorToEdit"]
