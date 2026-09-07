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
	# Named so the router can tell "the human asked for this" from "nobody
	# mentioned it", and so the fix can be offered as a diff without a model
	# round. See orchestrator/intent.py.
	"attribute": "storage_encrypted",
	"patch": {"storage_encrypted": true},
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

# Reachable only since G1. `root_block_device` is a static_block the compiler
# appends to the emitted HCL; it never reached the IR while the IR was built
# alongside emission rather than parsed out of it.
deny contains {
	"node_id": resource.node_id,
	"rule": "ebs_root_encrypted",
	"message": sprintf("%s.%s has an unencrypted root volume.", [resource.type, resource.name]),
	"severity": "error",
	"fix_hint": "The compiler normally emits root_block_device { encrypted = true }. If it is missing, the registry entry for ec2 has lost its static_blocks.",
} if {
	resource := input.ir.resources[_]
	resource.type == "aws_instance"
	not resource.attributes.root_block_device.encrypted == true
}
