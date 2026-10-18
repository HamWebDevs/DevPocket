"""Static Python import diagnostics without importing the inspected module."""
from __future__ import annotations

import importlib.machinery as machinery
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import re
import sys

from .common import redact


def locate(module, search_path):
    """Resolve dotted specs without executing package __init__.py files."""
    parts = module.split(".")
    full = parts[0]
    spec = machinery.BuiltinImporter.find_spec(full) or machinery.FrozenImporter.find_spec(full) or machinery.PathFinder.find_spec(full, search_path)
    if spec is None:
        return None, full
    for part in parts[1:]:
        if spec.submodule_search_locations is None:
            return None, f"{full} is a module, not a package"
        full += "." + part
        # Use the leaf name with the explicit parent search locations. A full
        # dotted namespace spec expects its parent in sys.modules, which would
        # require executing __init__.py. These specs are never loaded.
        spec = machinery.PathFinder.find_spec(part, list(spec.submodule_search_locations))
        if spec is None:
            return None, full
        if spec.submodule_search_locations is not None:
            spec.submodule_search_locations = list(spec.submodule_search_locations)
        spec.name = full
    return spec, None


def inspect_module(module, root, distribution=None, expected_python=None):
    if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", module, re.ASCII):
        raise ValueError("Supply a dotted Python import name, for example requests or yaml.loader")
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError("--root must be an existing directory")
    top = module.split(".")[0]
    search = [str(root), *[p for p in sys.path[1:] if p and Path(p).resolve() != root]]
    spec, missing = locate(module, search)
    top_spec, _ = locate(top, search)
    mappings = metadata.packages_distributions()
    owners = sorted(set(mappings.get(top, [])))
    if distribution and distribution not in owners:
        owners.append(distribution)
    distributions = []
    for name in owners:
        try:
            dist = metadata.distribution(name)
            distributions.append({"name": dist.metadata.get("Name", name), "version": dist.version, "location": str(dist.locate_file(""))})
        except metadata.PackageNotFoundError:
            distributions.append({"name": name, "version": None, "location": None})
    findings = []

    def add(code, message, suggestion):
        findings.append({"code": code, "message": message, "suggestion": suggestion})

    if expected_python and os.path.normcase(os.path.abspath(os.path.expanduser(expected_python))) != os.path.normcase(os.path.abspath(sys.executable)):
        add("interpreter-mismatch", f"Running interpreter differs from --expect-python: {expected_python}", "Run the expected interpreter with -m devpocket importdoctor to inspect that environment.")
    if spec is None:
        add("module-not-found", f"Static resolution stopped at {missing}.", "Check the spelling, project root and interpreter. Use --distribution if the pip distribution name differs from the import name.")
    top_origin = top_spec.origin if top_spec is not None else None
    is_local = bool(top_origin and top_origin not in {"built-in", "frozen"} and Path(top_origin).resolve().is_relative_to(root))
    builtin_name = top in getattr(sys, "stdlib_module_names", set())
    installed_owners = [d["name"] for d in distributions if d["version"] is not None]
    alternate_spec, _ = locate(top, [p for p in search if not Path(p).resolve().is_relative_to(root)])
    if is_local and (builtin_name or installed_owners or alternate_spec is not None):
        add("local-shadow", f"Local {top_origin} takes precedence over another module or distribution named {top}.", f"If unintended, rename the local {top}.py file or {top}/ package, then retry in a fresh Python process.")
    elif is_local:
        add("local-module", f"Resolved {top} from the project root.", "This can be intentional; confirm --root matches how the application starts.")
    if top_spec is not None and top_spec.origin is None and top_spec.submodule_search_locations is not None:
        add("namespace-package", f"{top} is a namespace package with no single __init__.py origin.", "Namespace packages are valid. Check each reported search location if a child module is missing.")
    for dist in distributions:
        if dist["version"] is None:
            add("distribution-not-installed", f"Distribution {dist['name']} is not installed in this interpreter.", "Verify the distribution name and use this interpreter's -m pip to inspect or install the project's declared requirements.")
    if not findings:
        add("resolved", "The module is statically resolvable in the inspected environment.", "If importing still fails, inspect the original traceback for a missing transitive dependency, package initialisation error or native-library failure.")
    problem_codes = {"interpreter-mismatch", "module-not-found", "local-shadow", "distribution-not-installed"}
    return {"schema": 1, "module": module, "python": {"executable": sys.executable, "version": sys.version.split()[0], "virtualenv": sys.prefix != sys.base_prefix}, "root": str(root), "resolution": {"found": spec is not None, "origin": spec.origin if spec is not None else None, "search_locations": list(spec.submodule_search_locations or []) if spec is not None else [], "missing_at": missing}, "distributions": distributions, "findings": findings, "has_problems": any(f["code"] in problem_codes for f in findings)}


def execute(args):
    report = inspect_module(args.module, args.root, args.distribution, args.expect_python)
    if args.json:
        print(redact(json.dumps(report, indent=2)))
    else:
        print(f"ImportDoctor: {args.module}")
        print(redact(f"Python {report['python']['version']}: {report['python']['executable']}"))
        print(redact(f"Origin: {report['resolution']['origin'] or '(no file origin)'}"))
        for location in report["resolution"]["search_locations"]:
            print(redact(f"Package search location: {location}"))
        for dist in report["distributions"]:
            print(f"Distribution: {dist['name']} {dist['version'] or '(not installed)'}")
        for item in report["findings"]:
            print(redact(f"\n[{item['code']}] {item['message']}\n  {item['suggestion']}"))
        print("\nStatic inspection only: target code was not imported; runtime imports may behave differently.")
    return 1 if report["has_problems"] else 0
