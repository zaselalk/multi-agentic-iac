# Data residency.
#
# MACOG carries residency as a constraint C on the intent (S4.1, "residency=EU")
# and checks it as an effect. The equivalent input here is a project's own
# settings, which the human sets in the canvas - so this rule is the clearest
# example of a policy that a human can violate by changing something visual,
# and that no amount of correct Terraform would catch.
#
# Enforced only when a project declares allowed_regions in its settings:
#
#     { "region": "eu-west-1", "allowed_regions": ["eu-west-1", "eu-central-1"] }

package visor.data_residency

import rego.v1

# A separate rule, because `not <expr>[_] == x` is unsafe in Rego - the
# negation has to be over a complete definition, not over a comprehension var.
region_allowed if {
	input.settings.allowed_regions[_] == input.settings.region
}

deny contains {
	"node_id": "",
	"rule": "region_not_allowed",
	"message": sprintf("Project region %q is not in the allowed set %v.", [input.settings.region, input.settings.allowed_regions]),
	"severity": "error",
	"fix_hint": "Change the project region in settings, or widen allowed_regions.",
} if {
	count(input.settings.allowed_regions) > 0
	not region_allowed
}
