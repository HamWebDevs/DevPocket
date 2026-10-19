"""Baselines and text, Markdown, JSON and SARIF 2.1.0 renderers."""
from __future__ import annotations
import json
from pathlib import Path
from urllib.parse import quote

from .common import load_json, write_json


def key(tool, finding):
    return tool + ":" + finding["fingerprint"]


def apply_baseline(report, filename):
    if not filename:
        return report
    baseline = load_json(Path(filename))
    if not isinstance(baseline, dict) or baseline.get("schema") != 1 or not isinstance(baseline.get("fingerprints"), list) or any(not isinstance(x, str) for x in baseline["fingerprints"]):
        raise ValueError("Expected baseline schema 1 with a fingerprints array")
    known = set(baseline["fingerprints"])
    seen = set()
    for finding in report.get("findings", []):
        identity = key(finding.get("tool", report["tool"]), finding)
        seen.add(identity)
        finding["existing"] = identity in known
    report["baseline"] = {"existing": sum(f.get("existing", False) for f in report.get("findings", [])), "new": sum(not f.get("existing", False) for f in report.get("findings", [])), "absent": len(known - seen)}
    return report


def create_baseline(source, target):
    report = load_json(Path(source))
    if not isinstance(report, dict) or report.get("schema") != 1 or not isinstance(report.get("findings"), list) or not isinstance(report.get("tool"), str):
        raise ValueError("Expected a DevPocket JSON report")
    fingerprints = sorted({key(f.get("tool", report["tool"]), f) for f in report["findings"]})
    write_json(Path(target), {"schema": 1, "fingerprints": fingerprints})
    return len(fingerprints)


def sarif(report):
    rules = {}
    results = []
    for f in report.get("findings", []):
        rule = f.get("tool", report["tool"]) + "/" + f["rule"]
        rules.setdefault(rule, {"id": rule, "shortDescription": {"text": f["rule"]}})
        result = {"ruleId": rule, "level": f["severity"], "message": {"text": f["message"]}, "partialFingerprints": {"devpocket/v1": f["fingerprint"]}}
        if f.get("path"):
            location = {"artifactLocation": {"uri": quote(f["path"], safe="/")}}
            if f.get("line"):
                location["region"] = {"startLine": f["line"]}
            result["locations"] = [{"physicalLocation": location}]
        if "existing" in f:
            result["baselineState"] = "unchanged" if f["existing"] else "new"
        if f.get("project"):
            result["properties"] = {key: f[key] for key in ("project", "check") if key in f}
        results.append(result)
    invocation = {"executionSuccessful": report.get("status") != "error" and all(s["report"].get("status") != "error" for s in report.get("checks", []))}
    if report.get("tool") in {"workspace", "workspace-plan"}:
        plan = report.get("data", {})
        invocation["properties"] = {"workspaceScope": plan.get("scope"), "planSha256": plan.get("plan_sha256"), "selectedProjects": [p["name"] for p in plan.get("projects", []) if p["selected"]], "unselectedProjects": [p["name"] for p in plan.get("projects", []) if not p["selected"]]}
    return {"$schema": "https://json.schemastore.org/sarif-2.1.0.json", "version": "2.1.0", "runs": [{"tool": {"driver": {"name": "DevPocket", "version": report["version"], "informationUri": "https://github.com/HamWebDevs/DevPocket", "rules": list(rules.values())}}, "results": results, "invocations": [invocation]}]}


def render(report, format="text"):
    if format == "json":
        return json.dumps(report, indent=2, allow_nan=False) + "\n"
    if format == "sarif":
        return json.dumps(sarif(report), indent=2, allow_nan=False) + "\n"
    lines = [f"DevPocket: {report['tool']}", report["summary"]]
    for step in report.get("checks", []):
        cached = step['report'].get('cache')
        annotation = f"; cache {cached['status']}" if cached else ""
        lines.append(f"{step['name']}: {step['status']} ({step['report']['summary']}{annotation})")
    for finding in report.get("findings", []):
        where = finding.get("path", "") + (":" + str(finding["line"]) if finding.get("line") else "")
        state = " [existing]" if finding.get("existing") else ""
        lines.append(f"{where} [{finding['severity']}] {finding['rule']}{state}: {finding['message']}")
        if finding.get("help"):
            lines.append("  " + finding["help"])
    if "baseline" in report:
        lines.append(f"Baseline: {report['baseline']['new']} new, {report['baseline']['existing']} existing, {report['baseline']['absent']} absent")
    if not report.get("findings") and report.get("data"):
        lines.append(json.dumps(report["data"], indent=2, allow_nan=False))
    text = "\n".join(lines)
    if format == "markdown":
        # A variable fence prevents plugin output from breaking the report layout.
        import re
        fence = "`" * max(3, 1 + max((len(m) for m in re.findall(r"`+", text)), default=0))
        return "# DevPocket report\n\n" + fence + "text\n" + text + "\n" + fence + "\n"
    return text + "\n"
