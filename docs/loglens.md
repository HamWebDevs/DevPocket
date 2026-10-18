# LogLens

[Back to DevPocket](../README.md)

Find repeated warnings and errors without reading every line of a log. LogLens reads text, JSONL and `.gz` files sequentially, groups similar messages and keeps source evidence.

## Usage

```bash
loglens application.log
loglens current.log previous.log.gz --top 5
loglens application.log --exact --json
```

Piped input is explicit:

```bash
cat application.log | loglens - --json
```

After cloning, use `python -m devpocket loglens examples/events.log` instead of the standalone command if you have not installed the package.

## Recognised records

- Text prefixes such as `ERROR message`, `[WARNING] message` and `2026-10-18T10:00:01Z ERROR message`.
- ISO-like dates with a `T` or space separator, optional fractional seconds and optional numeric timezone or `Z`.
- JSONL objects with `level`, `severity` or `levelname`; `timestamp`, `time` or `asctime`; and `message`, `msg` or `error` fields. If multiple aliases exist, the first in that order wins.
- Numeric JSON timestamps are retained as strings, without assuming a unit or converting them.
- Standard Python tracebacks and indented continuation lines are attached to the preceding record. The unindented final exception line is included in a traceback.

It is a bounded heuristic parser, not a complete implementation of every application's log grammar. Untimestamped plain lines have level `UNKNOWN`; use `--all` to include them. Timestamp-only records without a recognised level also have level `UNKNOWN`. JSON metadata outside the selected fields is not retained. Severity embedded in arbitrary prose is not treated as a record prefix.

## Grouping

By default, decimal numbers, UUIDs and `0x...` addresses become placeholders. This groups messages such as `request 481 failed` and `request 902 failed`. It can also merge meaningful differences, including HTTP status codes. Use `--exact` to disable this normalisation. Redaction and terminal-control removal always apply.

Groups are keyed by level plus message signature and sorted by descending count. Each keeps up to three distinct message samples, capped at 1,000 characters each. Locations include filename, physical starting line and timestamp when available.

**First and last mean input order**, not chronological minimum and maximum. Files are processed in the order supplied; rotated logs are not automatically sorted.

## Flags and limits

| Flag | Default | Meaning |
| --- | --- | --- |
| `--all` | Off | Include INFO, DEBUG, TRACE and UNKNOWN records too. |
| `--exact` | Off | Keep numbers and IDs distinct. |
| `--top N` | 10 | Print up to N groups in text output (1–1,000). |
| `--max-groups N` | 2,000 | Retain at most N distinct groups (1–10,000). |
| `--json` | Off | Emit every retained group, independent of `--top`. |

Input is read incrementally, not loaded as a whole. Physical lines are capped at 65,536 characters and records at 16,384 characters. Oversized content is truncated. Distinct groups are bounded: matching records for new signatures after the cap are counted as `ungrouped_records`; counts for existing signatures continue to grow. Invalid UTF-8 is replaced. Only `.gz` suffixes trigger decompression; ZIP archives are not supported.

Redaction is best-effort. Samples, filenames and signatures can still contain private information. Output is sent to stdout; save it using your shell if wanted. No files are rewritten and nothing is uploaded. Exit code is 0 for a completed scan (including logs containing errors), 2 for a tool/input error, 130 for interruption.
