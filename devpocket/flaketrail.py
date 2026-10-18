"""Repeat a command, retain bounded evidence, compare pass/fail runs."""
from __future__ import annotations
import difflib
from pathlib import Path
import statistics

from .common import redact, run, write_json


def execute(args):
    if not 2 <= args.runs <= 1000:
        raise ValueError("Runs must be between 2 and 1000")
    records = []
    for index in range(args.runs):
        result = run(args.command, cwd=args.root, timeout=args.timeout)
        result["stdout"] = redact(result["stdout"])
        result["stderr"] = redact(result["stderr"])
        result["run"] = index + 1
        records.append(result)
        state = "PASS" if result["returncode"] == 0 else "FAIL"
        print(f"{index + 1}/{args.runs} {state} ({result['seconds']:.3f}s)")
    passed = [r for r in records if r["returncode"] == 0]
    failed = [r for r in records if r["returncode"] != 0]
    comparison = []
    if passed and failed:
        a, b = passed[0], failed[0]
        comparison = list(difflib.unified_diff((a["stdout"] + a["stderr"]).splitlines(), (b["stdout"] + b["stderr"]).splitlines(), fromfile=f"pass-{a['run']}", tofile=f"fail-{b['run']}", lineterm=""))[:200]
    summary = {"passes": len(passed), "failures": len(failed), "mixed_outcomes": bool(passed and failed), "pass_median_seconds": statistics.median(r["seconds"] for r in passed) if passed else None, "fail_median_seconds": statistics.median(r["seconds"] for r in failed) if failed else None}
    write_json(Path(args.output), {"schema": 1, "command": [redact(a) for a in args.command], "summary": summary, "first_pass_fail_diff": comparison, "runs": records})
    print(f"{len(passed)} passed, {len(failed)} failed. Report: {args.output}")
    if comparison:
        print("\n".join(comparison))
    print("Evidence covers exit status, output and wall time; it does not establish a root cause.")
    return 1 if failed else 0
