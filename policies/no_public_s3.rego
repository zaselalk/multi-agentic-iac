# Public exposure of object storage.
#
# The compiler already attaches an aws_s3_bucket_public_access_block companion
# to every bucket, so a public ACL is not merely a risk here - it is a
# contradiction. AWS provider v4+ rejects the apply outright when an ACL is set
# on a bucket whose public access block is on.
#
# That contradiction is the interesting case for this research: it is exactly a
# human visual edit ("make this bucket public") colliding with a constraint the
# compiler enforces and the human cannot see. Catching it here is what lets the
# canvas say so before an apply fails.

package visor.no_public_s3

import rego.v1

public_acls := {"public-read", "public-read-write", "authenticated-read"}

deny contains {
	"node_id": resource.node_id,
	"rule": "s3_public_acl",
	"message": sprintf("%s.%s sets acl=%q, which conflicts with the public access block the compiler attaches to every bucket.", [resource.type, resource.name, resource.attributes.acl]),
	"severity": "error",
	"fix_hint": "Remove the acl attribute. Grant access with a bucket policy or CloudFront origin access control instead.",
} if {
	resource := input.ir.resources[_]
	resource.type == "aws_s3_bucket"
	public_acls[resource.attributes.acl]
}

deny contains {
	"node_id": resource.node_id,
	"rule": "s3_versioning",
	"message": sprintf("%s.%s has versioning suspended.", [resource.type, resource.name]),
	"severity": "warning",
	"fix_hint": "Enable versioning so an accidental delete is recoverable.",
} if {
	resource := input.ir.resources[_]
	resource.type == "aws_s3_bucket"
	resource.attributes.versioning_status == "Suspended"
}
