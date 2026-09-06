# Encryption at rest.
#
# MACOG treats encrypt_at_rest as an effect on the plan that a validator later
# discharges (S4.3). Here the obligation is discharged against the compiler's
# IR, so a violation names the canvas node rather than a Terraform address.

package visor.encryption_at_rest

import rego.v1

deny contains {
	"node_id": resource.node_id,
	"rule": "rds_storage_encrypted",
	"message": sprintf("%s.%s stores data unencrypted at rest.", [resource.type, resource.name]),
	"severity": "error",
	"fix_hint": "Set storage_encrypted to true on this database node.",
} if {
	resource := input.ir.resources[_]
	resource.type == "aws_db_instance"
	not resource.attributes.storage_encrypted == true
}

deny contains {
	"node_id": resource.node_id,
	"rule": "dynamodb_encryption",
	"message": sprintf("%s.%s relies on the AWS-owned key rather than a managed CMK.", [resource.type, resource.name]),
	"severity": "warning",
	"fix_hint": "Add a server_side_encryption block with a customer-managed KMS key.",
} if {
	resource := input.ir.resources[_]
	resource.type == "aws_dynamodb_table"
	not resource.attributes.server_side_encryption
}
