"""
Architect - the only agent here that calls a model.

MACOG's Architect parses intent and constraints into a typed I-IR plan. This
one does the same job against a live graph rather than a blank page: it reads
what the human has already drawn, edits it through MCP tools, and never writes
HCL. The compiler does that afterwards, deterministically.

Two turns exist. `plan()` is the first pass over a user's intent. `repair()` is
the counterexample-guided pass (MACOG S4.6): the same agent, shown the specific
validator failures and asked for a minimal edit rather than a rewrite.
"""

import json
import os
from typing import Any, Dict, List, Optional

from azure.ai.inference.models import (
    AssistantMessage,
    ChatCompletionsToolDefinition,
    FunctionDefinition,
    SystemMessage,
    ToolMessage,
    UserMessage,
)

from ..mcp_client import MCPClient

MAX_TOOL_ROUNDS = int(os.environ.get("VISOR_MAX_TOOL_ROUNDS", "12"))

# Tools the model must not reach for. set_graph is the orchestrator's own
# loading mechanism and would wipe the graph rather than edit it.
# import_terraform takes a whole file as an argument, which a model can only
# supply by retyping one, and round_trip_check reports compiler defects the
# Architect cannot fix - offering it invites a repair round that cannot help.
TOOL_DENYLIST = {"set_graph", "import_terraform", "round_trip_check"}

SYSTEM_PROMPT = """\
You are the Architect in a multi-agent infrastructure system. You edit a live
infrastructure graph through MCP tools. Think internally; do NOT narrate steps.

The graph is the single source of truth. A deterministic compiler turns it into
Terraform HCL after you finish, so you never write HCL yourself, and separate
validator agents check the result after you - do not try to do their job.

Rules:
- ALWAYS call get_graph first. Build on what already exists; never recreate a
  node that is already there, and never delete something the user did not ask
  you to remove.
- Use short, stable, human-readable node ids: "vpc-1", "web-ec2", "logs-s3".
- desired_state carries Terraform attributes ONLY. Never put position, style,
  parent_id or any other canvas/UI key in it - that is rejected.
- Express relationships with depends_on using node ids. The compiler turns them
  into real Terraform references (a subnet's vpc_id, an instance's subnet_id, a
  CloudFront origin) wherever the registry defines one.
- Names and strings from the user's request must be reproduced EXACTLY,
  case-sensitive, with no prefixes or suffixes.
- Do not invent attributes. If you are unsure, leave it out and let the
  registry defaults apply.
- Compliance is applied by the compiler (version pinning, default tags, S3
  public-access blocking and encryption, RDS/EBS encryption) and checked by the
  Security Prover. Do not reproduce it by hand, and do not add nodes solely to
  satisfy it.

Finish with a short, friendly message for the user describing what changed -
one or two sentences, plain prose, no JSON, no code fences, no step lists.
"""

REPAIR_PROMPT = """\
You are the Architect, repairing your own plan. Validators rejected the graph
you produced. Each failure below names the node it belongs to.

Make the SMALLEST edit that clears them. Do not restructure anything that was
not reported, do not delete nodes that were not the subject of a failure, and
do not add resources to work around a failure you could fix in place.

Failures:
{failures}

Apply the fixes with update_node / create_node / delete_node, then reply with
one sentence saying what you changed.
"""


def _motif_context(motifs: List[Dict[str, Any]]) -> str:
    """
    Verified motifs, as typed fragments.

    Never HCL (MACOG S4.10): HCL ages with the provider, and a motif pasted as
    text would reintroduce exactly the version drift the typed graph avoids.
    Layout is included because a motif here is a subgraph *plus* its
    arrangement - that is what makes it visual, and restoring the arrangement
    is half of what makes it useful to a human.

    Worded as precedent, not instruction. A motif is evidence that a shape
    passed every validator before; it is not a request, and the one in front of
    the model is the user's.
    """
    blocks = []
    for motif in motifs:
        lines = [
            f'- verified {motif.get("times_verified", 0)}x, '
            f'relevance {motif.get("score", 0)}'
        ]
        for node in motif.get("nodes") or []:
            state = ", ".join(
                f"{k}={v!r}" for k, v in sorted((node.get("desired_state") or {}).items())
            )
            parent = (node.get("view") or {}).get("parent")
            lines.append(
                f'    {node.get("resource")}'
                + (f" [{state}]" if state else "")
                + (f" nested in {parent}" if parent else "")
            )
        for edge in motif.get("edges") or []:
            lines.append(f"    depends: {edge}")
        blocks.append("\n".join(lines))
    return (
        "Previously verified structures from this workspace, for reference "
        "only. Each passed every validator on an earlier turn. Follow one only "
        "where it fits what is being asked for now; ignore them otherwise.\n"
        + "\n".join(blocks)
    )


