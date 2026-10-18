![DevPocket — small tools, fewer rabbit holes](docs/assets/banner.svg)

[![Tests](https://github.com/instalsxx/DevPocket/actions/workflows/tests.yml/badge.svg)](https://github.com/instalsxx/DevPocket/actions/workflows/tests.yml)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
[![MIT licence](https://img.shields.io/badge/licence-MIT-82edc4)](LICENSE)
![Runtime dependencies: zero](https://img.shields.io/badge/runtime_dependencies-zero-82edc4)

**Seven small command-line tools for the frustrating parts of programming.**

Make error reports worth reading. Compare environments. Restore a script's file changes. Investigate flaky tests, messy logs and Python imports — without an account, a server or an AI subscription.

[Quick start](#quick-start) · [The toolkit](#the-toolkit) · [Documentation](#documentation) · [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md)

## Quick start

Install from this repository in your preferred Python environment:

```bash
python -m pip install "git+https://github.com/instalsxx/DevPocket.git"
devpocket --help
```

Or clone it and run directly, with no installation:

```bash
git clone https://github.com/instalsxx/DevPocket.git
cd DevPocket
python -m devpocket loglens examples/events.log
python -m devpocket importdoctor json
```

Requires **Python 3.10+**. After cloning, `python -m pip install .` adds the `devpocket` command and all seven standalone aliases. This project is not published to PyPI; use the source above.

## The toolkit

| Command | Use it when… | Guide |
| --- | --- | --- |
| `oopsfile` | A command fails and you need a focused debugging report. | [Error reports](docs/cli-reference.md#oopsfile--useful-error-reports-in-one-command) |
| `envtwin` | Something works on one machine but not another. | [Environment comparisons](docs/cli-reference.md#envtwin--compare-what-actually-differs) |
| `undorun` | You want a backup and a record of a script's file changes. | [Backups and restoration](docs/cli-reference.md#undorun--inspect-and-reverse-scoped-file-changes) |
| `flaketrail` | A test passes sometimes and fails other times. | [Repeated runs](docs/cli-reference.md#flaketrail--make-intermittent-failure-visible) |
| `reporadar` | You want to catch the little setup problems before sharing a repo. | [Repository checks](docs/cli-reference.md#reporadar--the-small-checks-people-forget) |
| **`loglens`** | Thousands of log lines hide a few recurring errors. | [Log analysis](docs/loglens.md) |
| **`importdoctor`** | Python imports the wrong thing — or cannot find it at all. | [Import diagnostics](docs/importdoctor.md) |

Use either `devpocket TOOL ...` or the standalone `TOOL ...` after installation.

## A few useful commands

```bash
# Failed command → a local Markdown report
oopsfile run -- python app.py

# Group recurring errors in a large or compressed log
loglens application.log application.log.gz --top 5

# Check import resolution without executing the target package
importdoctor requests --root .

# Compare captured Python environments
envtwin diff laptop.json ci.json

# Repeat an intermittent test and keep the evidence
flaketrail --runs 20 -- python -m unittest tests.test_sometimes
```

Oopsfile and FlakeTrail examples preserve failures through a nonzero exit status. Their output reports are local; review them before sharing.

### What LogLens shows

With the bundled `examples/events.log` fixture:

```text
4 records scanned; 3 matched; 2 groups

2x ERROR | request <n> failed: upstream timeout
  first seen: examples/events.log:2 (2026-10-18T10:00:01Z)
  last seen: examples/events.log:3 (2026-10-18T10:00:02Z)
  sample: request 481 failed: upstream timeout
```

LogLens groups variable numbers and IDs by default. Use `--exact` when different numbers, such as HTTP status codes, must remain separate. JSON output includes counts, samples and first/last locations for every retained group.

## Designed to stay small

- **No runtime dependencies.** Python's standard library does the work.
- **Local operation.** No automatic uploads or telemetry. Wrapped commands retain their own normal network behaviour.
- **Useful evidence.** Reports show locations, captured differences and explicit limits.
- **Predictable file handling.** Reports never silently overwrite an existing file. UndoRun previews restoration and checks for later edits before applying it.
- **Portable source.** The test workflow covers Linux, macOS and Windows on Python 3.10, 3.12 and 3.14.

**Know the boundaries:** redaction is best-effort; UndoRun is a scoped backup tool, not a sandbox; LogLens grouping and ImportDoctor's static resolution are diagnostic clues. Each guide describes its limits. See [SECURITY.md](SECURITY.md).

## Documentation

- [CLI reference: original five tools, flags and exit codes](docs/cli-reference.md)
- [LogLens: text, JSONL, compressed logs and grouping](docs/loglens.md)
- [ImportDoctor: shadows, namespaces and interpreter mismatches](docs/importdoctor.md)
- [Changelog](CHANGELOG.md)
- [Contribution guide](CONTRIBUTING.md)

## Development

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
python -m devpocket reporadar --root .
```

Tests use isolated temporary fixtures. Bug reports, practical examples and focused pull requests are welcome. Open an [issue](https://github.com/instalsxx/DevPocket/issues) or read the [contribution guide](CONTRIBUTING.md).

---

MIT licensed · Built by [Anthony Fulton](https://github.com/instalsxx)
