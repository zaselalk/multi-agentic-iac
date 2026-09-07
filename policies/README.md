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

Two views of the same graph, plus the project's settings:

```json
{ "ir":       { "resources": [ {"type", "name", "node_id", "attributes", "depends_on"} ], ... },
  "plan":     { "resources": [ {"address", "type", "name", "node_id", "actions", "values", "unknown"} ],
                "summary": {"add": 4, "change": 0, "destroy": 0} },
  "settings": { "region": "eu-west-1", "default_tags": {...}, "allowed_regions": [...] } }
```

**`input.ir` is what the compiler emitted.** Every IR resource carries the
`node_id` it came from, so a violation is already addressed to a canvas node
and can be drawn there. It is available on every turn at no cost.

The IR describes the emitted HCL faithfully: it is parsed back out of the
rendered body, so every compliance *companion* the compiler attaches appears in
it, carrying the `node_id` that induced it and `generated_by: "compiler"`. That
is what makes `s3_missing_public_access_block`, `ebs_root_encrypted` and
`missing_default_tags` expressible — before it, each would have fired on every
resource, because the thing satisfying them was invisible.

**`input.plan` is what AWS says will actually exist** — `terraform plan`,
normalised. Since W2 it runs completely offline (see
`orchestrator/validators/terraform.py`), so this is not the expensive option it
was scoped as. Plan resources carry `node_id` too, attached on the way in, so a
plan-grounded finding is as drawable as an IR one.

The distinction is not academic. The IR holds
`tags = merge(local.default_tags, ...)` because that is the text; the plan
holds `tags_all = {"Owner": "visor", ...}` because that is the outcome. A
resource-level tag quietly overriding a project default satisfies `tagging.rego`
and is a live compliance failure — and nothing before the plan can see it.
`unknown` carries `after_unknown`, so a rule can also tell that it is being
asked to prove something Terraform will not know until apply.

**`input.plan` is `null` when deploy validation is off**, which is the default
for a chat turn. Guard on it — a rule that silently proves nothing is worse
than one that is honestly skipped. The prover reports which happened as
`evidence.grounded_in_plan`, and the canvas says so under the validator strip.

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
	"attribute": "acl",                     # optional — see below
	"patch":     {"acl": null},             # optional — see below
} if {
	resource := input.ir.resources[_]
	# ...
}
```

`attribute` and `patch` are what make a violation actionable without a model
round. Naming the `desired_state` key lets the router tell a rule contradicting
something the human asked for from one revealing an omission nobody thought
about; naming the fix lets it be offered as a before → after diff the human can
take or refuse. A `patch` value of `null` means *remove the key*. Rules about
the compiler's own invariants name neither — there is nothing on the node to
change. See `orchestrator/intent.py`.

For a plan-grounded rule, go through a guarded helper so it is undefined rather
than wrong when the plan did not run:

```rego
plan_resources := input.plan.resources if {
	input.plan != null
}
```

`severity` decides behaviour, not just presentation: an `error` enters the
repair loop and is handed to the Architect as a counterexample; a `warning` is
carried to the human untouched. Spending a model round on a warning is how a
repair loop starts to oscillate.

## Current rules

| File | Rules | Catches |
|---|---|---|
| `encryption_at_rest.rego` | `rds_storage_encrypted` (error), `ebs_root_encrypted` (error), `dynamodb_encryption` (warning) | Unencrypted databases and root volumes; tables on the AWS-owned key. |
| `no_public_s3.rego` | `s3_public_acl` (error), `s3_missing_public_access_block` (error), `s3_versioning` (warning) | A public ACL contradicting the compiler's public access block; a bucket whose block is missing or not fully restrictive; unrecoverable buckets. |
| `tagging.rego` | `missing_default_tags` (error) | A taggable resource not carrying the project's default tags. |
| `data_residency.rego` | `region_not_allowed` (error) | A project region outside its own `allowed_regions`. |
| `plan_grounded.rego` | `plan_default_tags_resolved` (error), `plan_value_unknown_until_apply` (warning) | A tag the provider will resolve to something other than the project default; a security switch Terraform cannot know before apply. **Runs only when the plan ran.** |

Three of these check that the compiler's own compliance work is intact -
`s3_missing_public_access_block`, `ebs_root_encrypted`, `missing_default_tags`.
They should never fire on a graph this compiler produced, which is the point:
they are the regression test for a registry entry silently losing its
`companion_resources`, `static_blocks` or `taggable` flag.

`s3_public_acl` is the one worth understanding. The compiler attaches an
`aws_s3_bucket_public_access_block` to every bucket, so a public ACL is not a
risk here but a *contradiction* — AWS provider v4+ fails the apply. That is
precisely the research case: a human makes a visual change ("make this bucket
public") that collides with a constraint only the compiler knows about. The
rule is what lets the canvas say so before an apply fails.

`plan_default_tags_resolved` is the one that shows why both views are kept. On
a graph where a node sets `Owner = "platform-team"`, the IR rules pass — the
expression still composes `local.default_tags`, which is all `tagging.rego` can
check — and the plan rule fails, because `tags_all` resolves to the node's
value. Same graph, same policy set, two different verdicts, and only one of
them is about what will exist.
