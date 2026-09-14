"""
Running Terraform, and turning what it says into something addressable.

MACOG's DevOps agent runs `terraform init/plan/apply` in LocalStack or an
ephemeral account, and its ablation shows this is the costliest component to
remove: IaC-Eval 74.02 -> 56.93 without the sandbox, the largest drop of the
eight. That was scoped here as needing LocalStack, which this environment
cannot run.

It turns out not to need one. With placeholder credentials and the provider's
skip flags (see `compiler.preamble.plan_mode` in schema.json), `terraform plan`
runs completely offline once the provider is downloaded: it resolves the real
provider schema, expands every default, and emits plan JSON. No account, no
network, no side effects - `apply` is never run and these credentials would
authenticate nothing if it were.

What that buys is the thing the IR cannot have. The IR says
`tags = merge(local.default_tags, ...)` because that is what the HCL says; the
plan says `tags_all = {"Owner": "visor", ...}` because that is what will exist.
Post-expansion values, resolved defaults, and `after_unknown` marking what is
only knowable at apply. So the plan is produced once by the controller rather
than as one validator's private output, and passed to both the DevOps
validator and the Security Prover.
"""

import glob
import json
import os
import re
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List, Optional

TIMEOUT_S = int(os.environ.get("VISOR_TERRAFORM_TIMEOUT", "120"))

# Every run works in a fresh temporary directory, so without a shared cache
# `terraform init` re-downloads the AWS provider - about 20 s of a 24 s
# verification, every time. With one it is a copy from disk. The cache holds
# only provider binaries Terraform itself verified against the registry's
# checksums, and lives outside the temp dir precisely so it survives it.
PLUGIN_CACHE = os.environ.get(
    "TF_PLUGIN_CACHE_DIR",
    os.path.expanduser("~/.cache/visor/terraform-plugins"),
)

# The cache alone is not enough. Terraform still asks registry.terraform.io to
# resolve `~> 5.0` to a concrete version before it looks in any cache, so a
# flaky moment on the network turns a passing verification into a skipped one -
# which is exactly the failure mode this validator exists to avoid reporting as
# a pass. A filesystem mirror is consulted *before* the registry, and the plugin
# cache's directory layout already is the unpacked mirror layout, so the same
# directory serves as both. `direct` stays as the fallback, so a cold cache
# still works and a new provider version can still be fetched.
CLI_CONFIG = os.path.join(os.path.dirname(PLUGIN_CACHE), "visor-terraform.rc")
CLI_CONFIG_BODY = """provider_installation {{
  filesystem_mirror {{
    path    = "{mirror}"
    include = ["registry.terraform.io/*/*"]
  }}
  direct {{}}
}}
"""

# Terraform reports a diagnostic against a file and line, not a node. The
# compiler names every resource after its node's tf_name, so the address in the
# message is the way back to the canvas - but it is written two different ways.
# Expressions use the dotted form; diagnostic headers use the quoted form, as
# in `on main.tf line 75, in resource "aws_instance" "test_lb_tf":`. Matching
# only the first leaves every diagnostic unattributed.
ADDRESS = re.compile(
    r'\b(aws_[a-z0-9_]+)\.([a-zA-Z0-9_]+)\b'
    r'|resource\s+"(aws_[a-z0-9_]+)"\s+"([a-zA-Z0-9_]+)"'
)


def available() -> Dict[str, Any]:
    if not shutil.which("terraform"):
        return {"available": False, "reason": "terraform is not on PATH."}
    return {"available": True, "reason": ""}


