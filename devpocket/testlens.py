"""Read saved JUnit XML evidence without running tests or exposing log bodies."""
from __future__ import annotations

from collections import defaultdict
import hashlib
import io
from pathlib import PurePosixPath
import re
import xml.etree.ElementTree as ET

from .common import redact
from .inputs import read_text
from .sdk import Finding, ToolResult

MAX_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_ELEMENTS = 100000
MAX_CASES = 20000


def _label(value):
    return re.sub(r"[\x00-\x1f\x7f]", " ", redact(value))[:160]


def _records(text, path):
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, re.I):
        raise ValueError("JUnit XML cannot contain DTDs or entity declarations")
    declaration = re.match(r"\s*<\?xml\s+[^?]*encoding\s*=\s*['\"]([^'\"]+)", text, re.I)
    if declaration and declaration[1].lower() not in {"utf-8", "utf8", "us-ascii", "ascii"}:
        raise ValueError("JUnit XML must declare UTF-8 or ASCII encoding")
    records, stack, suites = [], [], []
    case = None
    count = 0
    try:
        for event, node in ET.iterparse(io.StringIO(text), events=("start", "end")):
            tag = node.tag.rsplit("}", 1)[-1]
            if event == "start":
                parent = stack[-1] if stack else None
                stack.append(tag)
                count += 1
                if len(stack) > 64 or count > MAX_ELEMENTS:
                    raise ValueError("JUnit XML exceeds its element/depth limit")
                if parent is None and tag not in {"testsuites", "testsuite"}:
                    raise ValueError("JUnit XML requires a testsuite or testsuites root")
                if tag in {"testsuites", "testsuite"}:
                    if case is not None or parent not in {None, "testsuites", "testsuite"}:
                        raise ValueError("Invalid JUnit suite nesting")
                    declared = {}
                    for key in ("tests", "failures", "errors", "skipped"):
                        if key in node.attrib:
                            value = node.attrib[key]
                            if not re.fullmatch(r"[0-9]{1,8}", value):
                                raise ValueError("JUnit counters must be bounded non-negative integers")
                            declared[key] = int(value)
                    suites.append({"declared": declared, "tests": 0, "failures": 0, "errors": 0, "skipped": 0})
                elif tag == "testcase":
                    if case is not None or parent != "testsuite" or not node.get("name"):
                        raise ValueError("JUnit testcase requires a name and a direct testsuite parent")
                    name, group = node.get("name"), node.get("classname", "")
                    identity = hashlib.sha256((group + "\0" + name).encode()).hexdigest()
                    state, result = node.get("status"), node.get("result")
                    if state not in {None, "run", "notrun"} or result not in {None, "completed", "skipped", "suppressed"}:
                        raise ValueError("Unsupported JUnit testcase status/result dialect; outcomes cannot be inferred safely")
                    markers = {"skipped"} if state == "notrun" or result in {"skipped", "suppressed"} else set()
                    case = {"identity": identity, "label": _label((group + "::" if group else "") + name), "path": path, "markers": markers}
                elif tag in {"failure", "error", "skipped"}:
                    if case is None or parent != "testcase":
                        raise ValueError("JUnit outcome markers require a direct testcase parent")
                    case["markers"].add(tag)
            else:
                if tag == "testcase":
                    markers = case.pop("markers")
                    if len(markers) > 1:
                        raise ValueError("JUnit testcase has conflicting outcome markers")
                    case["outcome"] = next(iter(markers), "passed")
                    records.append(case)
                    if len(records) > MAX_CASES:
                        raise ValueError("JUnit XML exceeds 20,000 testcase records")
                    suites[-1]["tests"] += 1
                    counter = {"failure": "failures", "error": "errors", "skipped": "skipped"}.get(case["outcome"])
                    if counter:
                        suites[-1][counter] += 1
                    case = None
                elif tag in {"testsuites", "testsuite"}:
                    suite = suites.pop()
                    if any(suite[key] != value for key, value in suite["declared"].items()):
                        raise ValueError("JUnit declared counters do not match testcase records; evidence is incomplete")
                    if suites:
                        for key in ("tests", "failures", "errors", "skipped"):
                            suites[-1][key] += suite[key]
                stack.pop()
                node.clear()
    except ET.ParseError:
        raise ValueError("Malformed JUnit XML; input content withheld") from None
    return records


def inspect(context, params):
    paths = params["paths"]
    if len({str(PurePosixPath(path)) for path in paths}) != len(paths):
        raise ValueError("JUnit input paths must be unique")
    records, total_bytes = [], 0
    for path in paths:
        text = read_text(context.root, path, MAX_BYTES)
        total_bytes += len(text.encode("utf-8"))
        if total_bytes > MAX_TOTAL_BYTES:
            raise ValueError("Combined JUnit inputs exceed 16 MiB")
        records.extend(_records(text, path))
        if len(records) > MAX_CASES:
            raise ValueError("Combined JUnit inputs exceed 20,000 testcase records")
    grouped = defaultdict(list)
    for record in records:
        grouped[record["identity"]].append(record)
    failures = sum(row["outcome"] == "failure" for row in records)
    errors = sum(row["outcome"] == "error" for row in records)
    skipped = sum(row["outcome"] == "skipped" for row in records)
    mixed = 0
    findings = []
    for identity, rows in sorted(grouped.items()):
        bad = [row for row in rows if row["outcome"] in {"failure", "error"}]
        if bad:
            findings.append(Finding("test-failed", f"{rows[0]['label']} [{identity[:12]}]: {len(bad)} failing record(s)", "error", bad[0]["path"], help="Failure messages, stack traces and captured stdout/stderr are withheld. Inspect the original XML locally."))
        if len({row["outcome"] for row in rows}) > 1:
            mixed += 1
            findings.append(Finding("test-mixed-outcomes", f"{rows[0]['label']} [{identity[:12]}] has mixed recorded outcomes", "warning", rows[0]["path"], help="Retries, separate runs or duplicate test names can explain this; it does not establish flakiness."))
    minimum = params.get("min_tests", 1)
    too_few = len(records) < minimum
    if too_few:
        findings.append(Finding("test-count-budget", f"Found {len(records)} testcase records; at least {minimum} required", "error"))
    skip_limit = params.get("max_skipped")
    too_many_skips = skip_limit is not None and skipped > skip_limit
    if too_many_skips:
        findings.append(Finding("test-skipped-budget", f"Found {skipped} skipped records; at most {skip_limit} allowed", "error"))
    data = {"files": len(paths), "tests": len(records), "passed": len(records) - failures - errors - skipped, "failures": failures, "errors": errors, "skipped": skipped, "identities": len(grouped), "repeated_identities": sum(len(rows) > 1 for rows in grouped.values()), "mixed_outcomes": mixed, "min_tests": minimum, "max_skipped": skip_limit, "bodies": "withheld", "interpretation": "Counts describe XML testcase records, including retries and duplicates; no tests were executed."}
    # Failed tests and configured count gates are operational evidence: a finding
    # baseline must not turn them into a passing test run.
    return ToolResult(f"JUnit evidence: {len(records)} records, {failures} failures, {errors} errors, {skipped} skipped", findings, data, exit_code=int(bool(failures or errors or too_few or too_many_skips)))


def execute(args):
    from .engine import execute as run, gated_exit
    from .reports import render
    import json
    params = {"paths": args.paths, "min_tests": args.min_tests}
    if args.max_skipped is not None:
        params["max_skipped"] = args.max_skipped
    report = run("testlens", params, args.root)
    print(json.dumps(report, indent=2) if args.json else render(report), end="\n" if args.json else "")
    return gated_exit(report)
