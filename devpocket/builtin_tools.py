"""SDK adapters; original command-line interfaces remain compatible."""
from __future__ import annotations
from contextlib import ExitStack
import gzip
import json
from pathlib import Path
from types import SimpleNamespace

from . import assetguard, envtwin, flaketrail, importdoctor, loglens, oopsfile, reporadar, undorun
from .common import load_json
from .sdk import Finding, ToolResult, ToolSpec


def obj(properties=None, required=()):
    return {"type": "object", "properties": properties or {}, "required": list(required), "additionalProperties": False}


def string(description=""):
    return {"type": "string", "description": description, "maxLength": 4096}


def radar(ctx, params):
    found = reporadar.scan(ctx.root)
    return ToolResult(f"{len(found)} repository findings", [Finding(f["code"], f["message"], path=f["path"] if f["path"] != "." else None, line=f["line"] or None) for f in found], {"findings_count": len(found)})


def environment(ctx, params):
    if params.get("action", "snapshot") == "snapshot":
        return ToolResult("Python environment captured without environment values", data=envtwin.snapshot())
    if not params.get("left") or not params.get("right"):
        raise ValueError("Environment diff requires left and right snapshot paths")
    changes = envtwin.compare(load_json(ctx.resolve(params["left"])), load_json(ctx.resolve(params["right"])))
    return ToolResult(f"{len(changes)} environment differences", [Finding("environment-difference", f"{x['section']}.{x['name']}: {x['left']!r} -> {x['right']!r}") for x in changes], {"changes": changes})


def imports(ctx, params):
    report = importdoctor.inspect_module(params["module"], ctx.root, params.get("distribution"), params.get("expect_python"))
    error_codes = {"local-shadow", "module-not-found", "distribution-not-installed", "interpreter-mismatch"}
    findings = [Finding(f["code"], f["message"], severity="error" if f["code"] in error_codes else "note", help=f["suggestion"]) for f in report["findings"]]
    return ToolResult(f"Static import diagnosis: {params['module']}", findings, report)


def logs(ctx, params):
    with ExitStack() as stack:
        inputs = []
        for name in params["paths"]:
            path = ctx.resolve(name)
            opener = gzip.open if path.suffix.lower() == ".gz" else open
            inputs.append((path.relative_to(ctx.root).as_posix(), stack.enter_context(opener(path, "rt", encoding="utf-8", errors="replace"))))
        report = loglens.analyse(inputs, exact=params.get("exact", False), include_all=params.get("all", False), max_groups=params.get("max_groups", 2000))
    findings = []
    for group in report["groups"]:
        if group["level"] not in {"ERROR", "CRITICAL", "WARNING"}:
            continue
        first = group["first_seen"]
        findings.append(Finding("log-" + group["level"].lower(), group["signature"], severity="warning" if group["level"] == "WARNING" else "error", path=first["source"], line=first["line"], help=f"{group['count']} occurrence(s); inspect samples and first/last evidence"))
    return ToolResult(f"{report['records_matched']} matching log events in {len(report['groups'])} groups", findings, report)


def command_tool(name, ctx, params):
    if not ctx.allow_exec:
        raise ValueError("Command-running tools require --allow-exec")
    base = dict(root=str(ctx.root), command=params["command"], timeout=params.get("timeout", 60))
    if name in {"oopsfile", "flaketrail"}:
        base["output"] = str(ctx.resolve(params["output"]))
    if name == "oopsfile":
        base.update(include_source=params.get("include_source", False), include_diff=params.get("include_diff", False))
        code = oopsfile.execute(SimpleNamespace(**base))
    elif name == "flaketrail":
        base["runs"] = params.get("runs", 10)
        code = flaketrail.execute(SimpleNamespace(**base))
    else:
        base.update(action="run", exclude=params.get("exclude", []))
        code = undorun.execute(SimpleNamespace(**base))
    return ToolResult(f"{name} completed with exit code {code}", data={"output": params.get("output"), "command_exit_code": code}, exit_code=code)


