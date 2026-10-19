![DevPocket — small tools, fewer rabbit holes](docs/assets/banner.svg)

[![Tests](https://github.com/HamWebDevs/DevPocket/actions/workflows/tests.yml/badge.svg)](https://github.com/HamWebDevs/DevPocket/actions/workflows/tests.yml)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
[![MIT licence](https://img.shields.io/badge/licence-MIT-82edc4)](LICENSE)
![Runtime dependencies: zero](https://img.shields.io/badge/runtime_dependencies-zero-82edc4)

**An extensible toolkit for local developer diagnostics.**

**Version 1:** installable CLI, stable SDK API v1, configuration/editor contracts and a reusable GitHub Action. [Compatibility and upgrading](docs/compatibility.md) · [CI integration](docs/github-action.md)

Ten built-in SDK tools, production-build audits, dependency-aware workspace checks, a versioned plugin SDK, opt-in content-addressed caching, baseline-aware quality gates and MCP connectivity. Run diagnostics locally, wire them into CI, or let a coding assistant call the same tools — without a hosted service or runtime dependencies.

[Quick start](#quick-start) · [Build a plugin](#build-and-connect-your-own-tools) · [MCP](docs/mcp.md) · [The toolkit](#the-toolkit) · [Documentation](#documentation) · [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md)

## Put the same checks in CI

```yaml
- uses: HamWebDevs/DevPocket@v1
  id: diagnostics
  with:
    mode: workspace
    root: .
```

After checkout and your normal build, run reviewed project/workspace checks in an isolated Python environment. Collect JSON/SARIF artifacts, new-finding annotations and a job summary; a failed gate still fails the workflow. Optional plugin requirements connect your own diagnostics and ReclaimLab evidence. [Complete workflow, inputs and outputs →](docs/github-action.md)

Validate configuration before running it, without importing plugins or executing checks:

```bash
devpocket config validate --format json
devpocket config validate --root examples/workspace --workspace
devpocket config schema --kind project
```

Editor schemas ship with the package. Runtime preflight additionally checks dependencies, tool availability and built-in inputs; plugin inputs remain explicitly deferred to workers. [Configuration contracts and limits →](docs/configuration.md)

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

Requires **Python 3.10+**. After cloning, `python -m pip install .` adds `devpocket` and ten standalone aliases, including `workspace-plan`. Versioned wheels are also available in [GitHub releases](https://github.com/HamWebDevs/DevPocket/releases). This project is not published to PyPI.

## Coordinate a whole workspace

```bash
devpocket workspace plan --root examples/workspace --format json
devpocket workspace check --root examples/workspace --jobs 4
devpocket workspace check --root examples/workspace --changed-file packages/lib/api.py --format sarif
```

Plan project/check dependencies before running them. Keep each project's plugins and caches scoped to its root, select changed projects and affected dependents, then collect one report with workspace-relative findings. Review a plan digest before execution or expose read-only planning to your coding assistant. Unselected projects remain explicit in SARIF. [Workspace configuration, selection and limits →](docs/workspaces.md)

## Inspect the build you will deploy

```bash
assetguard --root dist --snapshot artifacts/build-before.json
# Make your change and finish your normal build.
assetguard --root dist --baseline artifacts/build-before.json --max-growth-kib 32
```

**AssetGuard** measures raw/gzip sizes, catches missing HTML resources, CSS imports, fonts, background images and deployment-path mistakes, flags private files and source maps, and finds identical content across renamed chunks. Stylesheet references resolve from their own file locations; malformed CSS coverage is reported explicitly. Choose total, individual-asset and growth budgets for CI. It works on finished artifacts from any toolchain and executes no target code. Gzip estimates describe build files; they are not browser transfer or route-performance measurements.

Try `assetguard --root examples/web-dist` from this checkout. [Build comparisons, budgets, SARIF and MCP →](docs/assetguard.md)

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
| **`config-validate`** | You want a configuration preflight with no check execution or plugin imports. | [Configuration contracts](docs/configuration.md) |
| **`workspace-plan`** | Several project roots share prerequisites and you need a reviewable dependency plan. Execute it with `devpocket workspace check`. | [Workspace checks](docs/workspaces.md) |
| **`assetguard`** | You need to review production assets, resource links and build-size regressions before deployment. | [Build auditing](docs/assetguard.md) |
| `oopsfile` | A command fails and you need a focused debugging report. | [Error reports](docs/cli-reference.md#oopsfile--useful-error-reports-in-one-command) |
| `envtwin` | Something works on one machine but not another. | [Environment comparisons](docs/cli-reference.md#envtwin--compare-what-actually-differs) |
| `undorun` | You want a backup and a record of a script's file changes. | [Backups and restoration](docs/cli-reference.md#undorun--inspect-and-reverse-scoped-file-changes) |
| `flaketrail` | A test passes sometimes and fails other times. | [Repeated runs](docs/cli-reference.md#flaketrail--make-intermittent-failure-visible) |
| `reporadar` | You want to catch the little setup problems before sharing a repo. | [Repository checks](docs/cli-reference.md#reporadar--the-small-checks-people-forget) |
| **`loglens`** | Thousands of log lines hide a few recurring errors. | [Log analysis](docs/loglens.md) |
| **`importdoctor`** | Python imports the wrong thing — or cannot find it at all. | [Import diagnostics](docs/importdoctor.md) |

Use either `devpocket TOOL ...` or the standalone `TOOL ...` for the original utilities. `workspace-plan` aliases `devpocket workspace plan`; run plans with `devpocket workspace check`.

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

- [Workspace plans, affected projects and combined reports](docs/workspaces.md)
- [GitHub Action: isolated checks, annotations, summaries and artifacts](docs/github-action.md)
- [Configuration preflight and editor schemas](docs/configuration.md)
- [Version 1 contracts, compatibility and migration](docs/compatibility.md)
- [Plugin SDK, package discovery and reference implementation](docs/plugins.md)
- [AssetGuard: production builds, content snapshots and size budgets](docs/assetguard.md)
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
