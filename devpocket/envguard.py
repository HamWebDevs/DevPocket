"""Compare dotenv names without evaluating or returning their values."""
from __future__ import annotations

import re

from .inputs import read_text
from .sdk import Finding, ToolResult

MAX_BYTES = 512 * 1024
MAX_KEYS = 1024
MAX_LINES = 20000
KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}\Z", re.ASCII)
ASSIGNMENT = re.compile(r"(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]{0,127})[ \t]*=", re.ASCII)


def _closing(text, quote):
    escaped = False
    for position, character in enumerate(text):
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == quote:
            return position
    return None


def _names(text, path):
    names, findings = {}, []
    quote, started = None, None
    lines = text.splitlines()
    if len(lines) > MAX_LINES:
        raise ValueError("Dotenv input exceeds 20,000 lines")
    for line, raw in enumerate(lines, 1):
        if quote is not None:
            closing = _closing(raw, quote)
            if closing is None:
                continue
            tail = raw[closing + 1:].strip()
            quote = None
            if tail and not tail.startswith("#"):
                findings.append(Finding("env-syntax", "Unexpected content after a quoted value; values withheld", "error", path, line))
            continue
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        match = ASSIGNMENT.match(value)
        if not match:
            findings.append(Finding("env-syntax", "Expected a NAME=value assignment; content withheld", "error", path, line))
            continue
        key = match[1]
        if key in names:
            findings.append(Finding("env-duplicate", f"Environment name {key} is assigned more than once", "warning", path, line))
        remainder = value[match.end():].lstrip()
        empty = not remainder or remainder.startswith("#")
        if remainder[:1] in {"'", '"'}:
            closing = _closing(remainder[1:], remainder[0])
            if closing is None:
                quote, started = remainder[0], line
                empty = False
            else:
                tail = remainder[closing + 2:].strip()
                if tail and not tail.startswith("#"):
                    findings.append(Finding("env-syntax", "Unexpected content after a quoted value; values withheld", "error", path, line))
                empty = closing == 0
        names[key] = {"line": line, "empty": empty}
        if len(names) > MAX_KEYS or len(findings) > MAX_KEYS:
            raise ValueError("Dotenv input exceeds the 1,024-name/finding limit")
    if quote is not None:
        findings.append(Finding("env-syntax", "Unterminated quoted value; content withheld", "error", path, started))
    return names, findings


def inspect(context, params):
    example, target = params.get("example", ".env.example"), params.get("env", ".env")
    ignored = set(params.get("ignore", []))
    if any(not KEY.fullmatch(key) for key in ignored):
        raise ValueError("Ignored environment names must be valid NAME identifiers")
    expected, findings = _names(read_text(context.root, example, MAX_BYTES), example)
    actual, issues = _names(read_text(context.root, target, MAX_BYTES), target)
    findings.extend(issues)
    wanted, present = set(expected) - ignored, set(actual) - ignored
    missing, extra = sorted(wanted - present), sorted(present - wanted)
    empty = sorted(key for key in wanted & present if actual[key]["empty"])
    for key in missing:
        findings.append(Finding("env-missing", f"Required environment name {key} is absent from the target", "error", example, expected[key]["line"]))
    for key in empty:
        findings.append(Finding("env-empty", f"Required environment name {key} has an empty value", "error", target, actual[key]["line"]))
    if not params.get("allow_extra", False):
        for key in extra:
            findings.append(Finding("env-extra", f"Environment name {key} is undocumented in the example", "warning", target, actual[key]["line"]))
    if not wanted:
        findings.append(Finding("env-no-reference", "The example defines no non-ignored environment names", "error", example))
    data = {"example": example, "env": target, "reference_names": len(wanted), "target_names": len(present), "missing": len(missing), "empty": len(empty), "extra": len(extra), "values": "withheld"}
    return ToolResult(f"Environment names: {len(missing)} missing, {len(empty)} empty, {len(extra)} undocumented; values withheld", findings, data)


def execute(args):
    from .engine import execute as run, gated_exit
    from .reports import render
    import json
    report = run("envguard", {"example": args.example, "env": args.env, "ignore": args.ignore, "allow_extra": args.allow_extra}, args.root)
    print(json.dumps(report, indent=2) if args.json else render(report), end="\n" if args.json else "")
    return gated_exit(report)