# ---------------------------------------------------------
# RUNNING
# ---------------------------------------------------------
def ground(hcl: str) -> Dict[str, Any]:
    """
    init -> validate -> plan -> show -json, stopping at the first failure.

    Returns an artifact, not a verdict: `stage` says how far it got, `status`
    whether Terraform accepted the configuration, and `plan` the parsed JSON
    when there is one. Interpreting that is the caller's job - the same
    artifact is read by two validators that want different things from it.
    """
    terraform = shutil.which("terraform")
    if not terraform:
        return _artifact("skipped", "init", reason="terraform is not on PATH.")
    if not (hcl or "").strip():
        return _artifact("skipped", "init", reason="nothing compiled to plan.")

    workdir = tempfile.mkdtemp(prefix="visor-tf-")
    try:
        with open(os.path.join(workdir, "main.tf"), "w") as handle:
            handle.write(hcl)

        init = _run([terraform, "init", "-backend=false", "-input=false", "-no-color"], workdir)
        if init["code"] != 0:
            output = init["stdout"] + init["stderr"]
            # An init failure is two completely different events wearing one
            # exit code. Reporting both as "no network" hid a real one: a node
            # that set its own `tags` compiled to two `tags` arguments in one
            # resource, Terraform refused to initialise, and the validator
            # said the provider download had failed. A configuration error
            # must fail, or the check exists only to be explained away.
            if _config_error(output):
                return _artifact(
                    "fail", "init",
                    diagnostics=diagnostics(output),
                    evidence=init,
                )
            return _artifact(
                "skipped", "init",
                reason="terraform init could not fetch the provider (no network?): "
                       f"{init['stderr'][:300]}",
                evidence=init,
            )

        check = _run([terraform, "validate", "-no-color"], workdir)
        if check["code"] != 0:
            return _artifact(
                "fail", "validate",
                diagnostics=diagnostics(check["stdout"] + check["stderr"]),
                evidence=check,
            )

        # -lock=false because there is no state to lock; -input=false so a
        # missing variable fails rather than blocking on a prompt forever.
        made = _run(
            [terraform, "plan", "-out=tfplan", "-input=false", "-lock=false", "-no-color"],
            workdir,
        )
        if made["code"] != 0:
            return _artifact(
                "fail", "plan",
                diagnostics=diagnostics(made["stdout"] + made["stderr"]),
                evidence=made,
            )

        shown = _run([terraform, "show", "-json", "tfplan"], workdir)
        if shown["code"] != 0:
            return _artifact(
                "skipped", "show",
                reason=f"terraform show -json failed: {shown['stderr'][:300]}",
                evidence=shown,
            )
        try:
            raw = json.loads(shown["stdout"] or "{}")
        except json.JSONDecodeError as error:
            return _artifact("skipped", "show", reason=f"plan JSON did not parse: {error}")

        return _artifact("pass", "show", plan=raw,
                         evidence={"stdout": made["stdout"][-2000:]})
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# What Terraform says when init failed because the configuration is wrong
# rather than because it could not reach the registry.
CONFIG_ERROR = "configuration must be valid before initialization"

# What it says when it could not reach the registry.
NETWORK_ERRORS = (
    "failed to query available provider packages",
    "failed to install provider",
    "could not retrieve the list of available versions",
    "no such host",
    "connection refused",
    "context deadline exceeded",
    "tls handshake timeout",
)


def _config_error(output: str) -> bool:
    """Is this init failure about the HCL, or about the network?"""
    lowered = output.lower()
    if CONFIG_ERROR in lowered:
        return True
    return bool(lowered.strip()) and not any(marker in lowered for marker in NETWORK_ERRORS)


def _artifact(status: str, stage: str, reason: str = "",
              diagnostics: Optional[List[str]] = None,
              plan: Optional[Dict[str, Any]] = None,
              evidence: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "status": status,
        "stage": stage,
        "reason": reason,
        "diagnostics": diagnostics or [],
        "plan": plan,
        "resources": [],
        "summary": {"add": 0, "change": 0, "destroy": 0},
        "evidence": evidence or {},
    }


def _mirrored() -> bool:
    """Has a previous run left a usable provider in the cache?"""
    pattern = os.path.join(PLUGIN_CACHE, "*", "*", "*", "*", "*")
    return any(os.path.isdir(path) for path in glob.glob(pattern))


def _prepare_cache(environment: Dict[str, str]) -> None:
    """
    Point Terraform at the shared provider directory, one way or the other.

    The two settings are mutually exclusive, and finding that out cost a
    confusing error: with the same directory as both cache and mirror,
    Terraform tries to install the provider from the mirror into the cache and
    refuses to "install existing provider directory to itself". So the first
    run treats it as a cache and fills it from the registry; every run after
    treats it as a mirror and never touches the network.
    """
    environment.pop("TF_PLUGIN_CACHE_DIR", None)
    environment.pop("TF_CLI_CONFIG_FILE", None)
    try:
        os.makedirs(PLUGIN_CACHE, exist_ok=True)
        if not _mirrored():
            environment["TF_PLUGIN_CACHE_DIR"] = PLUGIN_CACHE
            return
        body = CLI_CONFIG_BODY.format(mirror=PLUGIN_CACHE)
        if not os.path.exists(CLI_CONFIG) or open(CLI_CONFIG).read() != body:
            with open(CLI_CONFIG, "w") as handle:
                handle.write(body)
        environment["TF_CLI_CONFIG_FILE"] = CLI_CONFIG
    except OSError:
        # An unwritable directory is a slow run, not a failed one.
        environment.pop("TF_PLUGIN_CACHE_DIR", None)
        environment.pop("TF_CLI_CONFIG_FILE", None)


