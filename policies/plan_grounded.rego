# Obligations that can only be discharged against a plan.
#
# Every other rule in this directory reads `input.ir` - what the compiler
# emitted. These read `input.plan` - what the AWS provider says will actually
# exist, with defaults expanded and expressions evaluated.
#
# The distinction is not academic. The IR holds
# `tags = merge(local.default_tags, ...)` because that is the text; the plan
# holds `tags_all = {"Owner": "visor", ...}` because that is the outcome. A
# resource-level tag quietly overriding a project default satisfies the IR rule
# in tagging.rego and is a live compliance failure, and nothing before the plan
# can see it.
#
# `input.plan` is null on turns where deploy validation is off, so every rule
# here goes through `plan_resources`, which is simply undefined then. A rule
# that proved nothing must not read as a rule that passed.

package visor.plan_grounded

import rego.v1

plan_resources := input.plan.resources if {
	input.plan != null
}

# Switches a security policy asserts on directly.
#
# Deliberately not the identifiers beside them: an encrypted database's
# `kms_key_id` is computed by AWS and unknown until apply on every compliant
# plan, so warning about it would fire on exactly the resources that are fine.
# `acl` is out for the same reason - provider v5 computes it on every
# aws_s3_bucket. What matters is a *decision* being unprovable, not a name
# being unassigned, and a rule that fires on healthy graphs teaches people to
# ignore it.
security_attributes := {
	"storage_encrypted",
	"encrypted",
	"block_public_acls",
	"block_public_policy",
	"ignore_public_acls",
	"restrict_public_buckets",
}

# --- the project's default tags, as the provider will resolve them ---------
deny contains {
	"node_id": resource.node_id,
	"rule": "plan_default_tags_resolved",
	"message": sprintf(
		"%s will be created with %s = %q, not the project default %q.",
		[resource.address, key, object.get(resource.values.tags_all, [key], "<absent>"), expected],
	),
	"severity": "error",
	"fix_hint": sprintf("Remove the %q tag from this node, or change the project's default_tags.", [key]),
	"attribute": "tags",
} if {
	resource := plan_resources[_]

	# Untaggable resources have no tags_all at all, and an empty one means the
	# provider has not expanded it - neither is a violation.
	count(object.get(resource, ["values", "tags_all"], {})) > 0

	some key, expected in input.settings.default_tags
	object.get(resource.values.tags_all, [key], "<absent>") != expected
}

# --- obligations that cannot be proved before apply -----------------------
deny contains {
	"node_id": resource.node_id,
	"rule": "plan_value_unknown_until_apply",
	"message": sprintf(
		"%s sets %s to a value Terraform cannot know until apply, so nothing can be proved about it beforehand.",
		[resource.address, attribute],
	),
	"severity": "warning",
	"fix_hint": "Give the attribute a literal value, or accept that this obligation is discharged only at apply time.",
	"attribute": attribute,
} if {
	resource := plan_resources[_]
	some attribute, unknown in resource.unknown
	security_attributes[attribute]
	unknown == true
}
