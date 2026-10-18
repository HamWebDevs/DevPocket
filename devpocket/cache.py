"""Opt-in result caching for diagnostics with an explicit deterministic contract."""
from __future__ import annotations

import hashlib
import importlib.metadata as metadata
import inspect
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile
import time

from . import __version__

MAX_FILES = 10000
MAX_BYTES = 64 * 1024 * 1024
MAX_ENTRY = 2 * 1024 * 1024 + 65536
MAX_ENTRIES = 256
MAX_STORAGE = 64 * 1024 * 1024
ENTRY = re.compile(r"[0-9a-f]{64}\.json\Z")
ENV = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}\Z")


class Bypass(ValueError):
    """Caching is unavailable; the diagnostic must still run."""


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def validate_policy(policy):
    if not isinstance(policy, dict) or set(policy) - {"inputs", "env", "max_age"}:
        raise ValueError("cache must contain inputs, optional env and max_age")
    paths = policy.get("inputs")
    if not isinstance(paths, list) or not 1 <= len(paths) <= 32:
        raise ValueError("cache.inputs needs 1..32 explicit files or directories")
    for text in paths:
        if not isinstance(text, str) or not text or len(text) > 4096 or any(c in text for c in "\\:*?[]\0"):
            raise ValueError("Cache inputs are relative POSIX paths, without glob patterns")
        path = PurePosixPath(text)
        if path.is_absolute() or ".." in path.parts or ".git" in path.parts:
            raise ValueError("Cache inputs must stay inside the project and outside .git")
    names = policy.get("env", [])
    if not isinstance(names, list) or len(names) > 32 or any(not isinstance(n, str) or not ENV.fullmatch(n) for n in names):
        raise ValueError("cache.env must list at most 32 environment variable names")
    age = policy.get("max_age", 3600)
    if type(age) not in {int, float} or not 1 <= age <= 604800:
        raise ValueError("cache.max_age must be 1..604800 seconds")
    return policy


def contained(root, relative):
    path = root / relative
    for part in (path, *path.parents):
        if part == root:
            break
        if part.is_symlink():
            raise Bypass("A declared input or cache path is a symlink")
    if not path.resolve().is_relative_to(root):
        raise Bypass("A declared input or cache path leaves the project")
    return path


def files_under(path, excluded=()):
    if path.is_symlink():
        raise Bypass("Symlink inputs are not cached")
    if not path.exists():
        yield path
    elif path.is_file():
        yield path
    elif path.is_dir():
        yield path  # Empty directories and directory/file transitions affect the key.
        visited, pending = 0, [path]
        while pending:
            with os.scandir(pending.pop()) as children:
                for child in children:
                    item = Path(child.path)
                    if child.name in {".git", "__pycache__"} or item in excluded:
                        continue
                    visited += 1
                    if visited > MAX_FILES:
                        raise Bypass("Cache input traversal exceeded its file limit")
                    if child.is_symlink() or item.resolve() != item:
                        raise Bypass("Symlink/junction inputs are not cached")
                    if child.is_dir(follow_symlinks=False):
                        pending.append(item)
                    if item.suffix not in {".pyc", ".pyo"}:
                        yield item
    else:
        raise Bypass("Only regular files and directories can be cache inputs")


def hash_paths(paths, base):
    entries, total = [], 0
    for path in sorted(set(paths)):
        if len(entries) >= MAX_FILES:
            raise Bypass("Cache input file limit exceeded")
        if path.is_symlink() or not path.resolve().is_relative_to(base):
            raise Bypass("Cache input containment changed")
        relative = path.relative_to(base).as_posix()
        try:
            before = path.stat()
        except FileNotFoundError:
            entries.append([relative, "missing"])
            continue
        if stat.S_ISDIR(before.st_mode):
            entries.append([relative, "directory"])
            continue
        if not stat.S_ISREG(before.st_mode):
            raise Bypass("Cache input is not a regular file")
        total += before.st_size
        if total > MAX_BYTES:
            raise Bypass("Cache input byte limit exceeded")
        hashed = hashlib.sha256()
        read = 0
        with path.open("rb") as stream:
            while chunk := stream.read(128 * 1024):
                read += len(chunk)
                if read > before.st_size or total - before.st_size + read > MAX_BYTES:
                    raise Bypass("A cache input changed while being read")
                hashed.update(chunk)
        after = path.stat()
        if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise Bypass("A cache input changed while being read")
        entries.append([relative, before.st_size, bool(before.st_mode & stat.S_IXUSR), hashed.hexdigest()])
    return {"digest": digest(entries), "files": len(entries), "bytes": total}


def snapshot(root, policy):
    validate_policy(policy)
    root = Path(root).resolve()
    excluded = (root / ".devpocket" / "cache-v1",)
    paths = []
    for relative in policy["inputs"]:
        path = contained(root, relative)
        if path == excluded[0] or excluded[0] in path.parents:
            raise Bypass("The result cache cannot be its own input")
        paths.extend(files_under(path, excluded))
        if len(paths) > MAX_FILES:
            raise Bypass("Cache input file limit exceeded")
    result = hash_paths(paths, root)
    # Environment values and file contents are never serialized into cache metadata.
    result["environment"] = digest({name: os.environ.get(name) for name in sorted(set(policy.get("env", [])))})
    return result


