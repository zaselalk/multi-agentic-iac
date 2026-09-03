"""
The agent loop: natural-language intent -> MCP tool calls -> compiled HCL.

This is what was missing between the three repos. multi-agentic-iac could turn
intent into HCL text but had no notion of a graph and no MCP client;
mcp-server exposed graph tools nobody called. This module closes that loop.
"""

import json
import os
import sys
from typing import Any, Dict, List, Optional

from azure.ai.inference.models import (
    AssistantMessage,
    ChatCompletionsToolDefinition,
    FunctionDefinition,
    SystemMessage,
    ToolMessage,
    UserMessage,
)

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "evaluation"))
)

from .adapters import canvas_to_nodes, nodes_to_canvas
from .mcp_client import MCPClient
from .prompts import GRAPH_AGENT_SYSTEM_PROMPT

MAX_TOOL_ROUNDS = int(os.environ.get("VISOR_MAX_TOOL_ROUNDS", "12"))
DEFAULT_MODEL = os.environ.get("VISOR_AGENT_MODEL", "gpt-4.1-mini")

# Tools the agent may not call - set_graph is the orchestrator's own loading
# mechanism, not something the model should reach for (it would wipe the graph).
AGENT_TOOL_DENYLIST = {"set_graph"}


class GraphAgent:
    def __init__(self, mcp: MCPClient, chat_client, model: Optional[str] = None):
        self.mcp = mcp
        self.client = chat_client
        self.model = model or DEFAULT_MODEL

    # ---------------------------------------------------------
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
            if tool["name"] not in AGENT_TOOL_DENYLIST
        ]

    # ---------------------------------------------------------
    def run(
        self,
        message: str,
        canvas_nodes: List[Dict[str, Any]],
        canvas_edges: List[Dict[str, Any]],
        session_id: str = "default",
        knowledge: str = "",
        settings: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        One chat turn. Loads the canvas into MCP, lets the agent edit the graph
        through tools, then compiles and hands the result back in canvas shape.
        """
        trace: List[Dict[str, Any]] = []

        # 1. The canvas is authoritative at the start of a turn - the user may
        #    have dragged, added or deleted nodes since the last turn.
        self.mcp.call_tool("set_graph", {
            "session_id": session_id,
            "nodes": canvas_to_nodes(canvas_nodes, canvas_edges),
        })

        user_content = message
        if knowledge.strip():
            user_content = (
                f"Retrieved Terraform provider context:\n{knowledge}\n\n"
                f"User request: {message}"
            )

        messages = [
            SystemMessage(content=GRAPH_AGENT_SYSTEM_PROMPT),
            UserMessage(content=f"Session: {session_id}\n\n{user_content}"),
        ]
        tools = self.tool_definitions()

        reply = ""
        for _ in range(MAX_TOOL_ROUNDS):
            response = self.client.complete(
                messages=messages, model=self.model, tools=tools
            )
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

                if name in AGENT_TOOL_DENYLIST:
                    result = {"error": f"tool '{name}' is not available to the agent"}
                else:
                    result = self.mcp.call_tool(name, arguments)

                trace.append({"tool": name, "arguments": arguments, "result": result})
                messages.append(
                    ToolMessage(tool_call_id=call.id, content=json.dumps(result))
                )
        else:
            reply = (
                "I reached the tool-call limit for this turn. The graph holds the "
                "changes made so far - tell me what to finish."
            )

        # 2. Compile deterministically and read the graph back.
        compiled = self.mcp.call_tool(
            "compile_terraform", {"session_id": session_id, "settings": settings or {}}
        )
        graph = self.mcp.call_tool("get_graph", {"session_id": session_id})

        errors = compiled.get("errors", [])
        nodes, edges = nodes_to_canvas(graph.get("nodes", []), errors)

        return {
            "chatResponse": reply or "Updated the infrastructure graph.",
            "nodes": nodes,
            "edges": edges,
            "terraform": compiled.get("hcl", ""),
            "terraformIr": compiled.get("terraform_ir", {}),
            "errors": errors,
            "warnings": compiled.get("warnings", []),
            "toolTrace": trace,
        }
