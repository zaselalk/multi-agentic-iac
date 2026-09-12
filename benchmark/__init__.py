"""
The seeded-fault benchmark (G7, part 1).

MACOG is measured on IaC-Eval: one prompt, one file, did it pass. This system
cannot be measured that way, and saying why is the first result rather than an
excuse. A human edits the artefact mid-run, so "solved on the first try" is not
a quantity the interaction admits, and the thing being claimed is not
generation quality but whether a violation is *found*, *addressed to the right
place on a diagram*, and *resolved without reversing what somebody asked for*.

So: take graphs that pass everything, inject exactly one known fault into each,
and measure what happens. Every fault has a defined right answer - which rule
should fire, on which node - so scoring needs no judgement and no model.

Four measures, and the second is the one nothing else in the literature
reports:

    detection      did a validator fire at all
    attribution    did the finding name the *right node* - measurable here
                   only because every counterexample carries a node_id, which
                   is the thing a text-first system has no need to produce
    remediation    was it fixed, or a concrete fix offered
    minimality     nodes touched beyond the faulted one

See benchmark/README.md for why `remediation` is not MACOG's `repair rate`,
and docs/FUTURE-WORK.md section A2 for where this sits in the plan.
"""
