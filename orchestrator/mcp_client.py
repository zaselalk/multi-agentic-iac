"""
Minimal MCP client over stdio.

Speaks JSON-RPC 2.0 to visor-mcp (../mcp-server/main.py) as a long-lived child
process, so the graph sessions it holds survive between chat turns.
"""

import json
import os
import subprocess
import sys
import threading
from typing import Any, Dict, List, Optional

DEFAULT_MCP_PATH = os.environ.get(
    "VISOR_MCP_SERVER",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "mcp-server")),
)

PROTOCOL_VERSION = "2024-11-05"


class MCPError(RuntimeError):
    pass


class MCPClient:
    """One subprocess, one lock. Calls are serialised over the stdio pipe."""

    def __init__(self, server_path: Optional[str] = None, python_executable: Optional[str] = None):
        self.server_path = server_path or DEFAULT_MCP_PATH
        self.python = python_executable or sys.executable
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._next_id = 0
        self.tools: List[Dict[str, Any]] = []

    # ---------------------------------------------------------
    # lifecycle
    # ---------------------------------------------------------
    def start(self):
        entrypoint = os.path.join(self.server_path, "main.py")
        if not os.path.exists(entrypoint):
            raise MCPError(
                f"MCP server not found at {entrypoint}. Set VISOR_MCP_SERVER to the "
                "mcp-server checkout."
            )

        self._proc = subprocess.Popen(
            [self.python, "main.py"],
            cwd=self.server_path,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )

        self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "macog-orchestrator", "version": "1.0.0"},
        })
        self._notify("notifications/initialized", {})
        self.tools = self._request("tools/list", {}).get("tools", [])
        return self

    def stop(self):
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.stdin.close()
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()
        self._proc = None

    def _ensure_running(self):
        if self._proc is None or self._proc.poll() is not None:
            self.start()

    # ---------------------------------------------------------
    # transport
    # ---------------------------------------------------------
    def _send(self, payload: Dict[str, Any]):
        self._proc.stdin.write(json.dumps(payload) + "\n")
        self._proc.stdin.flush()

    def _notify(self, method: str, params: Dict[str, Any]):
        with self._lock:
            self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            self._next_id += 1
            req_id = self._next_id
            self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})

            while True:
                line = self._proc.stdout.readline()
                if not line:
                    raise MCPError("MCP server closed the connection")
                message = json.loads(line)
                if message.get("id") != req_id:
                    continue  # notification or stale reply
                if "error" in message:
                    raise MCPError(message["error"].get("message", "unknown MCP error"))
                return message.get("result", {})

    # ---------------------------------------------------------
    # tools
    # ---------------------------------------------------------
    def list_tools(self) -> List[Dict[str, Any]]:
        self._ensure_running()
        return self.tools

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call an MCP tool and unwrap its JSON text content."""
        self._ensure_running()
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        content = result.get("content", [])
        if not content:
            return {}
        try:
            return json.loads(content[0].get("text", "{}"))
        except json.JSONDecodeError:
            return {"raw": content[0].get("text", "")}
