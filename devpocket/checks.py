"""Bounded, subprocess-isolated tool invocation and dependency-aware parallel checks."""
from __future__ import annotations
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import json
import os
from pathlib import Path
import sys
import time
import threading

from . import __version__
from .common import run
from .engine import failure, gated_exit
from .project import validate
from .reports import apply_baseline, read_baseline

MAX_REPORT = 8 * 1024 * 1024


def invoke(tool, params, root, plugins=(), allow_exec=False, timeout=60, cancel_event=None, cache_policy=None):
    request = json.dumps({"tool": tool, "input": params, "root": str(root), "plugins": list(plugins), "allow_exec": allow_exec, "cache": cache_policy}, allow_nan=False)
    if len(request.encode()) > 1024 * 1024:
        return failure(tool, "Tool request exceeds 1 MiB")
    env = os.environ.copy()
    package_parent = str(Path(__file__).resolve().parent.parent)
    env["PYTHONPATH"] = package_parent + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    captured = run([sys.executable, "-m", "devpocket.worker"], cwd=root, timeout=timeout, input_text=request, env=env, capture_limit=3 * 1024 * 1024, cancel_event=cancel_event)
    if captured["timed_out"]:
        return failure(tool, f"Tool exceeded {timeout}s wall-clock timeout")
    if captured["returncode"] != 0 or any(captured["truncated"]):
        return failure(tool, "Worker failed or exceeded capture limits; no complete report was returned")
    try:
        report = json.loads(captured["stdout"])
        if not isinstance(report, dict) or report.get("schema") != 1 or report.get("tool") != tool or not isinstance(report.get("findings"), list):
            raise ValueError("Invalid worker envelope")
        return report
    except (ValueError, TypeError):
        return failure(tool, "Worker emitted invalid JSON; plugin output must use the SDK result")


def pipeline(config, root, jobs=4, allow_exec=False, fail_on="warning", baseline=None, progress=None, use_cache=True):
    validate(config)
    if type(jobs) is not int or not 1 <= jobs <= 8:
        raise ValueError("--jobs must be between 1 and 8")
    steps = config.get("checks", {})
    if not steps:
        raise ValueError("No checks configured. Run devpocket init and edit .devpocket.json.")
    # Baseline syntax is checked once before any tools execute.
    baseline = read_baseline(baseline)
    started = time.monotonic()
    pending = set(steps)
    finished = {}
    running = {}
    cancelled = threading.Event()
    size, exhausted = 0, False
    executor = ThreadPoolExecutor(max_workers=jobs)
    try:
        while pending or running:
            for name in list(steps):
                if name not in pending or len(running) >= jobs:
                    continue
                deps = steps[name].get("needs", [])
                if any(dep not in finished for dep in deps):
                    continue
                pending.remove(name)
                blocked = exhausted or any(finished[dep]["status"] not in {"passed", "allowed_failure"} for dep in deps)
                if blocked:
                    report = failure(steps[name]["tool"], "Skipped because a dependency or aggregate report budget did not pass")
                    finished[name] = {"name": name, "status": "skipped", "report": report}
                    continue
                if progress:
                    progress(name, "running")
                step = steps[name]
                policy = step.get("cache") if use_cache else False if "cache" in step else None
                future = executor.submit(invoke, step["tool"], step.get("input", {}), root, config.get("plugins", []), allow_exec, step.get("timeout", 60), cancelled, policy)
                running[future] = name
            if running:
                done, _ = wait(running, return_when=FIRST_COMPLETED)
                for future in done:
                    name = running.pop(future)
                    try:
                        report = future.result()
                    except Exception as exc:
                        report = failure(steps[name]["tool"], f"Worker error: {exc}")
                    weight = len(json.dumps(report, allow_nan=False).encode()) + len(json.dumps(report['findings']).encode())
                    if exhausted or size + weight > MAX_REPORT - 256 * 1024:
                        exhausted = True
                        cancelled.set()
                        report = failure(steps[name]['tool'], 'Aggregate report exceeds its budget; configure fewer checks')
                    else:
                        size += weight
                    report = apply_baseline(report, baseline)
                    code = gated_exit(report, fail_on)
                    status = "passed" if code == 0 else "allowed_failure" if steps[name].get("allow_failure", False) and not exhausted else "failed"
                    finished[name] = {"name": name, "status": status, "report": report}
                    if progress:
                        progress(name, status)
    except BaseException:
        cancelled.set()
        for future in running:
            future.cancel()
        raise
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
    ordered = [finished[name] for name in steps]
    findings = []
    for step in ordered:
        for finding in step["report"]["findings"]:
            findings.append({**finding, "tool": step["report"]["tool"], "check": step["name"]})
    failed = sum(s["status"] in {"failed", "skipped"} for s in ordered)
    tool_error = exhausted or any(s["status"] == "failed" and s["report"]["status"] == "error" for s in ordered)
    report = {"schema": 1, "version": __version__, "tool": "check", "status": "error" if tool_error else "failed" if failed else "completed", "exit_code": 2 if tool_error else 1 if failed else 0, "summary": f"{len(ordered) - failed}/{len(ordered)} checks passed or were explicitly allowed to fail", "seconds": round(time.monotonic() - started, 4), "findings": findings, "data": {}, "checks": ordered}
    report = apply_baseline(report, baseline)
    if len(json.dumps(report, allow_nan=False).encode()) > MAX_REPORT:
        return failure('check', 'Aggregate report exceeds 8 MiB; configure fewer checks')
    return report
