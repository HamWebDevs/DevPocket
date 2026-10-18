"""Portable environment snapshots without environment values or hostnames."""
from __future__ import annotations
import importlib.metadata
import os
from pathlib import Path
import platform
import re
import shutil
import sys

from .common import load_json, write_json


def snapshot():
    packages = {}
    for dist in importlib.metadata.distributions():
        name = dist.metadata.get("Name")
        if name:
            packages[re.sub(r"[-_.]+", "-", name).lower()] = dist.version
    return {"schema": 1, "python": {"version": platform.python_version(), "implementation": platform.python_implementation(), "virtualenv": sys.prefix != sys.base_prefix}, "system": {"os": platform.system(), "release": platform.release(), "machine": platform.machine(), "libc": list(platform.libc_ver())}, "packages": dict(sorted(packages.items())), "tools": {name: bool(shutil.which(name)) for name in ("git", "node", "npm", "docker", "gcc", "make")}, "environment_names": sorted(k for k in os.environ if k in {"VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "LANG", "LC_ALL", "CI"})}


def compare(left, right):
    if not isinstance(left, dict) or not isinstance(right, dict) or left.get("schema") != 1 or right.get("schema") != 1:
        raise ValueError("Expected EnvTwin schema 1 snapshots")
    changes = []
    for section in ("python", "system", "packages", "tools"):
        a, b = left.get(section, {}), right.get(section, {})
        if not isinstance(a, dict) or not isinstance(b, dict):
            raise ValueError(f"Invalid {section} section")
        for key in sorted(a.keys() | b.keys()):
            if a.get(key) != b.get(key):
                changes.append({"section": section, "name": key, "left": a.get(key), "right": b.get(key)})
    if left.get("environment_names") != right.get("environment_names"):
        changes.append({"section": "environment", "name": "variable names only", "left": left.get("environment_names"), "right": right.get("environment_names")})
    return changes


def execute(args):
    if args.action == "snapshot":
        write_json(Path(args.output), snapshot())
        print(f"Snapshot saved: {args.output} (no environment values included)")
        return 0
    changes = compare(load_json(Path(args.left)), load_json(Path(args.right)))
    if args.json:
        import json
        print(json.dumps(changes, indent=2))
    elif not changes:
        print("No differences in the captured fields.")
    else:
        for item in changes:
            print(f"{item['section']}.{item['name']}: {item['left']!r} -> {item['right']!r}")
        print("Start with Python/package differences. Tool presence and OS differences are clues, not proof of a cause.")
    return 1 if changes else 0
