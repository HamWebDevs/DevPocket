"""Shared bounded process capture, redaction, and filesystem utilities."""
from __future__ import annotations

import fnmatch
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time

EXCLUDED = {".git", ".hg", ".svn", ".venv", "venv", "node_modules", "__pycache__", ".devpocket", "dist", "build", ".pytest_cache", ".mypy_cache"}
SENSITIVE = (".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*", "id_ed25519*", "credentials*", "*secrets*", "*.sqlite*", "*.db")
MAX_CAPTURE = 128 * 1024


def sensitive(path: Path) -> bool:
    # Example files are templates, not credentials.
    if path.name in {".env.example", ".env.sample", ".env.template"}:
        return False
    return any(fnmatch.fnmatch(path.name.lower(), p) for p in SENSITIVE)


def redact(text: str) -> str:
    text = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", "[REDACTED PRIVATE KEY]", text, flags=re.S)
    text = re.sub(r"(?i)(https?://)[^\s/@:]+:[^\s/@]+@", r"\1[REDACTED]@", text)
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1[REDACTED]", text)
    text = re.sub(r"\b(?:gh[pousr]_[A-Za-z0-9_]{16,}|github_pat_[A-Za-z0-9_]+|AKIA[A-Z0-9]{16}|sk-[A-Za-z0-9_-]{16,})\b", "[REDACTED]", text)
    text = re.sub(r'''(?im)((?:[\w-]*(?:password|passwd|secret|token|api[_-]?key)[\w-]*)["']?\s*[:=]\s*)(?:"[^"\n]*"|'[^'\n]*'|[^\s,;]+)''', r"\1[REDACTED]", text)
    text = re.sub(r"(?i)(--(?:password|secret|token|api-key)\s+)\S+", r"\1[REDACTED]", text)
    home = str(Path.home())
    if len(home) > 1:
        text = text.replace(home, "~")
    return text


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Refuse to silently overwrite a report or follow a symlink.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)


def write_json(path: Path, data) -> None:
    write_text(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def load_json(path: Path):
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("JSON input exceeds 32 MiB")
    return json.loads(path.read_text(encoding="utf-8"))


def files(root: Path, extra=()):
    for base, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED and not (Path(base) / d).is_symlink() and not any(fnmatch.fnmatch((Path(base) / d).relative_to(root).as_posix(), p) for p in extra))
        for name in sorted(names):
            p = Path(base) / name
            rel = p.relative_to(root).as_posix()
            if p.is_symlink() or not p.is_file() or sensitive(p) or any(fnmatch.fnmatch(rel, pat) for pat in extra):
                continue
            yield p


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def run(command, *, cwd=None, timeout=60.0):
    """Execute argv without a shell. Capture each stream's last 128 KiB."""
    if not command:
        raise ValueError("Supply a command after --")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Timeout must be positive")
    start = time.monotonic()
    proc = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=(os.name == "posix"))
    buffers = [bytearray(), bytearray()]
    totals = [0, 0]

    def drain(stream, index):
        try:
            while True:
                block = stream.read(8192)
                if not block:
                    break
                totals[index] += len(block)
                buffers[index].extend(block)
                if len(buffers[index]) > MAX_CAPTURE:
                    del buffers[index][:-MAX_CAPTURE]
        finally:
            stream.close()

    threads = [threading.Thread(target=drain, args=(stream, i), daemon=True) for i, stream in enumerate((proc.stdout, proc.stderr))]
    for thread in threads:
        thread.start()
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        if os.name == "posix":
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            proc.kill()
        proc.wait()
    except BaseException:
        if os.name == "posix":
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            proc.kill()
        proc.wait()
        raise
    for thread in threads:
        thread.join(timeout=1)
    streams = [bytes(b).decode("utf-8", errors="replace") for b in buffers]
    return {"returncode": 124 if timed_out else proc.returncode, "timed_out": timed_out, "seconds": round(time.monotonic() - start, 4), "stdout": streams[0], "stderr": streams[1], "truncated": [n > MAX_CAPTURE for n in totals]}


def exit_code(code: int) -> int:
    return 128 - code if code < 0 else code
