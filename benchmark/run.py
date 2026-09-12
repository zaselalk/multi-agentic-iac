"""
The benchmark, as a command.

    python -m benchmark.run                 # full configuration only
    python -m benchmark.run --ablate        # every row of the ablation table
    python -m benchmark.run --json out.json # machine-readable, for a re-run diff

It refuses to report anything if the corpus is not clean first. A base graph
that already violates something makes every number measured against it the sum
of two effects, so that check is the precondition rather than a nicety.
"""

import argparse
import json
import sys
from collections import defaultdict
from typing import Any, Dict, List

from .corpus import CORPUS
from .faults import FAULTS
from .harness import ABLATIONS, Config, Runner


def _rate(values: List[bool]) -> str:
    if not values:
        return "—"
    return f"{100 * sum(values) / len(values):.0f}% ({sum(values)}/{len(values)})"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Seeded-fault benchmark (G7, part 1).")
    parser.add_argument("--ablate", action="store_true", help="run every ablation row")
    parser.add_argument("--json", metavar="PATH", help="write full results as JSON")
    parser.add_argument("--fault", action="append", help="only these fault classes")
    parser.add_argument(
        "--model", action="store_true",
        help="use the real Architect for repair rounds. Costs money and is not "
             "reproducible; without it the repair columns read as 'not measured' "
             "rather than as zero.",
    )
    args = parser.parse_args(argv)

    configs = ABLATIONS if args.ablate else [Config("full")]
    faults = args.fault or list(FAULTS)

    results: List[Dict[str, Any]] = []
    baselines: List[Dict[str, Any]] = []

    with Runner(use_model=args.model) as runner:
        # --- the precondition ------------------------------------------
        print("Corpus baseline (no fault injected)")
        for graph_name in CORPUS:
            for deploy in (False, True):
                report = runner.baseline(graph_name, Config("full"), deploy)
                report["deploy"] = deploy
                baselines.append(report)
        dirty = [b for b in baselines if not b["clean"]]
        for b in baselines:
            mark = "ok " if b["clean"] else "DIRTY"
            plan = "with plan" if b["deploy"] else "IR only "
            print(f"  {mark}  {b['graph']:<16} {plan}  {b['findings'] or ''}")
        if dirty:
            print("\nRefusing to score: the corpus is not clean, so every number "
                  "below would be the sum of two effects.", file=sys.stderr)
            return 1

        # --- the cases -------------------------------------------------
        print("\nCases")
        for config in configs:
            for fault_name in faults:
                for graph_name in CORPUS:
                    case = runner.case(fault_name, graph_name, config)
                    if case:
                        results.append(case)
            done = [r for r in results if r["config"] == config.name]
            print(f"  {config.name:<14} {len(done)} cases")

        model = runner.model

    _report(results, configs, model)

    if args.json:
        with open(args.json, "w") as handle:
            json.dump(
                {"model": model or None, "baselines": baselines, "results": results},
                handle, indent=2,
            )
        print(f"\nWrote {args.json}")
    return 0


def _report(results: List[Dict[str, Any]], configs: List[Config], model: str = "") -> None:
    full = [r for r in results if r["config"] == "full"]

    print("\n\n## Detection and attribution, full configuration\n")
    print(
        "Architect: " + (f"`{model}`" if model else "stubbed (deterministic; no model called)")
    )
    print(
        "\n`Fix offered` is a deterministic patch put on the table, computed from "
        "the violated rule with no model call.\n"
        "`Repaired` is a silent fix by the repair loop"
        + ("." if model else ", which needs `--model` to measure and reads as 0 here.")
    )
    print("\n| Fault | Validator | Cases | Detection | Attribution | Fix offered | Repaired | Nodes touched | Model rounds |")
    print("|---|---|---|---|---|---|---|---|---|")

    by_fault: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in full:
        by_fault[row["fault"]].append(row)

    for fault_name in FAULTS:
        rows = by_fault.get(fault_name)
        if not rows:
            continue
        attributable = [r["attributed"] for r in rows if r["attributed"] is not None]
        touched = sum(len(r["nodes_touched"]) for r in rows)
        calls = sum(r["model_rounds"] for r in rows)
        print(
            f'| `{fault_name}` | {rows[0]["validator"]} | {len(rows)} '
            f'| {_rate([r["detected"] for r in rows])} '
            f'| {_rate(attributable) if attributable else "n/a"} '
            f'| {_rate([r["offered"] for r in rows])} '
            f'| {_rate([r["repaired"] for r in rows])} '
            f'| {touched} | {calls} |'
        )

    attributable = [r["attributed"] for r in full if r["attributed"] is not None]
    print(
        f'| **all** | | **{len(full)}** '
        f'| **{_rate([r["detected"] for r in full])}** '
        f'| **{_rate(attributable)}** '
        f'| **{_rate([r["offered"] for r in full])}** '
        f'| **{_rate([r["repaired"] for r in full])}** '
        f'| **{sum(len(r["nodes_touched"]) for r in full)}** '
        f'| **{sum(r["model_rounds"] for r in full)}** |'
    )

    touched = sum(len(r["nodes_touched"]) for r in full)
    beyond = sum(
        len([n for n in r["nodes_touched"] if n not in (r.get("faulted") or [])])
        for r in full
    )
    print(
        f"\n**Nodes touched: {touched}**, of which {beyond} beyond the faulted node. "
        "Every fault here is *in* the graph, so by the presence rule in "
        "`orchestrator/intent.py` a **policy** objecting to one is held and "
        "offered rather than reversed - those cases should touch nothing at all. "
        "Schema errors are still repaired, and those are what the count is."
    )

    print(
        "\n**On the detection column.** Every fault here is one this system has a "
        "validator for, so a high detection rate is the expected result rather "
        "than a finding - a benchmark of a system against its own feature list "
        "cannot be surprised. The columns that carry information are "
        "**attribution** (a validator firing is not the same as it pointing at "
        "the right place), the **ablation** table below (which component is "
        "actually load-bearing for which fault), and **collateral** (what else "
        "the fault set off). Detection becomes informative only when the corpus "
        "grows faults nobody designed a rule for."
    )

    collateral = [r for r in full if r["collateral"]]
    print(f"\nCollateral findings (alarms the fault caused beyond its own): "
          f"{len(collateral)} of {len(full)} cases.")
    for row in collateral[:8]:
        print(f"  {row['fault']} / {row['graph']}: {', '.join(row['collateral'])}")

    if len(configs) > 1:
        print("\n\n## Ablation — detection rate per fault class\n")
        names = [c.name for c in configs]
        print("| Fault | " + " | ".join(names) + " |")
        print("|---" * (len(names) + 1) + "|")
        for fault_name in FAULTS:
            cells = []
            for name in names:
                rows = [r for r in results
                        if r["fault"] == fault_name and r["config"] == name]
                cells.append(_rate([r["detected"] for r in rows]) if rows else "—")
            if any(cell != "—" for cell in cells):
                print(f"| `{fault_name}` | " + " | ".join(cells) + " |")

        print("\n\n## Ablation — fix-offered rate\n")
        print("| Fault | " + " | ".join(names) + " |")
        print("|---" * (len(names) + 1) + "|")
        for fault_name in FAULTS:
            cells = []
            for name in names:
                rows = [r for r in results
                        if r["fault"] == fault_name and r["config"] == name]
                cells.append(_rate([r["offered"] for r in rows]) if rows else "—")
            if any(cell != "—" for cell in cells):
                print(f"| `{fault_name}` | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    sys.exit(main())
