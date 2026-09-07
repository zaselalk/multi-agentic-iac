# Public exposure of object storage.
#
# The compiler attaches an aws_s3_bucket_public_access_block companion to every
# bucket, so a public ACL is not merely a risk here - it is a contradiction.
# AWS provider v4+ rejects the apply outright when an ACL is set on a bucket
# whose public access block is on.
#
# That contradiction is the interesting case for this research: it is exactly a
# human visual edit ("make this bucket public") colliding with a constraint the
# compiler enforces and the human cannot see.

package visor.no_public_s3

import rego.v1

public_acls := {"public-read", "public-read-write", "authenticated-read"}

deny contains {
	"node_id": resource.node_id,
	"rule": "s3_public_acl",
	"message": sprintf("%s.%s sets acl=%q, which conflicts with the public access block the compiler attaches to every bucket.", [resource.type, resource.name, resource.attributes.acl]),
	"severity": "error",
	"fix_hint": "Remove the acl attribute. Grant access with a bucket policy or CloudFront origin access control instead.",
	# A null patch value means "remove this key" rather than "set it to null".
	"attribute": "acl",
	"patch": {"acl": null},
} if {
	resource := input.ir.resources[_]
	resource.type == "aws_s3_bucket"
	public_acls[resource.attributes.acl]
}

# Reachable only since G1 - the public access block is a companion resource, and
# companions did not appear in the IR until the compiler started deriving the IR
# from what it emits. Before that this rule would have fired on every bucket.
blocked contains bucket_name if {
	block := input.ir.resources[_]
	block.type == "aws_s3_bucket_public_access_block"
	block.attributes.block_public_acls == true
	block.attributes.block_public_policy == true
	block.attributes.ignore_public_acls == true
	block.attributes.restrict_public_buckets == true
	bucket_name := block.attributes.bucket
}

deny contains {
	"node_id": resource.node_id,
	"rule": "s3_missing_public_access_block",
	"message": sprintf("%s.%s has no fully-restrictive aws_s3_bucket_public_access_block.", [resource.type, resource.name]),
	"severity": "error",
	"fix_hint": "The compiler normally attaches one. If it is missing, the bucket's registry entry has lost its companion_resources.",
} if {
	resource := input.ir.resources[_]
	resource.type == "aws_s3_bucket"
	not blocked[sprintf("aws_s3_bucket.%s.id", [resource.name])]
}

# Versioning now reads the companion rather than the primary's virtual
# `versioning_status`, which G1 removed from the IR because it was never
# emitted into the HCL.
versioned contains bucket_name if {
	versioning := input.ir.resources[_]
	versioning.type == "aws_s3_bucket_versioning"
	versioning.attributes.versioning_configuration.status == "Enabled"
	bucket_name := versioning.attributes.bucket
}

deny contains {
	"node_id": resource.node_id,
	"rule": "s3_versioning",
	"message": sprintf("%s.%s has no versioning enabled.", [resource.type, resource.name]),
	"severity": "warning",
	"fix_hint": "Set versioning to true on this bucket node so an accidental delete is recoverable.",
	"attribute": "versioning",
} if {
	resource := input.ir.resources[_]
	resource.type == "aws_s3_bucket"
	not versioned[sprintf("aws_s3_bucket.%s.id", [resource.name])]
}
