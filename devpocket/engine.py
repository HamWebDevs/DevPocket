"""Uniform execution envelopes for CLI, workers, reports and MCP."""
from __future__ import annotations
import contextlib
import io
import json
from pathlib import Path
import re
import time

from . import __version__
from .common import redact
from .registry import Registry
from .sdk import Finding, ToolContext, ToolResult, validate_input

MAX_RESULT = 2 * 1024 * 1024


class Capture(io.TextIOBase):
    def __init__(self, limit=8192):
        self.limit = limit
        self.text = ""
        self.truncated = False

    def writable(self):
        return True

    def write(self, text):
        self.text += str(text)
        if len(self.text) > self.limit:
            self.text = self.text[-self.limit:]
            self.truncated = True
        return len(text)


def clean(value, depth=0):
    if depth > 30:
        raise ValueError("Result nesting exceeds 30 levels")
    if isinstance(value, str):
        from .loglens import safe_text
        return safe_text(value)
    if value is None or type(value) in {bool, int, float}:
        return value
    if isinstance(value, list):
        return [clean(v, depth + 1) for v in value]
    if isinstance(value, dict) and all(isinstance(k, str) for k in value):
        return {k: "[REDACTED]" if re.search(r"(?i)(?:password|passwd|secret|access_token|api_key)$", k) else clean(v, depth + 1) for k, v in value.items()}
    raise ValueError("Tool data must contain only JSON-compatible values")


def failure(name, message):
    return {"schema": 1, "version": __version__, "tool": name, "status": "error", "summary": redact(message), "exit_code": 2, "findings": [], "data": {}, "seconds": 0}


def execute(name, params, root, enabled=(), allow_exec=False, registry=None):
    started = time.monotonic()
    captured = Capture()
    try:
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            spec = (registry or Registry(enabled)).get(name)
            validate_input(params, spec.input_schema)
            if not spec.read_only and not allow_exec:
                raise ValueError(f"Tool {name} can execute commands or write files; pass --allow-exec explicitly")
            result = spec.run(ToolContext(Path(root).resolve(), allow_exec), params)
        if not isinstance(result, ToolResult) or not isinstance(result.summary, str) or type(result.exit_code) is not int or not 0 <= result.exit_code <= 255:
            raise ValueError("Tool returned an invalid ToolResult")
        if len(result.findings) > 20000 or any(not isinstance(f, Finding) for f in result.findings):
            raise ValueError("Tools may return at most 20,000 Finding objects")
        report = {"schema": 1, "version": __version__, "tool": name, "status": "completed" if result.exit_code == 0 else "failed", "summary": result.summary, "exit_code": result.exit_code, "findings": [f.as_dict() for f in result.findings], "data": result.data, "seconds": round(time.monotonic() - started, 4)}
        if captured.text:
            report["diagnostics"] = {"text": captured.text, "truncated": captured.truncated}
        if len(json.dumps(report, allow_nan=False).encode()) > MAX_RESULT:
            raise ValueError("Tool result exceeds 2 MiB; narrow the input or grouping limit")
        report = clean(report)
        if len(json.dumps(report, allow_nan=False).encode()) > MAX_RESULT:
            raise ValueError("Tool result exceeds 2 MiB; narrow the input or grouping limit")
        return report
    except Exception as exc:
        report = failure(name, f"{type(exc).__name__}: {exc}")
        report["seconds"] = round(time.monotonic() - started, 4)
        return report


def gated_exit(report, fail_on="warning"):
    if report.get("status") == "error":
        return 2
    if report.get("exit_code", 0):
        return 1
    levels = {"error"} if fail_on == "error" else {"warning", "error"} if fail_on == "warning" else set()
    return int(any(f["severity"] in levels and not f.get("existing", False) for f in report.get("findings", [])))
