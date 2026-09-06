# Default tags on every taggable resource.
#
# MACOG lists tagging alongside least privilege, encryption at rest and
# restricted ingress as what its Security Prover checks. It was the one of the
# four that could not be written here until G1: the compiler merges
# local.default_tags into every taggable resource on emission, and that never
# reached the IR.
#
# The IR holds `tags` as the raw Terraform expression rather than a resolved
# map, because that is what the HCL says. The compliance property is that the
# expression composes the project's defaults - not what any one value is.

package visor.tagging

import rego.v1

# Resource types the registry marks taggable. Kept here rather than derived,
# because a policy asserting "these must be tagged" should not read its own
# expectations out of the thing it is checking.
taggable := {
	"aws_vpc",
	"aws_subnet",
	"aws_instance",
	"aws_db_instance",
	"aws_s3_bucket",
	"aws_lambda_function",
	"aws_dynamodb_table",
	"aws_sqs_queue",
}

deny contains {
	"node_id": resource.node_id,
	"rule": "missing_default_tags",
	"message": sprintf("%s.%s does not carry the project's default tags.", [resource.type, resource.name]),
	"severity": "error",
	"fix_hint": "Every taggable resource should emit tags = merge(local.default_tags, ...). If it does not, the registry entry has lost taggable: true.",
} if {
	resource := input.ir.resources[_]
	taggable[resource.type]
	not contains(object.get(resource, ["attributes", "tags"], ""), "local.default_tags")
}
