"""Scoped file backups and conflict-aware restoration. This is not a sandbox."""
from __future__ import annotations
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import uuid

from .common import digest, exit_code, files, load_json, run, write_json


def checked_path(root, relative):
    p = PurePosixPath(relative)
    if not relative or p.is_absolute() or ".." in p.parts or "\\" in relative or ":" in relative or ".devpocket" in p.parts:
        raise ValueError(f"Unsafe journal path: {relative!r}")
    path = root.joinpath(*p.parts)
    for parent in [path, *path.parents]:
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError(f"Symlink in restore path: {relative}")
    if not path.resolve().is_relative_to(root):
        raise ValueError("Restore path leaves root")
    return path


def inventory(root, excludes):
    state = {}
    for p in files(root, excludes):
        if len(state) >= 20000:
            raise ValueError("Inventory exceeds 20,000 files; use --exclude or a smaller --root")
        state[p.relative_to(root).as_posix()] = {"sha256": digest(p), "mode": stat.S_IMODE(p.stat().st_mode), "size": p.stat().st_size}
    return state


def changes(before, after):
    return sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))


def journal_dir(root, run_id):
    if not re.fullmatch(r"[a-f0-9]{12}", run_id):
        raise ValueError("Invalid run ID")
    for p in (root / ".devpocket", root / ".devpocket/runs", root / ".devpocket/runs" / run_id):
        if p.is_symlink():
            raise ValueError("Journal directories must not be symlinks")
    return root / ".devpocket/runs" / run_id


def record(args):
    root = Path(args.root).resolve()
    if not root.is_dir():
        raise ValueError("Root must be a directory")
    before = inventory(root, args.exclude)
    if len(before) > 5000 or sum(v["size"] for v in before.values()) > 64 * 1024 * 1024 or any(v["size"] > 8 * 1024 * 1024 for v in before.values()):
        raise ValueError("Backup limit exceeded (5,000 files / 64 MiB total / 8 MiB per file). Narrow --root or --exclude.")
    run_id = uuid.uuid4().hex[:12]
    folder = journal_dir(root, run_id)
    folder.mkdir(parents=True, mode=0o700)
    os.chmod(root / ".devpocket", 0o700)
    backup = folder / "backup"
    backup.mkdir(mode=0o700)
    for rel, info in before.items():
        source = checked_path(root, rel)
        dest = backup / info["sha256"]
        if not dest.exists():
            shutil.copyfile(source, dest)
            os.chmod(dest, 0o600)
        if digest(dest) != info["sha256"]:
            raise ValueError("Files changed during backup; command was not run. Stop other writers and retry.")
    write_json(folder / "before.json", {"schema": 1, "root": str(root), "before": before, "excludes": args.exclude})
    print(f"Backup ready. Run ID: {run_id}", flush=True)
    result = run(args.command, cwd=root, timeout=args.timeout)
    # A command can modify anything it has permission to; it is not confined.
    after = inventory(root, args.exclude)
    write_json(folder / "after.json", {"after": after, "returncode": result["returncode"]})
    print(result["stdout"], end="")
    print(result["stderr"], end="")
    for rel in changes(before, after):
        label = "created" if rel not in before else "deleted" if rel not in after else "modified"
        print(f"{label}: {rel}")
    print(f"Preview undo: devpocket undorun restore {run_id} --root {str(root)!r}")
    return exit_code(result["returncode"])


def restore(args):
    root = Path(args.root).resolve()
    folder = journal_dir(root, args.run_id)
    manifest = load_json(folder / "before.json")
    if manifest.get("schema") != 1 or manifest.get("root") != str(root):
        raise ValueError("Journal belongs to a different root or schema")
    before = manifest["before"]
    after = load_json(folder / "after.json")["after"]
    affected = changes(before, after)
    # Preflight every target and backup before making any changes.
    for rel in affected:
        path = checked_path(root, rel)
        if path.exists() and not path.is_file():
            raise ValueError(f"Restore conflict (not a regular file): {rel}")
        actual = None if not path.exists() else {"sha256": digest(path), "mode": stat.S_IMODE(path.stat().st_mode), "size": path.stat().st_size}
        if actual != after.get(rel):
            raise ValueError(f"Restore conflict: {rel} changed after the run. No files restored.")
        for parent in path.parents:
            if parent == root:
                break
            if parent.exists() and not parent.is_dir():
                raise ValueError(f"Parent path is no longer a directory: {rel}")
        if rel in before:
            sha = before[rel]["sha256"]
            if not re.fullmatch(r"[a-f0-9]{64}", sha):
                raise ValueError("Invalid backup hash")
            saved = folder / "backup" / sha
            if saved.is_symlink() or not saved.is_file() or digest(saved) != sha:
                raise ValueError(f"Missing or damaged backup: {rel}")
    if not affected:
        print("No captured file changes.")
        return 0
    for rel in affected:
        print(f"{'restore' if rel in before else 'remove created file'}: {rel}")
    if not args.apply:
        print("Preview only. Add --apply to restore these files.")
        return 0
    for rel in affected:
        path = checked_path(root, rel)
        if rel not in before:
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix=".devpocket-restore-", dir=path.parent)
            os.close(fd)
            try:
                shutil.copyfile(folder / "backup" / before[rel]["sha256"], name)
                os.chmod(name, before[rel]["mode"] & 0o777)
                os.replace(name, path)
            finally:
                if os.path.exists(name):
                    os.unlink(name)
    print("Captured file contents restored. Backups retained; empty directories are left in place.")
    return 0


def execute(args):
    return record(args) if args.action == "run" else restore(args)
