# Changelog

User-visible changes are recorded here. Repository versions are not PyPI releases.

## 1.2.0 — 2026-10-21

- Add EnvGuard: compare dotenv names against an example, locate missing/empty assignments, duplicates and undocumented keys, and never evaluate or return values.
- Parse quoted multiline values without treating their contents as variable names; support explicit optional-name and extra-name policies.
- Add TestLens: aggregate saved JUnit XML shards, count actual testcase outcomes, flag mixed recorded outcomes and enforce minimum-test/maximum-skip gates. Failed tests remain failed through finding baselines and disabled severity gates.
- Reject incomplete counter declarations, malformed XML, DTDs/entities, unsafe paths, symlinks, redirected directories, observed file mutations and oversized inputs. Withhold JUnit log/failure bodies and dotenv values.
- Connect both tools to standalone aliases, CLI, project/workspace checks, JSON/SARIF and read-only MCP. Opt-in TestLens caching requires every XML input; EnvGuard stays uncached.
- Include a passing CI example, installed-wheel smoke checks and privacy/evidence regression tests. Preserve SDK API v1, configuration schemas and zero runtime dependencies.

## 1.1.1 — 2026-10-20

- Improve first-run positioning and provide a complete copyable GitHub Actions workflow for project diagnostics.
- Add a Marketplace launch checklist, positioning/categorisation guidance and clear boundaries for analytics and publishing.
- Give the Marketplace action a more specific name and concise discoverable description; retain the same inputs, outputs and API v1 contract.
- Keep the local CLI, offline diagnostics, SARIF output and release checks unchanged.

## 1.1.0 — 2026-10-19

- Extend AssetGuard to inspect literal CSS imports, fonts and image URLs in every non-private stylesheet, with stylesheet-relative resolution and deployment-prefix checks.
- Decode CSS escapes and distinguish comments, strings, fragments, embedded assets and remote references without executing code or making network requests.
- Report missing CSS resources at the stylesheet and source line. Surface malformed tokens or unsupported encodings as incomplete coverage rather than silently claiming a clean scan.
- Bound combined HTML/CSS references and preserve metadata-only handling of private files, snapshot schema 1, SDK API v1 and existing budget semantics.
- Add regression coverage for nested imports, escaped paths, conditional resources, encodings, privacy and reference limits.

## 1.0.0 — 2026-10-19

- Establish documented 1.x contracts for SDK API v1, configuration/report schemas, CLI gates and the local MCP/Action interfaces, with an explicit 0.x migration guide.
- Add a reusable cross-platform GitHub composite Action: isolated installation, optional reviewed plugin requirements, host-version constraints, project/workspace checks, JSON/SARIF outputs, escaped annotations and a bounded job summary. Preserve artifacts and status propagation on failed gates.
- Add metadata-only configuration preflight and packaged project/workspace editor schemas; accept optional `$schema` hints without network fetching or plugin imports.
- Bound project aggregate reports like workspace reports, cancel on exhaustion and prevent allowed failures from hiding resource errors.
- Read baselines once into an immutable snapshot; enforce byte/key bounds and bounded growing-file JSON reads, reject nonfinite JSON and catch dangling output symlinks before execution.
- Keep SDK API v1 unchanged, freeze a pre-cache plugin compatibility fixture and update new scaffold metadata for the stable host range `>=1,<2`.
- Test the real Action on Linux/Windows/macOS, including intentionally failed checks and output artifacts. Include Action/schema assets in source/wheel packages and add production CI/compatibility documentation.

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
