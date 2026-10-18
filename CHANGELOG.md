# Changelog

User-visible changes are recorded here. Repository versions are not PyPI releases.

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
