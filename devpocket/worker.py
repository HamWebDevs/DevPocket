"""One isolated invocation. Stdout is a single machine-readable report."""
import json
import sys
import os
import signal
from .engine import execute, failure


def main():
    if os.name == "posix":
        def terminate(signum, frame):
            raise SystemExit(143)
        signal.signal(signal.SIGTERM, terminate)
    try:
        raw = sys.stdin.read(1024 * 1024 + 1)
        if len(raw.encode()) > 1024 * 1024:
            raise ValueError("Worker request exceeds 1 MiB")
        data = json.loads(raw)
        report = execute(data["tool"], data.get("input", {}), data["root"], data.get("plugins", []), data.get("allow_exec", False), cache_policy=data.get("cache"))
    except Exception as exc:
        report = failure("worker", f"{type(exc).__name__}: {exc}")
    print(json.dumps(report, allow_nan=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