def assets(ctx, params):
    relative = params.get("path", "dist")
    if (ctx.root / relative).is_symlink():
        raise ValueError("Build root cannot be a symlink")
    path = ctx.resolve(relative)
    baseline = load_json(ctx.resolve(params["baseline"])) if params.get("baseline") else None
    report = assetguard.analyse(path, baseline=baseline, **{key: params[key] for key in ("public_path", "max_total_gzip_kib", "max_asset_gzip_kib", "max_growth_kib") if key in params})
    findings = []
    for item in report["findings"]:
        location = (path / item["path"]).relative_to(ctx.root).as_posix() if item.get("path") else None
        findings.append(Finding(item["rule"], item["message"], severity=item["severity"], path=location, line=item.get("line")))
    return ToolResult(f"Production build: {report['summary']['files']} assets, {report['summary']['gzip_bytes']} bytes gzip estimate", findings, report)


def specs():
    boolean = {"type": "boolean"}
    command = {"type": "array", "items": {"type": "string", "maxLength": 16384}, "minItems": 1, "maxItems": 256}
    common = {"command": command, "timeout": {"type": "number", "minimum": .01, "maximum": 3600}}
    result = [
        ToolSpec('config-validate', 'Validate project/workspace configuration without executing checks or importing plugins', obj({'config': string(), 'workspace': boolean}), configuration),
        ToolSpec("workspace-plan", "Inspect a multi-project dependency plan without running checks or importing plugins", obj({"manifest": string(), "projects": {"type": "array", "items": string(), "maxItems": 32}, "changed_files": {"type": "array", "items": string(), "maxItems": 4096}}), workspace_plan),
        ToolSpec("assetguard", "Audit a finished web build for missing resources, exposed files, duplicate content and size budgets", obj({"path": string("Finished build directory, relative to project root"), "public_path": string("Deployment URL prefix, e.g. /docs/"), "baseline": string("Previous AssetGuard snapshot"), **{key: {"type": "number", "minimum": 0, "maximum": 1048576} for key in ("max_total_gzip_kib", "max_asset_gzip_kib", "max_growth_kib")}}), assets),
        ToolSpec("reporadar", "Offline repository setup and documentation checks", obj(), radar),
        ToolSpec("envtwin", "Snapshot the reporting Python environment or compare saved snapshots", obj({"action": {"type": "string", "enum": ["snapshot", "diff"]}, "left": string(), "right": string()}), environment),
        ToolSpec("importdoctor", "Inspect import resolution without importing target modules", obj({"module": string(), "distribution": string(), "expect_python": string()}, ["module"]), imports),
        ToolSpec("loglens", "Group recurring events in root-contained text, JSONL and gzip logs", obj({"paths": {"type": "array", "items": string(), "minItems": 1, "maxItems": 64}, "exact": boolean, "all": boolean, "max_groups": {"type": "integer", "minimum": 1, "maximum": 10000}}, ["paths"]), logs, cache_version="loglens-v1"),
    ]
    for name in ("oopsfile", "flaketrail", "undorun"):
        props = dict(common)
        required = ["command"]
        if name != "undorun":
            props["output"] = string("Root-contained output filename; never overwritten")
            required.append("output")
        if name == "oopsfile":
            props.update(include_source=boolean, include_diff=boolean)
        if name == "flaketrail":
            props["runs"] = {"type": "integer", "minimum": 2, "maximum": 1000}
        if name == "undorun":
            props["exclude"] = {"type": "array", "items": string(), "maxItems": 100}
        result.append(ToolSpec(name, f"Run the {name} command (explicit execution opt-in required)", obj(props, required), lambda ctx, data, tool=name: command_tool(tool, ctx, data), read_only=False))
    return {tool.name: tool for tool in result}


def workspace_plan(ctx, params):
    from .workspace import compile_plan
    plan = compile_plan(ctx.root, params.get("manifest", ".devpocket-workspace.json"), params.get("projects", []), params.get("changed_files"))[0]
    return ToolResult(f"{len(plan['nodes'])} planned checks; {plan['scope']} workspace scope", data=plan)


def configuration(ctx, params):
    from .configuration import adapter
    return adapter(ctx, params)
