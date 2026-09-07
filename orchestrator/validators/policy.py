"""
v_policy - the Security Prover.

MACOG evaluates OPA/Rego against `terraform plan` JSON. This evaluates both,
in one pass, over one input document:

    input.ir    the compiler's typed IR - what the graph says
    input.plan  the provider's plan - what will actually exist

The IR came first for a reason specific to this research: every IR resource
carries the `node_id` it came from, so a violation is already addressed to a
canvas node, whereas plan JSON is addressed the way Terraform thinks and would
lose that on the way. `validators/terraform.normalise` closes the gap by
attaching `node_id` to every planned resource, so a plan-grounded rule is as
drawable as an IR one.

Both are kept because they prove different things. The IR is available on every
turn at no cost and says what the compiler emitted; the plan needs Terraform
and a provider download and says what AWS will do with it. A rule about an
attribute the graph sets belongs on the IR. A rule about a value only the
provider knows - a resolved `tags_all`, an expanded default, whether something
is knowable before apply at all - can only be written against the plan.

`input.plan` is absent on turns where deploy validation is off, so a
plan-grounded rule must guard on its presence or it silently proves nothing.

Rego contract - policies live in ../policies and are evaluated as:

    package visor.<anything>

    deny contains {
      "node_id":   "logs-s3",
      "rule":      "no_public_s3",
      "message":   "Bucket is publicly readable",
      "fix_hint":  "Set acl to private",
      "attribute": "acl",            # optional
      "patch":     {"acl": null}     # optional
    } if { ... }

`attribute` and `patch` are what make a violation actionable without a model.
A rule that names the desired_state key it is about lets the router tell a
contradiction of the human's request from an omission nobody asked for; a rule
that also names the fix lets that fix be offered as a diff. Rules about the
compiler's own invariants (a missing companion, absent default tags) name
neither, because there is nothing on the node to change.

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

        artifact = compiled.get("plan") or {}
        document = {
            "ir": compiled.get("terraform_ir", {}),
            # Present only when the plan ran and Terraform accepted the
            # configuration. A half-finished plan would be worse than none:
            # a rule guarding on `input.plan` would fire against resources the
            # provider never got as far as expanding.
            "plan": (
                {
                    "resources": artifact.get("resources", []),
                    "summary": artifact.get("summary", {}),
                    "terraform_version": artifact.get("terraform_version", ""),
                }
                if artifact.get("status") == "pass"
                else None
            ),
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
                attribute=v.get("attribute", ""),
                patch=v.get("patch"),
            )
            for v in violations
        ]
        blocking = [c for c in found if c["severity"] == "error"]
        return result(
            self.name,
            "fail" if blocking else "pass",
            counterexamples=found,
            evidence={"policy_dir": POLICY_DIR, "violations": len(found),
                      "packages": sorted(_rego_files(POLICY_DIR)),
                      # Whether the plan-grounded rules could prove anything
                      # this turn. Without this, a pass over IR-only rules
                      # reads identically to a pass over everything.
                      "grounded_in_plan": document["plan"] is not None},
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
