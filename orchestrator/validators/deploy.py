"""
v_deploy - the DevOps agent's runtime grounding.

MACOG runs `terraform init/plan/apply` in LocalStack or an ephemeral account.
This implements the half that needs no cloud credentials at all -
`terraform init -backend=false` followed by `terraform validate` - which is
already the strongest independent confirmation available for free: it parses
the emitted HCL against the real AWS provider schema, so a field the compiler's
registry has wrong is caught here even though the registry accepted it.

`terraform plan` is the next rung and is deliberately not here yet: it needs
either credentials or a LocalStack endpoint, and it is the point at which a
turn stops being side-effect-free. See docs/RESEARCH-GAPS.md.
"""

import os
import re
import shutil
import subprocess
import tempfile
from typing import Any, Dict

from .base import counterexample, result

TIMEOUT_S = int(os.environ.get("VISOR_TERRAFORM_TIMEOUT", "120"))
# Terraform reports a diagnostic against a file and line, not a node. The
# compiler names every resource after its node's tf_name, so the address in
# the message is the way back to the canvas.
ADDRESS = re.compile(r'\b(aws_[a-z0-9_]+)\.([a-zA-Z0-9_]+)\b')


class DeployValidator:
    name = "deploy"

    def run(self, compiled: Dict[str, Any], **_) -> Dict[str, Any]:
        terraform = shutil.which("terraform")
        if not terraform:
            return result(self.name, "skipped",
                          reason="terraform is not on PATH; install it to enable deploy validation.")

        hcl = compiled.get("hcl") or ""
        if not hcl.strip():
            return result(self.name, "skipped", reason="nothing compiled to validate.")

        workdir = tempfile.mkdtemp(prefix="visor-tf-")
        try:
            with open(os.path.join(workdir, "main.tf"), "w") as handle:
                handle.write(hcl)

            init = _run([terraform, "init", "-backend=false", "-input=false", "-no-color"], workdir)
            if init["code"] != 0:
                return result(
                    self.name, "skipped",
                    reason=f"terraform init failed (usually no network for the provider "
                           f"download): {init['stderr'][:300]}",
                    evidence=init,
                )

            check = _run([terraform, "validate", "-no-color"], workdir)
            if check["code"] == 0:
                return result(self.name, "pass", evidence={"stdout": check["stdout"][:2000]})

            found = [
                counterexample(
                    node_id=_node_for(line, compiled),
                    type_="deploy_error",
                    message=line.strip(),
                    rule="terraform_validate",
                    fix_hint="Correct the attribute the provider rejected, or add the "
                             "missing field to the resource registry in schema.json.",
                )
                for line in _diagnostics(check["stdout"] + check["stderr"])
            ]
            return result(self.name, "fail", counterexamples=found, evidence=check)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)


    def availability(self):
        if not shutil.which("terraform"):
            return {"available": False, "reason": "terraform is not on PATH."}
        return {"available": True, "reason": ""}

def _run(command, cwd) -> Dict[str, Any]:
    try:
        proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT_S)
        return {"code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
    except subprocess.TimeoutExpired:
        return {"code": 124, "stdout": "", "stderr": f"timed out after {TIMEOUT_S}s"}


def _diagnostics(output: str):
    """Terraform prints 'Error: ...' followed by context; keep the headline lines."""
    return [line for line in output.splitlines() if line.strip().startswith("Error:")] or (
        [output.strip()[:500]] if output.strip() else []
    )


def _node_for(message: str, compiled: Dict[str, Any]) -> str:
    """Map a Terraform address in a diagnostic back to the node that produced it."""
    by_tf_name = {
        r.get("name"): r.get("node_id", "")
        for r in (compiled.get("terraform_ir") or {}).get("resources", [])
    }
    for _, name in ADDRESS.findall(message):
        if name in by_tf_name:
            return by_tf_name[name]
    return ""
