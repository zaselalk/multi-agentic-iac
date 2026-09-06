# Policies

Rego rules the Security Prover (`orchestrator/validators/policy.py`) evaluates
on every turn. Drop a `.rego` file in here and it is picked up — no code change.

## Requirements

OPA on `PATH`. These use Rego v1 syntax (`import rego.v1`), so **OPA 1.x**, or
0.59+ where the import is available:

```shell
curl -L -o opa https://openpolicyagent.org/downloads/latest/opa_linux_amd64_static
chmod +x opa && mv opa ~/.local/bin/
opa check policies/       # syntax
opa fmt --diff policies/  # formatting
```

Without it the prover reports `skipped`, never `pass` — an unproven obligation
must not read as a satisfied one.

## What they run against

The input document is the compiler's typed IR plus the project's settings:

```json
{ "ir":       { "resources": [ {"type", "name", "node_id", "attributes", "depends_on"} ], ... },
  "settings": { "region": "eu-west-1", "default_tags": {...}, "allowed_regions": [...] } }
```

Evaluating the IR rather than `terraform plan` JSON is deliberate. **Every IR
resource carries the `node_id` it came from**, so a violation is already
addressed to a canvas node and can be drawn there. A plan file yields Terraform
addresses that must be mapped back first, and that mapping is where the visual
feedback loop loses fidelity.

The cost of that choice: a plan file has post-expansion values (resolved ARNs,
counts, provider-injected defaults) the IR does not, and — see
`docs/RESEARCH-GAPS.md#g1` — the IR omits the compliance *companion* resources
that do appear in the emitted HCL. A rule needing either belongs in the deploy
validator once plan output is available there.

## Writing a rule

Package must be under `visor.`; the prover walks `data.visor` for `deny` sets.

```rego
package visor.my_rule

import rego.v1

deny contains {
	"node_id":  resource.node_id,          # "" for a whole-graph finding
	"rule":     "my_rule",
	"message":  "what is wrong",
	"severity": "error",                    # or "warning" — warnings never
	"fix_hint": "what to change",           # trigger a repair round
} if {
	resource := input.ir.resources[_]
	# ...
}
```

`severity` decides behaviour, not just presentation: an `error` enters the
repair loop and is handed to the Architect as a counterexample; a `warning` is
carried to the human untouched. Spending a model round on a warning is how a
repair loop starts to oscillate.

## Current rules

| File | Rules | Catches |
|---|---|---|
| `encryption_at_rest.rego` | `rds_storage_encrypted` (error), `dynamodb_encryption` (warning) | Unencrypted databases; tables on the AWS-owned key. |
| `no_public_s3.rego` | `s3_public_acl` (error), `s3_versioning` (warning) | A public ACL contradicting the compiler's public access block; unrecoverable buckets. |
| `data_residency.rego` | `region_not_allowed` (error) | A project region outside its own `allowed_regions`. |

`s3_public_acl` is the one worth understanding. The compiler attaches an
`aws_s3_bucket_public_access_block` to every bucket, so a public ACL is not a
risk here but a *contradiction* — AWS provider v4+ fails the apply. That is
precisely the research case: a human makes a visual change ("make this bucket
public") that collides with a constraint only the compiler knows about. The
rule is what lets the canvas say so before an apply fails.
