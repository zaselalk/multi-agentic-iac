"""
Project storage.

A project is one named infrastructure graph with its own Terraform settings -
a staging VPC and a production VPC are separate projects, edited separately
and compiled with their own region and tags.

Storage is one JSON file per project on disk. That keeps projects alive across
restarts (the MCP server's own graph state is in memory and does not survive
one), and keeps them out of any single browser.
"""

import json
import os
import re
import shutil
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .adapters import SCHEMA, canvas_to_nodes, nodes_to_canvas

PROJECT_DIR = os.environ.get(
    "VISOR_PROJECT_DIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".visor", "projects")),
)

SCHEMA_VERSION = SCHEMA.get("schema_version", "3.1.0")
_PREAMBLE = SCHEMA["compiler"]["preamble"]

MAX_NAME = 80
MAX_DESCRIPTION = 500
# Chat is kept with the project so switching projects does not lose the
# conversation that produced the graph. Trimmed so a long-lived project's
# file does not grow without bound.
MAX_CHAT_MESSAGES = 200


class ProjectError(ValueError):
    pass


def default_settings() -> Dict[str, Any]:
    """New projects start from the schema's own preamble defaults."""
    return {
        "region": _PREAMBLE["region_variable"]["default"],
        "default_tags": dict(_PREAMBLE["default_tags"]),
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return slug[:40] or "project"


class ProjectStore:
    def __init__(self, directory: str = PROJECT_DIR):
        self.directory = directory
        self._lock = threading.Lock()
        os.makedirs(self.directory, exist_ok=True)

    # ---------------------------------------------------------
    # paths
    # ---------------------------------------------------------
    def _path(self, project_id: str) -> str:
        # Project ids are generated here, but never trust one off the wire as
        # a path component.
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", project_id or ""):
            raise ProjectError(f"invalid project id: {project_id!r}")
        return os.path.join(self.directory, f"{project_id}.json")

    def _write(self, record: Dict[str, Any]):
        path = self._path(record["id"])
        # Write-then-replace, so a crash mid-save cannot truncate a project.
        handle, temp = tempfile.mkstemp(dir=self.directory, suffix=".tmp")
        try:
            with os.fdopen(handle, "w") as f:
                json.dump(record, f, indent=2)
            os.replace(temp, path)
        except BaseException:
            if os.path.exists(temp):
                os.unlink(temp)
            raise

    def _read(self, project_id: str) -> Optional[Dict[str, Any]]:
        path = self._path(project_id)
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return json.load(f)

    # ---------------------------------------------------------
    # validation
    # ---------------------------------------------------------
    @staticmethod
    def _clean_name(name: Any) -> str:
        text = str(name or "").strip()
        if not text:
            raise ProjectError("A project needs a name.")
        return text[:MAX_NAME]

    @staticmethod
    def _clean_settings(settings: Any, base: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        resolved = base or default_settings()
        if not isinstance(settings, dict):
            return resolved

        region = str(settings.get("region", "") or "").strip()
        if region:
            if not re.fullmatch(r"[a-z]{2}(-[a-z]+)+-\d", region):
                raise ProjectError(f"'{region}' is not an AWS region, e.g. eu-west-1.")
            resolved["region"] = region

        tags = settings.get("default_tags")
        if isinstance(tags, dict):
            cleaned = {
                str(k).strip(): str(v)
                for k, v in tags.items()
                if str(k).strip()
            }
            if cleaned:
                resolved["default_tags"] = cleaned
        return resolved

    # ---------------------------------------------------------
    # CRUD
    # ---------------------------------------------------------
    def list(self) -> List[Dict[str, Any]]:
        summaries = []
        for filename in os.listdir(self.directory):
            if not filename.endswith(".json"):
                continue
            try:
                with open(os.path.join(self.directory, filename)) as f:
                    record = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue  # a half-written or hand-edited file must not break the list
            summaries.append(self.summarise(record))
        summaries.sort(key=lambda p: p.get("updatedAt", ""), reverse=True)
        return summaries

    @staticmethod
    def summarise(record: Dict[str, Any]) -> Dict[str, Any]:
        nodes = record.get("nodes", [])
        kinds: Dict[str, int] = {}
        for node in nodes:
            kinds[node.get("resource", "?")] = kinds.get(node.get("resource", "?"), 0) + 1
        return {
            "id": record["id"],
            "name": record["name"],
            "description": record.get("description", ""),
            "resourceCount": len(nodes),
            "resourceKinds": kinds,
            "region": record.get("settings", {}).get("region", ""),
            "createdAt": record.get("created_at", ""),
            "updatedAt": record.get("updated_at", ""),
        }

    def create(
        self,
        name: str,
        description: str = "",
        settings: Any = None,
        nodes: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            clean_name = self._clean_name(name)
            project_id = f"{_slug(clean_name)}-{uuid.uuid4().hex[:6]}"
            record = {
                "schema_version": SCHEMA_VERSION,
                "id": project_id,
                "name": clean_name,
                "description": str(description or "")[:MAX_DESCRIPTION],
                "settings": self._clean_settings(settings),
                "nodes": nodes or [],
                "chat": [],
                "created_at": _now(),
                "updated_at": _now(),
            }
            self._write(record)
            return record

    def get(self, project_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._read(project_id)

    def update(self, project_id: str, **fields) -> Dict[str, Any]:
        with self._lock:
            record = self._read(project_id)
            if record is None:
                raise ProjectError(f"No project '{project_id}'.")

            if "name" in fields and fields["name"] is not None:
                record["name"] = self._clean_name(fields["name"])
            if "description" in fields and fields["description"] is not None:
                record["description"] = str(fields["description"])[:MAX_DESCRIPTION]
            if "settings" in fields and fields["settings"] is not None:
                record["settings"] = self._clean_settings(
                    fields["settings"], record.get("settings") or default_settings()
                )
            if "nodes" in fields and fields["nodes"] is not None:
                record["nodes"] = fields["nodes"]
            if "chat" in fields and fields["chat"] is not None:
                record["chat"] = list(fields["chat"])[-MAX_CHAT_MESSAGES:]

            record["updated_at"] = _now()
            self._write(record)
            return record

    def save_graph(
        self, project_id: str, canvas_nodes: List[Dict[str, Any]], canvas_edges: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        return self.update(project_id, nodes=canvas_to_nodes(canvas_nodes, canvas_edges))

    def append_chat(self, project_id: str, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        with self._lock:
            record = self._read(project_id)
            if record is None:
                raise ProjectError(f"No project '{project_id}'.")
            history = list(record.get("chat", [])) + list(messages)
            record["chat"] = history[-MAX_CHAT_MESSAGES:]
            record["updated_at"] = _now()
            self._write(record)
            return record

    def delete(self, project_id: str) -> bool:
        with self._lock:
            path = self._path(project_id)
            if not os.path.exists(path):
                return False
            os.unlink(path)
            return True

    # ---------------------------------------------------------
    # transfer
    # ---------------------------------------------------------
    def export(self, project_id: str) -> Dict[str, Any]:
        record = self.get(project_id)
        if record is None:
            raise ProjectError(f"No project '{project_id}'.")
        return {
            "visor_export": "1.0",
            "exported_at": _now(),
            "project": {
                "name": record["name"],
                "description": record.get("description", ""),
                "settings": record.get("settings", default_settings()),
                "nodes": record.get("nodes", []),
                "schema_version": record.get("schema_version", SCHEMA_VERSION),
            },
        }

    def import_project(self, payload: Any, name: Optional[str] = None) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProjectError("That file is not a Visor project export.")

        project = payload.get("project") if "project" in payload else payload
        if not isinstance(project, dict) or "nodes" not in project:
            raise ProjectError(
                "That file is not a Visor project export - expected a 'project' object with 'nodes'."
            )

        nodes = project.get("nodes") or []
        if not isinstance(nodes, list):
            raise ProjectError("The export's 'nodes' must be a list.")

        # Re-key through the adapter so an export from an older schema, or one
        # saved in canvas shape, still lands as canonical nodes.
        if nodes and ("data" in nodes[0] or "type" in nodes[0]):
            nodes = canvas_to_nodes(nodes, project.get("edges", []))

        return self.create(
            name=name or project.get("name") or "Imported project",
            description=project.get("description", ""),
            settings=project.get("settings"),
            nodes=nodes,
        )

    # ---------------------------------------------------------
    # canvas shape
    # ---------------------------------------------------------
    @staticmethod
    def to_canvas(record: Dict[str, Any], errors: Optional[List[Dict[str, Any]]] = None):
        return nodes_to_canvas(record.get("nodes", []), errors or [])


store = ProjectStore()
