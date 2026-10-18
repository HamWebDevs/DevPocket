"""Explicit project configuration; never imports Python files from a repository."""
from __future__ import annotations
import json
import os
from pathlib import Path
import tempfile

from .common import load_json, write_json
from .sdk import NAME

DEFAULT = {"version": 1, "plugins": [], "checks": {"repository": {"tool": "reporadar", "input": {}}}}


def config_path(root, path=None):
    return Path(path).resolve() if path else Path(root).resolve() / ".devpocket.json"


def validate(config):
    if not isinstance(config, dict) or (type(config.get("version")) is not int or config.get("version") != 1) or set(config) - {"version", "plugins", "checks"}:
        raise ValueError("Expected .devpocket.json version 1 with plugins and checks")
    plugins = config.get("plugins", [])
    if not isinstance(plugins, list) or any(not isinstance(p, str) or not NAME.fullmatch(p) for p in plugins) or len(set(plugins)) != len(plugins):
        raise ValueError("plugins must be a list of unique tool entry-point names")
    checks = config.get("checks", {})
    if not isinstance(checks, dict) or len(checks) > 100:
        raise ValueError("checks must be an object containing at most 100 checks")
    for name, step in checks.items():
        if not NAME.fullmatch(name) or not isinstance(step, dict) or set(step) - {"tool", "input", "needs", "timeout", "allow_failure", "cache"}:
            raise ValueError(f"Invalid check: {name}")
        if not isinstance(step.get("tool"), str) or not NAME.fullmatch(step["tool"]) or not isinstance(step.get("input", {}), dict):
            raise ValueError(f"Invalid tool or input for check {name}")
        needs = step.get("needs", [])
        if not isinstance(needs, list) or any(not isinstance(n, str) or n not in checks or n == name for n in needs):
            raise ValueError(f"Invalid dependencies for check {name}")
        if type(step.get("timeout", 60)) not in {int, float} or not 0 < step.get("timeout", 60) <= 3600:
            raise ValueError(f"Check {name}: timeout must be 0..3600 seconds")
        if type(step.get("allow_failure", False)) is not bool:
            raise ValueError("allow_failure must be boolean")
        if "cache" in step:
            from .cache import validate_policy
            validate_policy(step["cache"])
    remaining = set(checks)
    while remaining:
        ready = {n for n in remaining if not set(checks[n].get("needs", [])) & remaining}
        if not ready:
            raise ValueError("Check dependencies contain a cycle")
        remaining -= ready
    return config


def load(root, path=None):
    filename = config_path(root, path)
    if path and not filename.exists():
        raise ValueError(f"Explicit config does not exist: {filename}")
    return validate(load_json(filename)) if filename.exists() else {"version": 1, "plugins": [], "checks": {}}


def init(root):
    filename = config_path(root)
    write_json(filename, DEFAULT)
    return filename


def set_plugin(root, name, enabled):
    filename = config_path(root)
    config = load(root)
    names = config.setdefault("plugins", [])
    if enabled and name not in names:
        names.append(name)
    if not enabled and name in names:
        names.remove(name)
    validate(config)
    if not filename.exists():
        write_json(filename, config)
    else:
        # Existing config replacement is explicit for this command; symlinks are refused.
        if filename.is_symlink():
            raise ValueError("Refusing to replace a symlinked project config")
        fd, temporary = tempfile.mkstemp(prefix=".devpocket-config-", dir=filename.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
                f.write("\n")
            os.replace(temporary, filename)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return filename
