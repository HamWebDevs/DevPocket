"""Read-only repository checks with evidence and no automatic execution."""
from __future__ import annotations
import ast
import json
from pathlib import Path
import re
import shlex

from .common import files

GITHUB_RUNNER_ENV = {'CI', 'GITHUB_WORKSPACE', 'GITHUB_ACTION_PATH', 'GITHUB_OUTPUT', 'GITHUB_STEP_SUMMARY', 'RUNNER_TEMP'}


def scan(root):
    findings = []

    def add(code, path, line, message):
        findings.append({"code": code, "path": path, "line": line, "message": message})

    all_files = list(files(root))
    readmes = [p for p in all_files if p.parent == root and p.name.lower().startswith("readme")]
    if not readmes:
        add("missing-readme", ".", 0, "Add a README with installation and one runnable example.")
    tracked_names = {p.name.lower() for p in all_files if p.parent == root}
    if not any(n.startswith(("license", "licence", "copying")) for n in tracked_names):
        add("missing-license", ".", 0, "No root licence file; readers cannot assume permission to reuse the code.")
    if "pyproject.toml" in tracked_names and not any("test" in p.relative_to(root).parts or "tests" in p.relative_to(root).parts or p.name.startswith("test_") for p in all_files):
        add("missing-tests", "pyproject.toml", 0, "Python project has no obvious test files.")
    for p in all_files:
        if p.suffix.lower() not in {".md", ".py", ".json"} or p.stat().st_size > 256 * 1024:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeError, OSError):
            continue
        rel = p.relative_to(root).as_posix()
        if p.suffix.lower() == ".md":
            # Local links only: no network requests, code fences ignored.
            in_fence = False
            marker = None
            for number, line in enumerate(text.splitlines(), 1):
                stripped = line.lstrip()
                match = re.match(r"(`{3,}|~{3,})", stripped)
                if match:
                    if not in_fence:
                        in_fence, marker = True, match[1][0]
                    elif match[1][0] == marker:
                        in_fence = False
                    continue
                if in_fence:
                    continue
                for target in re.findall(r"\[[^\]]*\]\(([^\s)]+)(?:\s+[^)]*)?\)", line):
                    if target.startswith(("#", "/", "//")) or re.match(r"[a-zA-Z][\w+.-]*:", target):
                        continue
                    from urllib.parse import unquote
                    pathpart = unquote(target.split("#")[0].split("?")[0].strip("<>"))
                    destination = (p.parent / pathpart).resolve()
                    if destination.is_relative_to(root) and not destination.exists():
                        add("broken-local-link", rel, number, f"Local Markdown target does not exist: {target}")
        if p.suffix == ".py":
            try:
                tree = ast.parse(text)
            except SyntaxError:
                tree = None
            for node in ast.walk(tree) if tree is not None else ():
                if not (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute)
                        and isinstance(node.value.value, ast.Name) and node.value.value.id == "os"
                        and node.value.attr == "environ" and isinstance(node.slice, ast.Constant)
                        and isinstance(node.slice.value, str)):
                    continue
                key = node.slice.value
                if p.relative_to(root).parts[0] == '.github' and key in GITHUB_RUNNER_ENV:
                    continue
                if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
                    continue
                examples = [root / name for name in (".env.example", ".env.sample", ".env.template")]
                documented = any(e.exists() and not e.is_symlink() and e.stat().st_size < 256 * 1024 and re.search(rf"(?m)^\s*{re.escape(key)}\s*=", e.read_text(errors="replace")) for e in examples)
                if not documented:
                    add("undocumented-env", rel, node.lineno, f"Required environment name {key} is absent from root .env example files.")
        if p.name == "package.json":
            try:
                data = json.loads(text)
                scripts = data.get("scripts", {})
                if not isinstance(scripts, dict):
                    raise ValueError("scripts must be an object")
                for name, command in scripts.items():
                    # Deliberately narrow: only literal `node path` and `python path`.
                    tokens = shlex.split(str(command))
                    for i, token in enumerate(tokens[:-1]):
                        candidate = tokens[i + 1]
                        if token in {"node", "python", "python3"} and re.fullmatch(r"[\w./-]+\.(?:js|mjs|cjs|py)", candidate):
                            target = (p.parent / candidate).resolve()
                            if target.is_relative_to(root) and not target.exists():
                                add("missing-script", rel, 0, f"Script {name!r} references missing file: {candidate}")
            except (ValueError, AttributeError, TypeError) as exc:
                add("invalid-package-json", rel, 0, f"Cannot inspect package.json: {exc}")
    return findings


def execute(args):
    root = Path(args.root).resolve()
    if not root.is_dir():
        raise ValueError("Root must be a directory")
    findings = scan(root)
    if args.json:
        print(json.dumps({"schema": 1, "findings": findings}, indent=2))
    else:
        for f in findings:
            print(f"{f['path']}:{f['line']} [{f['code']}] {f['message']}")
        print(f"{len(findings)} finding(s). Static heuristics only; setup commands were not executed.")
    return 1 if findings else 0
