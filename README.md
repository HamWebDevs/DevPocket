![DevPocket — small tools, fewer rabbit holes](docs/assets/banner.svg)

[![Tests](https://github.com/HamWebDevs/DevPocket/actions/workflows/tests.yml/badge.svg)](https://github.com/HamWebDevs/DevPocket/actions/workflows/tests.yml)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
[![MIT licence](https://img.shields.io/badge/licence-MIT-82edc4)](LICENSE)
![Runtime dependencies: zero](https://img.shields.io/badge/runtime_dependencies-zero-82edc4)

**An extensible toolkit for local developer diagnostics.**

Seven built-in tools, a versioned plugin SDK, parallel project checks, opt-in content-addressed caching, baseline-aware quality gates and MCP connectivity. Run diagnostics locally, wire them into CI, or let a coding assistant call the same tools — without a hosted service or runtime dependencies.

[Quick start](#quick-start) · [Build a plugin](#build-and-connect-your-own-tools) · [MCP](docs/mcp.md) · [The toolkit](#the-toolkit) · [Documentation](#documentation) · [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md)

## Quick start

Install from this repository in your preferred Python environment:

```bash
python -m pip install "git+https://github.com/HamWebDevs/DevPocket.git"
devpocket --help
```

Or clone it and run directly, with no installation:

```bash
git clone https://github.com/HamWebDevs/DevPocket.git
cd DevPocket
python -m devpocket loglens examples/events.log
python -m devpocket importdoctor json
```

Requires **Python 3.10+**. After cloning, `python -m pip install .` adds the `devpocket` command and all seven standalone aliases. This project is not published to PyPI; use the source above.

## Configure checks once

```bash
devpocket init
devpocket check --jobs 4
devpocket check --format sarif --output checks.sarif
```

Independent checks run in parallel worker processes. Define dependencies, timeouts and allowed failures in `.devpocket.json`. Use fingerprints and baselines to gate new problems while retaining evidence of existing ones. The committed config lets you try `devpocket check` immediately from this checkout; use `init` in a new project.

[Project configuration, reports and baselines →](docs/project-checks.md)

## Reuse work when the inputs are unchanged

DevPocket 0.4 can cache deterministic read-only checks. Both the tool and project must opt in. Declare every result-affecting file/directory and environment variable; content, runtime and tool-code fingerprints decide reuse. Cached findings still pass through current baseline, dependency and severity gates.

```bash
devpocket check --format json
devpocket cache status --json
devpocket check --no-cache
devpocket cache clear
```

Reports expose hits, misses and bypass reasons. Failed execution, unsafe paths and incomplete snapshots never become cached success. [Configuration, contracts and limits →](docs/cache.md)

## Build and connect your own tools

```bash
devpocket plugins scaffold ./my-check --name long-lines
python -m pip install ./my-check
devpocket plugins enable long-lines
devpocket run long-lines --input '{"path":"README.md","max_length":100}'
```

The scaffold is a complete Python package with a runner, schema, entry point and test. Plugins are discovered through standard Python package metadata and load only when enabled and used. They work with the same CLI, project checks, reports and optional MCP exposure as the built-in tools.

[Plugin SDK and working reference plugin →](docs/plugins.md)

[ReclaimLab](https://github.com/HamWebDevs/ReclaimLab) is a companion example: its read-only trace and repeated-study plugins work with project checks, result caching, SARIF and MCP.

## Connect a coding assistant

```bash
devpocket serve --root /absolute/path/to/project --print-config
```

Configure a compatible MCP client to launch the local stdio server. It exposes read-only repository, import, environment and log diagnostics by default. Reviewed read-only plugins can be exposed explicitly. Command-running tools stay outside the MCP surface.

[MCP connection guide and protocol limits →](docs/mcp.md)

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

## Designed for real workflows

- **No runtime dependencies.** Python's standard library does the work.
- **Local operation.** No automatic uploads or telemetry. Wrapped commands retain their own normal network behaviour.
- **Interoperable evidence.** A shared finding model powers text, JSON, Markdown and SARIF reports.
- **Extensible by design.** Versioned SDK, schema validation, metadata discovery, process isolation and project-specific plugin opt-in.
- **CI and assistant integration.** Dependency-aware checks, stable fingerprints, severity gates and an MCP stdio server.
- **Predictable file handling.** Reports never silently overwrite an existing file. UndoRun previews restoration and checks for later edits before applying it.
- **Portable source.** The test workflow covers Linux, macOS and Windows on Python 3.10, 3.12 and 3.14.

**Know the boundaries:** redaction is best-effort; UndoRun is a scoped backup tool, not a sandbox; LogLens grouping and ImportDoctor's static resolution are diagnostic clues. Each guide describes its limits. See [SECURITY.md](SECURITY.md).

## Documentation

- [Plugin SDK, package discovery and reference implementation](docs/plugins.md)
- [Project checks, structured runs, reports and baselines](docs/project-checks.md)
- [Deterministic result caching, invalidation and controls](docs/cache.md)
- [MCP server and client connection](docs/mcp.md)
- [CLI reference: original five tools, flags and exit codes](docs/cli-reference.md)
- [LogLens: text, JSONL, compressed logs and grouping](docs/loglens.md)
- [ImportDoctor: shadows, namespaces and interpreter mismatches](docs/importdoctor.md)
- [Changelog](CHANGELOG.md)
- [Release packaging and publication](docs/releases.md)
- [Contribution guide](CONTRIBUTING.md)

## Development

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
python -m devpocket check
python examples/verify_extension.py
```

Tests use isolated temporary fixtures. The extension verification script builds and installs the host and a generated plugin in a fresh environment; Python build dependencies may be downloaded from your configured package registry. Bug reports, practical examples and focused pull requests are welcome. Open an [issue](https://github.com/HamWebDevs/DevPocket/issues) or read the [contribution guide](CONTRIBUTING.md).

---

MIT licensed · Built by [HamWebDevs](https://github.com/HamWebDevs)