def runtime_identity(spec):
    source = inspect.getsourcefile(spec.run)
    if not source:
        raise Bypass("Tool source cannot be fingerprinted")
    source = Path(source).resolve()
    module = inspect.getmodule(spec.run)
    package = getattr(module, "__package__", "") or ""
    base = source.parents[max(0, len(package.split(".")) - 1)] if package else source.parent
    paths = files_under(base) if package else [source]
    tool_code = hash_paths(paths, base)
    host = Path(__file__).resolve().parent
    host_code = hash_paths(files_under(host), host)
    versions = sorted((d.metadata.get("Name", ""), d.version) for d in metadata.distributions())
    return digest({"host": __version__, "python": sys.version, "interpreter": sys.executable, "platform": sys.platform, "tool_code": tool_code["digest"], "host_code": host_code["digest"], "distributions": versions})


def directory(root, create=False):
    root = Path(root).resolve()
    target = contained(root, ".devpocket/cache-v1")
    if create:
        target.mkdir(mode=0o700, parents=True, exist_ok=True)
        contained(root, ".devpocket/cache-v1")
    return target


def read(root, key, tool):
    path = directory(root) / (key + ".json")
    if not path.exists():
        return None, "no matching stored result"
    if path.is_symlink() or path.stat().st_size > MAX_ENTRY:
        return None, "invalid cache entry"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        age = time.time() - data["created"]
        report = data["report"]
        if data["schema"] != 1 or data["key"] != key or not 0 <= age <= data["max_age"] or digest(report) != data["integrity"]:
            return None, "expired or invalid cache entry"
        if not isinstance(report, dict) or report.get("schema") != 1 or report.get("tool") != tool or report.get("version") != __version__ or report.get("status") != "completed" or report.get("exit_code") != 0 or not isinstance(report.get("findings"), list) or not isinstance(report.get("summary"), str) or not isinstance(report.get("data"), dict):
            return None, "invalid cached report"
        for finding in report["findings"]:
            if not isinstance(finding, dict) or finding.get("severity") not in {"note", "warning", "error"} or not all(isinstance(finding.get(k), str) for k in ("rule", "message", "fingerprint")):
                return None, "invalid cached findings"
        return report, round(age, 3)
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        return None, "unreadable cache entry"


def store_result(root, key, report, max_age):
    target = directory(root, create=True)
    data = {"schema": 1, "key": key, "created": time.time(), "max_age": max_age, "integrity": digest(report), "report": report}
    payload = encoded(data)
    if len(payload) > MAX_ENTRY:
        raise Bypass("Result is too large for the cache")
    path = target / (key + ".json")
    if path.is_symlink():
        raise Bypass("Cache destination is a symlink")
    fd, temporary = tempfile.mkstemp(prefix=".cache-", dir=target)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    # Bound storage. Only this cache's recognized regular entry files are removed.
    entries = sorted((p for p in target.iterdir() if ENTRY.fullmatch(p.name) and not p.is_symlink() and p.is_file()), key=lambda p: p.stat().st_mtime)
    sizes = {p: p.stat().st_size for p in entries}
    total = sum(sizes.values())
    while len(entries) > MAX_ENTRIES or total > MAX_STORAGE:
        item = entries.pop(0)
        try:
            item.unlink()
        except FileNotFoundError:
            pass
        total -= sizes[item]


class Session:
    def __init__(self, spec, params, root, policy, allow_exec):
        self.root, self.policy, self.spec = Path(root).resolve(), policy, spec
        self.info = {"status": "bypass", "reason": "not requested"}
        self.key, self.before, self.hit = None, None, None
        if policy is None:
            return
        if policy is False:
            self.info["reason"] = "disabled by --no-cache"
            return
        try:
            validate_policy(policy)
            if allow_exec or not spec.read_only or spec.cache_version is None:
                raise Bypass("Tool has no read-only cache contract or execution is allowed")
            directory(self.root, create=True)
            self.before = snapshot(self.root, policy)
            identity = runtime_identity(spec)
            self.key = digest({"root": str(self.root), "tool": spec.name, "contract": spec.cache_version, "schema": spec.input_schema, "input": params, "policy": policy, "snapshot": self.before, "runtime": identity})
            self.hit, reason = read(self.root, self.key, spec.name)
            if self.hit is not None and snapshot(self.root, policy) != self.before:
                self.hit = None
                raise Bypass("Declared inputs changed while reading a cached result")
            self.info = {"status": "hit" if self.hit else "miss", "key": self.key, "files": self.before["files"], "bytes_hashed": self.before["bytes"]}
            self.info["age_s" if self.hit else "reason"] = reason
        except (OSError, ValueError, TypeError, RecursionError) as exc:
            self.key = None
            self.hit = None
            self.info = {"status": "bypass", "reason": str(exc)}

    def finish(self, report):
        if self.key and self.hit is None and report["status"] == "completed" and report["exit_code"] == 0:
            try:
                if snapshot(self.root, self.policy) != self.before:
                    raise Bypass("Declared inputs changed during the diagnostic")
                store_result(self.root, self.key, report, self.policy.get("max_age", 3600))
            except (OSError, ValueError, TypeError, RecursionError) as exc:
                self.info = {"status": "bypass", "reason": str(exc)}
        if self.policy is not None:
            report["cache"] = self.info
        return report


def manage(root, clear=False):
    path = directory(root)
    entries, size, removed = 0, 0, 0
    if path.exists():
        for item in path.iterdir():
            if not ENTRY.fullmatch(item.name) or item.is_symlink() or not item.is_file():
                continue
            entries += 1
            size += item.stat().st_size
            if clear:
                item.unlink()
                removed += 1
    return {"entries": entries, "bytes": size, "removed": removed, "path": ".devpocket/cache-v1"}
