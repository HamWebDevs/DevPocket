"""Explicit multi-project plans and one bounded pool of isolated check workers."""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import threading
import time

from . import __version__
from .checks import invoke
from .common import write_text
from .engine import clean, failure, gated_exit
from .project import validate as validate_project
from .reports import apply_baseline, render
from .sdk import Finding, NAME

MAX_CONFIG = 256 * 1024
MAX_CHECKS = 256
MAX_REPORT = 8 * 1024 * 1024


def relative(value):
    if not isinstance(value, str) or not value or len(value) > 1024 or any(c in value for c in "\\:") or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Workspace paths must be printable relative POSIX paths")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ValueError("Workspace paths must be canonical and stay under their root")
    return value


def contained(root, value):
    relative(value)
    root = Path(root).resolve()
    path = root / value
    for component in (path, *path.parents):
        if component == root:
            break
        if component.is_symlink():
            raise ValueError("Workspace paths cannot pass through symlinks")
    if not path.resolve().is_relative_to(root):
        raise ValueError("Workspace path leaves its root")
    return path


def read_json(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("Workspace configuration must be a regular JSON file")
    with path.open("rb") as stream:
        payload = stream.read(MAX_CONFIG + 1)
    if len(payload) > MAX_CONFIG:
        raise ValueError("Workspace JSON exceeds 256 KiB")
    try:
        return json.loads(payload)
    except (ValueError, RecursionError) as exc:
        raise ValueError("Invalid workspace JSON") from exc


def under(path, prefix):
    return prefix == "." or path == prefix or path.startswith(prefix + "/")


def levels(nodes):
    remaining, done, result = set(nodes), set(), []
    while remaining:
        ready = [name for name, node in nodes.items() if name in remaining and set(node.get("needs", [])) <= done]
        if not ready:
            raise ValueError("Workspace dependencies contain a cycle")
        result.append(ready)
        remaining.difference_update(ready)
        done.update(ready)
    return result


def compile_plan(root, manifest=".devpocket-workspace.json", projects=(), changed=None):
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError("Workspace root must be an existing directory")
    config = read_json(contained(root, manifest))
    if not isinstance(config, dict) or set(config) - {"version", "projects", "shared_inputs"} or type(config.get("version")) is not int or config["version"] != 1:
        raise ValueError("Expected workspace version 1 with projects and optional shared_inputs")
    definitions = config.get("projects")
    if not isinstance(definitions, dict) or not 1 <= len(definitions) <= 32:
        raise ValueError("A workspace requires 1..32 projects")
    shared = config.get("shared_inputs", [])
    if not isinstance(shared, list) or len(shared) > 32:
        raise ValueError("shared_inputs must contain at most 32 relative paths")
    for value in shared:
        relative(value)
    configs, roots, paths, project_nodes = {}, {}, set(), {}
    for name, definition in definitions.items():
        if not isinstance(name, str) or not NAME.fullmatch(name) or not isinstance(definition, dict) or set(definition) - {"path", "config", "needs", "watch"}:
            raise ValueError("Invalid workspace project name or fields")
        path = relative(definition.get("path"))
        target = contained(root, path)
        if not target.is_dir() or target.resolve() in paths:
            raise ValueError("Project roots must be existing, distinct directories")
        paths.add(target.resolve())
        roots[name] = target
        needs = definition.get("needs", [])
        if not isinstance(needs, list) or len(needs) != len(set(x for x in needs if isinstance(x, str))) or any(not isinstance(x, str) or x not in definitions or x == name for x in needs):
            raise ValueError("Project dependencies must name other workspace projects once")
        watch = definition.get("watch", [])
        if not isinstance(watch, list) or len(watch) > 32:
            raise ValueError("Project watch must contain at most 32 relative workspace paths")
        for value in watch:
            relative(value)
        config_name = definition.get("config", ".devpocket.json")
        configs[name] = validate_project(read_json(contained(target, config_name)))
        if not configs[name]["checks"]:
            raise ValueError("Every workspace project must configure at least one check")
        project_nodes[name] = {"needs": needs}
    levels(project_nodes)
    if sum(len(c["checks"]) for c in configs.values()) > MAX_CHECKS:
        raise ValueError("A workspace may configure at most 256 checks")
    if not isinstance(projects, (list, tuple)) or any(not isinstance(name, str) or name not in definitions for name in projects):
        raise ValueError("Selected projects must exist in the workspace")
    if projects and changed is not None:
        raise ValueError("Choose explicit projects or changed-file selection, not both")
    reasons = {name: [] for name in definitions}
    if changed is not None:
        if not isinstance(changed, list) or len(changed) > 4096:
            raise ValueError("Changed files must be a list of at most 4096 relative paths")
        changed = sorted(set(relative(value) for value in changed))
        config_paths = {manifest, *(contained(root, d["path"]).joinpath(d.get("config", ".devpocket.json")).relative_to(root).as_posix() for d in definitions.values())}
        full = any(path in config_paths or any(under(path, value) for value in shared) for path in changed)
        for path in changed:
            owners = [name for name, definition in definitions.items() if under(path, definition["path"]) or any(under(path, value) for value in definition.get("watch", []))]
            if not owners:
                full = True
            for name in owners:
                if len(reasons[name]) < 8:
                    reasons[name].append("changed input: " + path)
        selected = set(definitions) if full else {name for name in definitions if reasons[name]}
        if full:
            for name in definitions:
                reasons[name].append("full run: configuration, shared or unmapped change")
        while True:
            added = {name for name, node in project_nodes.items() if set(node["needs"]) & selected} - selected
            if not added:
                break
            for name in added:
                reasons[name].append("depends on an affected project")
            selected.update(added)
    else:
        selected = set(projects) if projects else set(definitions)
        for name in selected:
            reasons[name].append("explicit project" if projects else "full workspace")
    while True:
        added = {dependency for name in selected for dependency in project_nodes[name]["needs"]} - selected
        if not added:
            break
        for name in added:
            reasons[name].append("required prerequisite")
        selected.update(added)
    nodes = {}
    for name, definition in definitions.items():
        if name not in selected:
            continue
        for check, step in configs[name]["checks"].items():
            dependencies = [name + "/" + dep for dep in step.get("needs", [])]
            dependencies.extend(dep + "/" + task for dep in definition.get("needs", []) for task in configs[dep]["checks"])
            nodes[name + "/" + check] = {"project": name, "check": check, "tool": step["tool"], "needs": dependencies}
    batches = levels(nodes)
    identity = {"version": __version__, "workspace": config, "configs": configs, "selected": sorted(selected), "changed": changed}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    public = {"manifest": manifest, "plan_sha256": digest, "scope": "full" if len(selected) == len(definitions) else "selected", "projects": [{"name": name, "path": definition["path"], "selected": name in selected, "needs": definition.get("needs", []), "reasons": reasons[name]} for name, definition in definitions.items()], "nodes": [{"name": name, **node} for name, node in nodes.items()], "levels": batches, "interpretation": "A plan describes selected checks and configuration, not a filesystem snapshot or plugin attestation. Selection runs affected dependents and prerequisites; unselected projects are not certified. Unmapped changes trigger a full run."}
    if len(json.dumps(public, allow_nan=False).encode()) > 1024 * 1024:
        raise ValueError("Workspace plan exceeds 1 MiB; reduce dependency fan-out or path lengths")
    return public, nodes, roots, configs


def relocate(report, project, prefix):
    report = copy.deepcopy(report)
    report.pop("baseline", None)
    for item in report.get("findings", []):
        path = str(PurePosixPath(prefix) / item["path"]) if item.get("path") else None
        Finding(item["rule"], item["message"], item["severity"], path, item.get("line"))
        if path:
            item["path"] = path
        item["fingerprint"] = hashlib.sha256(("workspace/v1\0" + project + "\0" + prefix + "\0" + item["fingerprint"]).encode()).hexdigest()
        item["tool"] = report["tool"]
        item["project"] = project
        item.pop("existing", None)
    return report


def check(root, manifest=".devpocket-workspace.json", *, projects=(), changed=None, jobs=4, allow_exec=False, fail_on="warning", baseline=None, use_cache=True, expect_plan=None):
    if type(jobs) is not int or not 1 <= jobs <= 8:
        raise ValueError("Workspace jobs must be between 1 and 8")
    plan, nodes, roots, configs = compile_plan(root, manifest, projects, changed)
    if expect_plan is not None and (not re.fullmatch(r"[a-f0-9]{64}", expect_plan) or expect_plan != plan["plan_sha256"]):
        raise ValueError("Workspace configuration or selection differs from the expected plan")
    apply_baseline({"tool": "workspace", "findings": []}, baseline)
    pending, finished, running = set(nodes), {}, {}
    cancelled = threading.Event()
    executor = ThreadPoolExecutor(max_workers=jobs)
    started, size, exhausted = time.monotonic(), 0, False
    try:
        while pending or running:
            for name, node in nodes.items():
                if name not in pending or len(running) >= jobs:
                    continue
                if not set(node["needs"]) <= finished.keys():
                    continue
                pending.remove(name)
                if exhausted or any(finished[dep]["status"] not in {"passed", "allowed_failure"} for dep in node["needs"]):
                    finished[name] = {"name": name, "project": node["project"], "status": "skipped", "report": failure(node["tool"], "Not run: workspace budget or prerequisite did not pass")}
                    continue
                project = node["project"]
                step = configs[project]["checks"][node["check"]]
                policy = step.get("cache") if use_cache else False if "cache" in step else None
                future = executor.submit(invoke, node["tool"], step.get("input", {}), roots[project], configs[project].get("plugins", []), allow_exec, step.get("timeout", 60), cancelled, policy)
                running[future] = name
            if not running:
                continue
            done, _ = wait(running, return_when=FIRST_COMPLETED)
            for future in done:
                name = running.pop(future)
                node = nodes[name]
                step = configs[node["project"]]["checks"][node["check"]]
                try:
                    report = relocate(future.result(), node["project"], str(roots[node["project"]].relative_to(Path(root).resolve())))
                    weight = len(json.dumps(report, allow_nan=False).encode()) + len(json.dumps(report["findings"]).encode())
                    if exhausted or size + weight > MAX_REPORT - 256 * 1024:
                        raise ValueError("Workspace report budget exceeded; select fewer projects")
                    size += weight
                    report = apply_baseline(report, baseline)
                except Exception as exc:
                    report = failure(node["tool"], str(exc))
                    if "report budget exceeded" in str(exc):
                        exhausted = True
                        cancelled.set()
                state = "passed" if gated_exit(report, fail_on) == 0 else "allowed_failure" if step.get("allow_failure", False) and not exhausted else "failed"
                finished[name] = {"name": name, "project": node["project"], "status": state, "report": report}
    except BaseException:
        cancelled.set()
        for future in running:
            future.cancel()
        raise
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
    ordered = [finished[name] for name in nodes]
    failed = sum(row["status"] in {"failed", "skipped"} for row in ordered)
    errors = exhausted or any(row["status"] == "failed" and row["report"]["status"] == "error" for row in ordered)
    report = {"schema": 1, "version": __version__, "tool": "workspace", "status": "error" if errors else "failed" if failed else "completed", "exit_code": 2 if errors else 1 if failed else 0, "summary": f"{len(ordered) - failed}/{len(ordered)} selected checks passed or were explicitly allowed to fail; {plan['scope']} workspace scope", "seconds": round(time.monotonic() - started, 4), "findings": [{**finding, "check": row["name"]} for row in ordered for finding in row["report"]["findings"]], "checks": ordered, "data": plan}
    report = clean(apply_baseline(report, baseline))
    if len(json.dumps(report, allow_nan=False).encode()) > MAX_REPORT:
        return failure("workspace", "Workspace report exceeds 8 MiB; select fewer projects")
    return report


def execute(args):
    if args.output and (Path(args.output).exists() or Path(args.output).is_symlink()):
        raise ValueError("Output already exists; choose a fresh filename")
    changed = read_json(contained(args.root, args.changed_files)) if args.changed_files else args.changed_file
    if args.changed_files and args.changed_file is not None:
        raise ValueError("Choose --changed-files or --changed-file")
    if args.action == "plan":
        plan = compile_plan(args.root, args.manifest, args.project, changed)[0]
        report = {"schema": 1, "version": __version__, "tool": "workspace-plan", "status": "completed", "exit_code": 0, "summary": f"{len(plan['nodes'])} checks planned; {plan['scope']} workspace scope", "findings": [], "data": clean(plan)}
    else:
        report = check(args.root, args.manifest, projects=args.project, changed=changed, jobs=args.jobs, allow_exec=args.allow_exec, fail_on=args.fail_on, baseline=args.baseline, use_cache=not args.no_cache, expect_plan=args.expect_plan)
    text = render(report, args.format)
    if args.output:
        write_text(Path(args.output), text)
    else:
        print(text, end="")
    return report["exit_code"]


def register(tools):
    workspace = tools.add_parser("workspace", help="Plan and run dependency-aware checks across multiple project roots")
    actions = workspace.add_subparsers(dest="action", required=True)
    for verb in ("plan", "check"):
        command = actions.add_parser(verb)
        command.add_argument("--root", default=".")
        command.add_argument("--manifest", default=".devpocket-workspace.json")
        command.add_argument("--project", action="append", default=[])
        command.add_argument("--changed-file", action="append", help="Changed workspace-relative path; repeatable, including deleted files")
        command.add_argument("--changed-files", help="Workspace-relative JSON array of changed paths; [] selects none")
        command.add_argument("--format", choices=("text", "json", "markdown", "sarif"), default="text")
        command.add_argument("--output")
        if verb == "check":
            command.add_argument("--jobs", type=int, default=4, help="Global active check-worker limit, 1..8")
            command.add_argument("--allow-exec", action="store_true")
            command.add_argument("--no-cache", action="store_true")
            command.add_argument("--fail-on", choices=("error", "warning", "none"), default="warning")
            command.add_argument("--baseline")
            command.add_argument("--expect-plan", help="Expected plan_sha256 from a reviewed plan")
        command.set_defaults(handler=execute)
