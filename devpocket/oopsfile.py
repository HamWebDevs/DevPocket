"""Turn a failed command into a small, local Markdown debugging report."""
from __future__ import annotations
import json
from pathlib import Path
import re
import shlex

from .common import exit_code, redact, run, sensitive, write_text
from .envtwin import snapshot


def fence(text, language=""):
    # Tracebacks or diffs may themselves contain Markdown fences.
    runs = [len(x) for x in re.findall(r"`+", text)]
    marker = "`" * max(3, max(runs, default=0) + 1)
    return f"{marker}{language}\n{text.rstrip()}\n{marker}\n"


def context(output, root):
    snippets = []
    seen = set()
    for name, line in re.findall(r'File "([^"\n]+)", line (\d+)', output):
        path = Path(name)
        if not path.is_absolute():
            path = root / path
        path = path.resolve()
        if not path.is_relative_to(root) or sensitive(path) or path in seen:
            continue
        seen.add(path)
        try:
            if path.stat().st_size > 256 * 1024:
                continue
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        number = int(line)
        start, end = max(0, number - 4), min(len(lines), number + 3)
        snippets.append(f"### {path.relative_to(root).as_posix()}:{number}\n\n" + fence("\n".join(f"{i + 1}: {lines[i]}" for i in range(start, end)), "python"))
        if len(snippets) >= 5:
            break
    return "\n".join(snippets)


def execute(args):
    root = Path(args.root).resolve()
    result = run(args.command, cwd=root, timeout=args.timeout)
    print(redact(result["stdout"]), end="")
    print(redact(result["stderr"]), end="")
    if result["returncode"] == 0:
        print("Command succeeded; no failure report needed.")
        return 0
    sections = ["# Oopsfile debugging report\n", "Local report. Review before sharing: redaction is best-effort, not a secret detector.\n", "## Command\n\n" + fence(shlex.join(args.command), "text"), f"Exit code: {result['returncode']} | Timed out: {result['timed_out']} | Duration: {result['seconds']}s\n", "## Output (last 128 KiB per stream)\n\n" + fence(result["stdout"] + "\n" + result["stderr"], "text"), f"Truncated stdout/stderr: {result['truncated']}\n", "## Environment of the reporting Python interpreter\n\n" + fence(json.dumps(snapshot(), indent=2), "json")]
    if args.include_source:
        sections.append("## Traceback source context\n\n" + (context(result["stderr"] + result["stdout"], root) or "No readable project-local Python frames found.\n"))
    if args.include_diff:
        changes = run(["git", "diff", "--no-ext-diff", "--no-textconv", "--stat"], cwd=root, timeout=10)
        sections.append("## Unstaged Git change summary\n\n" + fence(changes["stdout"] or changes["stderr"], "text"))
        sections.append("Only file statistics are included; patch contents are omitted.\n")
    write_text(Path(args.output), redact("\n".join(sections)))
    print(f"Failure report saved: {args.output}")
    return exit_code(result["returncode"])
