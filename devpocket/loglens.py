"""Stream text/JSONL logs into bounded, redacted groups of repeated events."""
from __future__ import annotations

from contextlib import ExitStack
import gzip
import json
from pathlib import Path
import re
import sys

from .common import redact

MAX_LINE = 65536
MAX_RECORD = 16384
LEVEL = re.compile(r"\b(CRITICAL|FATAL|ERROR|WARN(?:ING)?|INFO|DEBUG|TRACE)\b", re.I)
STAMP = re.compile(r"^\s*\[?(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\]?")
PREFIX = re.compile(r"^\s*(?:\[(?:CRITICAL|FATAL|ERROR|WARN(?:ING)?|INFO|DEBUG|TRACE)\]|(?:CRITICAL|FATAL|ERROR|WARN(?:ING)?|INFO|DEBUG|TRACE)\b)", re.I)


def safe_text(value):
    # Reports must not replay terminal control sequences from untrusted logs.
    value = re.sub(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))", "", str(value))
    return redact("".join(c for c in value if c in "\n\t" or (ord(c) >= 32 and ord(c) != 127)))


def bounded_lines(stream):
    number = 0
    while True:
        text = stream.readline(MAX_LINE + 1)
        if not text:
            break
        number += 1
        truncated = len(text) > MAX_LINE
        if truncated and not text.endswith("\n"):
            while True:
                rest = stream.readline(MAX_LINE + 1)
                if not rest or rest.endswith("\n"):
                    break
        yield number, text[:MAX_LINE].rstrip("\r\n") + (" [line truncated]" if truncated else ""), truncated


def parse_line(line):
    """Return level, timestamp and message; JSON arrays/scalars stay plain text."""
    if line.lstrip().startswith("{"):
        try:
            obj = json.loads(line)
        except ValueError:
            obj = None
        if isinstance(obj, dict):
            level = str(obj.get("level", obj.get("severity", obj.get("levelname", "")))).upper()
            level = "WARNING" if level == "WARN" else "CRITICAL" if level == "FATAL" else level
            stamp = obj.get("timestamp", obj.get("time", obj.get("asctime")))
            message = obj.get("message", obj.get("msg", obj.get("error", line)))
            if not isinstance(message, str):
                message = json.dumps(message, sort_keys=True)
            return level if level in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "TRACE"} else "UNKNOWN", str(stamp) if stamp is not None else None, message
    stamp = STAMP.match(line)
    remaining = line[stamp.end():].lstrip(" :-|") if stamp else line
    match = LEVEL.search(remaining[:120]) if stamp or PREFIX.match(line) else None
    if match:
        level = match[1].upper()
        level = "WARNING" if level == "WARN" else "CRITICAL" if level == "FATAL" else level
        message = remaining[match.end():].lstrip(" ]:-|")
    else:
        level, message = "UNKNOWN", remaining
        if "Traceback (most recent call last)" in line or re.match(r"^[\w.]+(?:Error|Exception):", line):
            level = "ERROR"
    return level, stamp[1] if stamp else None, message


def records(stream):
    current = None
    for number, line, truncated in bounded_lines(stream):
        if not line.strip():
            continue
        structured = bool(STAMP.match(line) or PREFIX.match(line) or line.lstrip().startswith("{"))
        traceback = line.startswith("Traceback (most recent call last)")
        continuation = current is not None and not structured and not traceback and (line[:1].isspace() or current.get("traceback"))
        if continuation:
            current["message"] = (current["message"] + "\n" + line)[:MAX_RECORD]
            current["record_truncated"] |= len(current["message"]) >= MAX_RECORD
            if line and not line[:1].isspace() and re.match(r"^[\w.]+(?:Error|Exception):", line):
                current["traceback"] = False
            continue
        if current is not None:
            yield current
        level, stamp, message = parse_line(line)
        current = {"line": number, "level": level, "timestamp": stamp, "message": message[:MAX_RECORD], "traceback": traceback or "Traceback (most recent call last)" in message, "record_truncated": len(message) > MAX_RECORD}
    if current is not None:
        yield current


def signature(message, exact=False):
    text = safe_text(message)
    if exact:
        return text
    text = re.sub(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", "<uuid>", text, flags=re.I)
    text = re.sub(r"\b0x[0-9a-f]+\b", "<hex>", text, flags=re.I)
    text = re.sub(r"(?<![\w])[-+]?\d+(?:\.\d+)?(?![\w])", "<n>", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def analyse(inputs, *, exact=False, include_all=False, max_groups=2000):
    groups = {}
    total = matched = overflow = truncated = 0
    for source, stream in inputs:
        for rec in records(stream):
            total += 1
            truncated += int(rec["record_truncated"])
            if not include_all and rec["level"] not in {"ERROR", "WARNING", "CRITICAL"}:
                continue
            matched += 1
            clean = safe_text(rec["message"])
            key = (rec["level"], signature(clean, exact))
            if key not in groups:
                if len(groups) >= max_groups:
                    overflow += 1
                    continue
                groups[key] = {"level": rec["level"], "signature": key[1], "count": 0, "first_seen": None, "last_seen": None, "samples": []}
            group = groups[key]
            group["count"] += 1
            location = {"source": safe_text(source), "line": rec["line"], "timestamp": safe_text(rec["timestamp"]) if rec["timestamp"] is not None else None}
            if group["first_seen"] is None:
                group["first_seen"] = location
            group["last_seen"] = location
            sample = clean[:1000]
            if len(group["samples"]) < 3 and sample not in group["samples"]:
                group["samples"].append(sample)
    return {"schema": 1, "records_scanned": total, "records_matched": matched, "ungrouped_records": overflow, "truncated_records": truncated, "groups": sorted(groups.values(), key=lambda g: (-g["count"], g["level"], g["signature"]))}


def execute(args):
    if not 1 <= args.top <= 1000 or not 1 <= args.max_groups <= 10000:
        raise ValueError("--top must be 1..1000 and --max-groups must be 1..10000")
    if args.paths.count("-") > 1:
        raise ValueError("Standard input (-) can only appear once")
    with ExitStack() as stack:
        inputs = []
        for name in args.paths:
            if name == "-":
                stream = sys.stdin
            else:
                path = Path(name)
                opener = gzip.open if path.suffix.lower() == ".gz" else open
                stream = stack.enter_context(opener(path, "rt", encoding="utf-8", errors="replace"))
            inputs.append((name, stream))
        report = analyse(inputs, exact=args.exact, include_all=args.all, max_groups=args.max_groups)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"{report['records_scanned']} records scanned; {report['records_matched']} matched; {len(report['groups'])} groups")
        for group in report["groups"][:args.top]:
            print(f"\n{group['count']}x {group['level']} | {group['signature'][:160]}")
            for label in ("first_seen", "last_seen"):
                loc = group[label]
                print(f"  {label.replace('_', ' ')}: {loc['source']}:{loc['line']} ({loc['timestamp'] or 'no timestamp'})")
            print("  sample: " + group["samples"][0].replace("\n", "\n          "))
        if report["ungrouped_records"]:
            print(f"\nGroup limit reached: {report['ungrouped_records']} matching records were not grouped. Narrow input or increase --max-groups.")
        if report["truncated_records"]:
            print(f"{report['truncated_records']} oversized records were truncated.")
    return 0
