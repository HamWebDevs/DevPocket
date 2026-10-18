"""CLI surfaces for the extension platform; original commands stay unchanged."""
from __future__ import annotations
import contextlib
import json
from pathlib import Path
import sys

from . import __version__
from .checks import invoke, pipeline
from .common import load_json, write_text
from .engine import Capture, gated_exit
from .project import init, load, set_plugin
from .registry import Registry
from .reports import apply_baseline, create_baseline, render
from .scaffold import scaffold


def emit(args, report):
    text = render(report, args.format)
    if args.output:
        write_text(Path(args.output), text)
        print(f"Report saved: {args.output}", file=sys.stderr)
    else:
        print(text, end="")


def execute(args):
    root = Path(args.root).resolve()
    if not root.is_dir():
        raise ValueError("--root must be an existing directory")
    if args.tool == "init":
        print(f"Created {init(root)}")
        return 0
    if args.tool == "baseline":
        count = create_baseline(args.source, args.output)
        print(f"Saved {count} baseline fingerprints: {args.output}")
        return 0
    if args.tool == "plugins" and args.action == "scaffold":
        print(f"Plugin scaffold created: {scaffold(args.destination, args.name)}")
        return 0
    if args.tool == "cache":
        from .cache import manage
        result = manage(root, clear=args.action == "clear")
        print(json.dumps(result, indent=2) if args.json else f"Cache: {result['entries']} entries, {result['bytes']} bytes; removed {result['removed']}")
        return 0
    config = load(root, getattr(args, "config", None))
    registry = Registry(config.get("plugins", []))
    if args.tool in {"tools", "plugins"}:
        if args.action == "list":
            rows = registry.inventory()
            if args.tool == "plugins":
                rows = [r for r in rows if r["source"] != "builtin"]
            if args.json:
                print(json.dumps(rows, indent=2))
            else:
                for r in rows:
                    print(f"{r['name']:16} {r['source']:24} {'enabled' if r['enabled'] else 'disabled'}{' CONFLICT' if r['conflict'] else ''} | {r['description']}")
                if not rows:
                    print("No installed DevPocket plugins. Use plugins scaffold to create one.")
            return 0
        if args.action in {"enable", "disable"}:
            if args.action == "enable":
                if args.name in registry.builtins or len(registry.entries.get(args.name, [])) != 1:
                    raise ValueError("Enable requires exactly one installed, non-conflicting plugin entry point")
            print(f"Configuration updated: {set_plugin(root, args.name, args.action == 'enable')}")
            return 0
        with contextlib.redirect_stdout(Capture()), contextlib.redirect_stderr(Capture()):
            spec = registry.get(args.name)
        print(json.dumps({"name": spec.name, "description": spec.description, "read_only": spec.read_only, "api_version": spec.api_version, "cache_version": spec.cache_version, "input_schema": spec.input_schema}, indent=2))
        return 0
    if args.output and Path(args.output).exists():
        raise ValueError("Output already exists; choose a fresh filename before running checks")
    if args.tool == "run":
        raw = args.input
        params = load_json(Path(raw[1:])) if raw.startswith("@") else json.loads(raw)
        if args.baseline:
            apply_baseline({"tool": args.name, "findings": []}, args.baseline)
        report = invoke(args.name, params, root, config.get("plugins", []), args.allow_exec, args.timeout)
        report = apply_baseline(report, args.baseline)
        emit(args, report)
        return gated_exit(report, args.fail_on)
    if args.tool == "check":
        callback = (lambda name, state: print(f"[{state}] {name}", file=sys.stderr)) if args.format == "text" else None
        report = pipeline(config, root, args.jobs, args.allow_exec, args.fail_on, args.baseline, callback, not args.no_cache)
        emit(args, report)
        return report["exit_code"]
    raise ValueError("Unknown platform command")


def register(tools):
    def root(p):
        p.add_argument("--root", default=".")

    def output(p):
        p.add_argument("--format", choices=("text", "json", "sarif", "markdown"), default="text")
        p.add_argument("--output", help="Fresh report filename; never overwritten")
        p.add_argument("--fail-on", choices=("error", "warning", "none"), default="warning")
        p.add_argument("--baseline", help="Baseline file; existing findings do not fail the gate")
        p.add_argument("--allow-exec", action="store_true", help="Permit command-running or writing tools")
        p.add_argument("--config", help="Explicit project JSON config; default is ROOT/.devpocket.json")
        root(p)

    p = tools.add_parser("init", help="Create a project config without overwriting existing files")
    root(p)
    p.set_defaults(handler=execute)
    p = tools.add_parser("run", help="Run any built-in or enabled plugin through the structured API")
    p.add_argument("name")
    p.add_argument("--input", default="{}", help="JSON object or @path/to/input.json")
    p.add_argument("--timeout", type=float, default=60)
    output(p)
    p.set_defaults(handler=execute)
    p = tools.add_parser("check", help="Run configured checks in parallel with dependencies and quality gates")
    p.add_argument("--jobs", type=int, default=4)
    p.add_argument("--no-cache", action="store_true", help="Run all configured diagnostics without reading or writing result caches")
    output(p)
    p.set_defaults(handler=execute)
    p = tools.add_parser("cache", help="Inspect or clear this project's local result cache")
    actions = p.add_subparsers(dest="action", required=True)
    for verb in ("status", "clear"):
        command = actions.add_parser(verb)
        root(command)
        command.add_argument("--json", action="store_true")
    p.set_defaults(handler=execute)
    for noun in ("tools", "plugins"):
        p = tools.add_parser(noun, help=f"Discover and manage {noun}")
        actions = p.add_subparsers(dest="action", required=True)
        l = actions.add_parser("list")
        root(l)
        l.add_argument("--json", action="store_true")
        d = actions.add_parser("describe")
        d.add_argument("name")
        root(d)
        if noun == "plugins":
            for verb in ("enable", "disable"):
                d = actions.add_parser(verb)
                d.add_argument("name")
                root(d)
            d = actions.add_parser("scaffold")
            d.add_argument("destination")
            d.add_argument("--name", required=True)
            root(d)
        p.set_defaults(handler=execute)
    p = tools.add_parser("baseline", help="Record fingerprints from a structured JSON report")
    p.add_argument("--from", dest="source", required=True)
    p.add_argument("--output", required=True)
    root(p)
    p.set_defaults(handler=execute)
    from . import mcp_server
    p = tools.add_parser("serve", help="Serve read-only diagnostics to MCP clients over stdio")
    root(p)
    p.add_argument("--plugin", action="append", default=[], help="Explicitly expose an enabled read-only plugin; repeatable")
    p.add_argument("--timeout", type=float, default=60)
    p.add_argument("--print-config", action="store_true", help="Print a generic mcpServers connection snippet and exit")
    p.set_defaults(handler=mcp_server.execute)
