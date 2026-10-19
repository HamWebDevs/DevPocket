# Changelog

User-visible changes are recorded here. Repository versions are not PyPI releases.

## 0.6.0 — 2026-10-19

- Add reviewable multi-project workspace plans and dependency-aware execution using one globally bounded pool of isolated check workers.
- Select explicit projects or changed-file owners, affected dependents and prerequisites; configuration/shared/unmapped changes conservatively select every project.
- Preserve project-local roots, enabled plugins, timeout/cache declarations, allowed failures and current baseline/severity gates.
- Namespace findings by project, relocate locations to the workspace root and combine JSON, text, Markdown and SARIF reports with explicit selected/unselected scope.
- Add expected-plan digest preflight, a read-only `workspace-plan` SDK/MCP tool and standalone alias; planning never imports plugins or runs target checks.
- Bound project/check/config/selection/report sizes and cancel active work on aggregate resource exhaustion. Plan hashes bind configuration/selection only, not source contents or plugin authenticity.
- Add a complete three-project example, cross-platform workspace CI checks and developer documentation. Keep SDK API v1 unchanged and verify scaffold compatibility through host 0.6.

## 0.5.0 — 2026-10-18

- Add AssetGuard: bundler-independent production-artifact inventories, deterministic gzip estimates and per-kind size summaries.
- Resolve explicit HTML resource references against document/base URLs and deployment prefixes; locate missing resources without executing target code or fetching URLs.
- Detect duplicate content, source maps and private deployment entries; never read secret-like file contents.
- Compare validated content-hash snapshots, including byte-identical renames, unique new content and total/asset/growth budgets. Missing measurements cannot pass requested budgets.
- Add the standalone `assetguard` command, read-only structured/SARIF/MCP integration and a working three-file build/CI example.
- Keep SDK API v1 unchanged and update the scaffold/reference-plugin dependency range for DevPocket 0.4/0.5 compatibility.
- Bound traversal, inputs and reports; refuse symlinks and observed build mutations. Keep the build auditor uncached so deployment metadata is inspected on every run.

## 0.4.0 — 2026-10-18

- Add verified GitHub release builds with wheels, source distributions, versioned tags and SHA-256 checksums.
- Credit HamWebDevs consistently in the README, licence and package metadata.
- Opt-in, content-addressed caching for deterministic read-only project checks, with explicit file/directory and environment declarations.
- Invalidate on content, missing/added/deleted inputs, parameters, runtime/package versions, tool source and cache contract changes; recheck inputs before saving.
- Bound cache hashing/storage, refuse symlinks, validate cached reports, expire entries and retain fresh severity/baseline/dependency gates.
- Add `check --no-cache`, `cache status` and `cache clear`; expose hit/miss/bypass evidence in structured and text reports.
- Add optional `ToolSpec.cache_version` without changing API v1. LogLens and newly scaffolded plugins support the contract; other built-ins remain uncached.

## 0.3.0 — 2026-10-18

### Added

- Public API v1 plugin SDK: typed tool context/spec/result/finding contracts, strict schema subset and stable finding fingerprints.
- Metadata-only plugin discovery, project-specific enable/disable, collision detection, complete scaffolding and a packaged reference plugin.
- A structured runner for all seven built-ins and installed plugins, with isolated workers, bounded diagnostics, timeouts and explicit execution opt-in.
- JSON project configuration and dependency-aware parallel checks, severity gates, allowed failures and baseline suppression of existing findings.
- Shared text, JSON, Markdown and SARIF 2.1.0 reports.
- Local stdio MCP server with read-only built-in diagnostics, explicit plugin exposure, structured tool results, bounded concurrency and cancellation.
- Real-wheel extension verification across installation, discovery, CLI, checks, baselines, SARIF and MCP.
- Extension, project-check and integration guides; repository self-check configuration.

### Fixed

- Bounded credential-key matching avoids excessive backtracking on very long unbroken output.
- POSIX worker termination can unwind built-in nested command runners before hard termination. Windows descendant-cleanup limits remain documented.

### Compatibility

- Original seven tool commands keep their interfaces and exit conventions.
- Plugin API v1 and JSON report/config schema 1 are new in this pre-1.0 release. Scaffolded plugins declare a compatible 0.3 host range.

## 0.2.0 — 2026-10-18

### Added

- LogLens: incremental text/JSONL/gzip log analysis, normalised or exact grouping, first/last source evidence, bounded samples, stdin and JSON output.
- ImportDoctor: static dotted import resolution, local-shadow checks, namespace locations, distribution metadata and interpreter-path comparison without executing target modules.
- Standalone `loglens` and `importdoctor` commands.
- Dedicated guides, a sample log and diagnostic regression tests.
- Repository banner, status badges, package links, issue forms, pull request template and Codex contributor instructions.

### Changed

- Reworked the README around installation, tool discovery and practical examples; moved detailed original-tool documentation to the CLI reference.
- Extended CI with installed-command smoke checks and a repository scan.

## 0.1.0 — 2026-10-18

- Initial Oopsfile, EnvTwin, UndoRun, FlakeTrail and RepoRadar commands.
- Local reports, bounded command capture, best-effort redaction, scoped file backups and conflict-aware restoration.
- Integration tests and a Python/OS test matrix.
