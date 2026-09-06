"""
v_policy - the Security Prover.

MACOG evaluates OPA/Rego against `terraform plan` JSON. This runs the same
engine one stage earlier, against the compiler's typed IR, for a reason
specific to this research: every IR resource carries the `node_id` it came
from, so a violation is already addressed to a canvas node. Evaluating a plan
file would produce Terraform addresses that then have to be mapped back to
nodes before anything can be drawn on the canvas, and that mapping is exactly
where the visual feedback loop would lose fidelity.

Cost of that choice: a plan file has post-expansion values (resolved ARNs,
counts, provider defaults) that the IR does not. Policies needing those belong
in the deploy validator, once plan output is available there.

Rego contract - policies live in ../policies and are evaluated as:

    package visor.<anything>

    deny contains {
      "node_id":  "logs-s3",
      "rule":     "no_public_s3",
      "message":  "Bucket is publicly readable",
      "fix_hint": "Set acl to private"
    } if { ... }

The query is `data.visor` walked for `deny` sets, so a new .rego file under
package `visor.*` is picked up with no code change.
"""

import json
import os
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List

from .base import counterexample, result

POLICY_DIR = os.environ.get(
    "VISOR_POLICY_DIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "policies")),
)
OPA_QUERY = "data.visor"
TIMEOUT_S = 20


class PolicyValidator:
    name = "policy"

    def run(self, compiled: Dict[str, Any], settings: Dict[str, Any] = None, **_) -> Dict[str, Any]:
        opa = shutil.which("opa")
        if not opa:
            return result(
                self.name, "skipped",
                reason="opa is not on PATH; install Open Policy Agent to enable policy proving.",
            )
        if not os.path.isdir(POLICY_DIR) or not _rego_files(POLICY_DIR):
            return result(
                self.name, "skipped",
                reason=f"no .rego policies found in {POLICY_DIR}.",
            )

        document = {
            "ir": compiled.get("terraform_ir", {}),
            "settings": settings or {},
        }

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(document, handle)
            input_path = handle.name

        try:
            proc = subprocess.run(
                [opa, "eval", "--format", "json", "--data", POLICY_DIR,
                 "--input", input_path, OPA_QUERY],
                capture_output=True, text=True, timeout=TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            return result(self.name, "skipped", reason=f"opa eval timed out after {TIMEOUT_S}s.")
        finally:
            os.unlink(input_path)

        if proc.returncode != 0:
            return result(
                self.name, "skipped",
                reason=f"opa eval failed: {(proc.stderr or proc.stdout).strip()[:300]}",
            )

        violations = _collect(proc.stdout)
        found = [
            counterexample(
                node_id=v.get("node_id", ""),
                type_="policy_violation",
                rule=v.get("rule", ""),
                message=v.get("message", ""),
                severity=v.get("severity", "error"),
                fix_hint=v.get("fix_hint", ""),
            )
            for v in violations
        ]
        blocking = [c for c in found if c["severity"] == "error"]
        return result(
            self.name,
            "fail" if blocking else "pass",
            counterexamples=found,
            evidence={"policy_dir": POLICY_DIR, "violations": len(found),
                      "packages": sorted(_rego_files(POLICY_DIR))},
        )


    def availability(self):
        if not shutil.which("opa"):
            return {"available": False, "reason": "opa is not on PATH."}
        if not os.path.isdir(POLICY_DIR) or not _rego_files(POLICY_DIR):
            return {"available": False, "reason": f"no .rego policies in {POLICY_DIR}."}
        return {"available": True, "reason": "", "policies": sorted(_rego_files(POLICY_DIR))}

def _rego_files(directory: str) -> List[str]:
    return [f for f in os.listdir(directory) if f.endswith(".rego")]


def _collect(stdout: str) -> List[Dict[str, Any]]:
    """
    Pull every `deny` set out of an `opa eval data.visor` result.

    The document is {"result": [{"expressions": [{"value": {<pkg>: {"deny": [...]}}}]}]},
    so each sub-package under visor contributes its own deny set.
    """
    try:
        payload = json.loads(stdout or "{}")
    except json.JSONDecodeError:
        return []

    violations: List[Dict[str, Any]] = []
    for item in payload.get("result", []):
        for expression in item.get("expressions", []):
            for package in (expression.get("value") or {}).values():
                if isinstance(package, dict):
                    for entry in package.get("deny", []) or []:
                        if isinstance(entry, dict):
                            violations.append(entry)
                        else:
                            violations.append({"message": str(entry)})
    return violations