def _run(command, cwd) -> Dict[str, Any]:
    environment = dict(os.environ)
    _prepare_cache(environment)
    environment["TF_IN_AUTOMATION"] = "1"

    try:
        proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                              timeout=TIMEOUT_S, env=environment)
        return {"code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
    except subprocess.TimeoutExpired:
        return {"code": 124, "stdout": "", "stderr": f"timed out after {TIMEOUT_S}s"}


# ---------------------------------------------------------
# NORMALISING
# ---------------------------------------------------------
def normalise(artifact: Dict[str, Any], compiled: Dict[str, Any]) -> Dict[str, Any]:
    """
    Flatten plan JSON into resources that carry their `node_id`.

    Raw plan JSON is addressed the way Terraform thinks - `aws_db_instance.x` -
    and a finding the canvas cannot address to a node is one it cannot draw. It
    is also three overlapping views of the same thing (`resource_changes`,
    `planned_values`, `configuration`); a Rego author should not have to know
    which one holds what. So this is the single shape policies are written
    against, and the reason `input.plan` looks nothing like `terraform show`.
    """
    plan = artifact.get("plan") or {}
    by_name = {
        r.get("name"): r.get("node_id", "")
        for r in (compiled.get("terraform_ir") or {}).get("resources", [])
    }

    resources: List[Dict[str, Any]] = []
    summary = {"add": 0, "change": 0, "destroy": 0}
    for change in plan.get("resource_changes", []) or []:
        delta = change.get("change") or {}
        actions = delta.get("actions") or []
        if "create" in actions:
            summary["add"] += 1
        if "update" in actions:
            summary["change"] += 1
        if "delete" in actions:
            summary["destroy"] += 1
        resources.append({
            "address": change.get("address", ""),
            "type": change.get("type", ""),
            "name": change.get("name", ""),
            "node_id": by_name.get(change.get("name"), ""),
            "actions": actions,
            # Everything the provider will set, defaults expanded. This is the
            # whole reason the plan is worth running: `tags_all` is a resolved
            # map here and an unevaluated merge() expression in the IR.
            "values": delta.get("after") or {},
            # Attributes only knowable at apply. A policy asserting something
            # about one of these is asserting nothing, so it has to be able to
            # see which they are.
            "unknown": delta.get("after_unknown") or {},
        })

    artifact = dict(artifact)
    artifact["resources"] = resources
    artifact["summary"] = summary
    # The raw document is large and nothing reads it after this point. Keeping
    # it would put a megabyte of JSON through every chat response.
    artifact["plan"] = None
    artifact["terraform_version"] = plan.get("terraform_version", "")
    return artifact


# ---------------------------------------------------------
# DIAGNOSTICS
# ---------------------------------------------------------
def diagnostics(output: str) -> List[str]:
    """
    Split Terraform's output into whole diagnostics, headline plus context.

    Keeping only the `Error:` line loses the address: Terraform puts it on the
    *following* line, as `on main.tf line 75, in resource "aws_instance"
    "test_lb_tf":`. Without that the finding cannot be attributed to a node,
    and an unattributed finding is one the canvas cannot draw.
    """
    blocks: List[str] = []
    current: List[str] = []
    for line in output.splitlines():
        if line.strip().startswith(("Error:", "Warning:")):
            if current:
                blocks.append("\n".join(current).strip())
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append("\n".join(current).strip())

    if blocks:
        return blocks
    return [output.strip()[:500]] if output.strip() else []


def summarise(block: str) -> str:
    """One line from a diagnostic: the headline, plus the detail sentence."""
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    if not lines:
        return ""
    headline = lines[0].split(":", 1)[-1].strip()
    # The detail is the last prose line - the ones between are the source
    # excerpt (`on main.tf line N, ...` and the numbered line itself).
    detail = next(
        (
            line
            for line in reversed(lines[1:])
            if not line.startswith("on ") and not re.match(r"^\d+:", line)
        ),
        "",
    )
    return f"{headline}: {detail}" if detail else headline


def node_for(message: str, compiled: Dict[str, Any]) -> str:
    """Map a Terraform address in a diagnostic back to the node that produced it."""
    by_tf_name = {
        r.get("name"): r.get("node_id", "")
        for r in (compiled.get("terraform_ir") or {}).get("resources", [])
    }
    for match in ADDRESS.finditer(message):
        # group 2 is the dotted form's name, group 4 the quoted form's
        name = match.group(2) or match.group(4)
        if name in by_tf_name:
            return by_tf_name[name]
    return ""
