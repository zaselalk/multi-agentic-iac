"""
v_deploy - the DevOps agent's runtime grounding.

MACOG runs `terraform init/plan/apply` in a sandbox and reports what the
provider says. This runs `init -backend=false`, `validate`, `plan -out` and
`show -json`, all offline - see validators/terraform.py for why no cloud
account is needed, and `compiler.preamble.plan_mode` in schema.json for the
provider arguments that make it possible.

`apply` is deliberately absent and will stay absent. Everything up to it is
side-effect-free and can run on every verification; apply is not, and a system
whose whole argument is that it does not change things behind your back should
not be the thing that creates them.

This validator interprets the plan artifact rather than producing it. The
artifact is written to the blackboard during the deploy state and read by the
Security Prover too, because post-expansion values are exactly what the IR
cannot have.
"""

from typing import Any, Dict

from . import terraform
from .base import counterexample, result


class DeployValidator:
    name = "deploy"

    def run(self, compiled: Dict[str, Any], **_) -> Dict[str, Any]:
        artifact = compiled.get("plan")
        if not artifact:
            # Called outside the orchestrator - a test, or a direct use. Do the
            # work rather than reporting an absence that is only about wiring.
            artifact = terraform.normalise(
                terraform.ground(compiled.get("hcl") or ""), compiled
            )

        status = artifact.get("status")
        if status == "skipped":
            return result(self.name, "skipped", reason=artifact.get("reason", ""),
                          evidence=artifact.get("evidence", {}))

        if status == "fail":
            stage = artifact.get("stage", "validate")
            found = [
                counterexample(
                    node_id=terraform.node_for(block, compiled),
                    type_="deploy_error",
                    message=terraform.summarise(block),
                    rule=f"terraform_{stage}",
                    fix_hint="Correct the attribute the provider rejected, or add the "
                             "missing field to the resource registry in schema.json.",
                )
                for block in artifact.get("diagnostics", [])
            ]
            return result(self.name, "fail", counterexamples=found,
                          evidence={"stage": stage, **artifact.get("evidence", {})})

        summary = artifact.get("summary", {})
        return result(
            self.name, "pass",
            evidence={
                "stage": artifact.get("stage", ""),
                "terraform_version": artifact.get("terraform_version", ""),
                # What the provider says this graph would do. Nothing runs
                # `apply`, so these are counts of a plan and never of a change.
                "planned": summary,
                "resources": len(artifact.get("resources", [])),
            },
        )

    def availability(self):
        return terraform.available()