class Architect:
    name = "architect"

    def __init__(self, mcp: MCPClient, chat_client, model: str):
        self.mcp = mcp
        self.client = chat_client
        self.model = model

    # -----------------------------------------------------
    def tool_definitions(self) -> List[ChatCompletionsToolDefinition]:
        return [
            ChatCompletionsToolDefinition(
                function=FunctionDefinition(
                    name=tool["name"],
                    description=tool.get("description", ""),
                    parameters=tool.get("inputSchema", {"type": "object", "properties": {}}),
                )
            )
            for tool in self.mcp.list_tools()
            if tool["name"] not in TOOL_DENYLIST
        ]

    # -----------------------------------------------------
    def plan(self, intent: str, session_id: str, knowledge: str = "",
             motifs: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """First pass: turn the user's intent into graph edits."""
        content = intent
        if knowledge.strip():
            content = (
                f"Retrieved Terraform provider context:\n{knowledge}\n\n"
                f"User request: {intent}"
            )
        if motifs:
            content = f"{_motif_context(motifs)}\n\n{content}"
        return self._turn(
            SystemMessage(content=SYSTEM_PROMPT),
            UserMessage(content=f"Session: {session_id}\n\n{content}"),
            session_id,
        )

    def repair(self, counterexamples: List[Dict[str, Any]], session_id: str) -> Dict[str, Any]:
        """
        Counterexample-guided pass (MACOG Eq. 12, the Error-to-Edit mapping).

        The failures are handed over as structured text rather than paraphrased,
        which is the distinction MACOG draws between its repair loop and a
        multi-turn baseline: the model is told exactly which node and which rule
        failed, so it patches instead of speculating.
        """
        failures = "\n".join(
            f'- [{c.get("severity", "error")}] node "{c.get("node_id") or "(graph)"}"'
            f'{" rule " + c["rule"] if c.get("rule") else ""}: {c.get("message", "")}'
            + (f'\n  Suggested fix: {c["fix_hint"]}' if c.get("fix_hint") else "")
            for c in counterexamples
        )
        return self._turn(
            SystemMessage(content=SYSTEM_PROMPT),
            UserMessage(content=REPAIR_PROMPT.format(failures=failures)),
            session_id,
        )

    # -----------------------------------------------------
    def _turn(self, system: SystemMessage, user: UserMessage, session_id: str) -> Dict[str, Any]:
        """One bounded tool-calling turn. Returns {"reply", "trace", "truncated"}."""
        messages = [system, user]
        tools = self.tool_definitions()
        trace: List[Dict[str, Any]] = []
        reply, truncated = "", False

        for _ in range(MAX_TOOL_ROUNDS):
            response = self.client.complete(messages=messages, model=self.model, tools=tools)

            # A completion with no choices is rare and real: content filtering,
            # a throttled deployment, or a generation that failed after the
            # request was accepted all return 200 with an empty list. Indexing
            # it raised IndexError out of the agent, through the state machine,
            # and out of the API as a 500 - losing every edit already made this
            # turn and telling the human nothing. The turn ends here instead,
            # keeping the trace, because the graph edits in it are real.
            if not getattr(response, "choices", None):
                reply = (
                    "The model returned nothing for this turn. Anything already "
                    "changed is on the canvas and is listed below; nothing was "
                    "rolled back. Try again, or say what to do next."
                )
                break

            choice = response.choices[0].message
            tool_calls = getattr(choice, "tool_calls", None)

            if not tool_calls:
                reply = choice.content or ""
                break

            messages.append(AssistantMessage(content=choice.content, tool_calls=tool_calls))
            for call in tool_calls:
                name = call.function.name
                try:
                    arguments = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                arguments["session_id"] = session_id

                if name in TOOL_DENYLIST:
                    result = {"error": f"tool '{name}' is not available to the agent"}
                else:
                    result = self.mcp.call_tool(name, arguments)

                trace.append({"tool": name, "arguments": arguments, "result": result})
                messages.append(ToolMessage(tool_call_id=call.id, content=json.dumps(result)))
        else:
            truncated = True
            reply = (
                "I reached the tool-call limit for this turn. The graph holds the "
                "changes made so far - tell me what to finish."
            )

        return {"reply": reply, "trace": trace, "truncated": truncated}
