# Workspace checks

[Back to DevPocket](../README.md)

DevPocket 0.6 coordinates existing project checks across a monorepo or several project folders. Projects retain their own roots, enabled plugins, checks, timeouts and cache declarations. One global pool runs at most 1–8 isolated check workers; cross-project dependencies share the same pool.

## Try the complete example

From this checkout:

```bash
devpocket workspace plan --root examples/workspace --format json
devpocket workspace check --root examples/workspace --jobs 2
devpocket workspace check --root examples/workspace --changed-file apps/web/index.html --format sarif
```

The example has a shared library, web app and independent API. All checks inspect standard-library imports without executing target code. `workspace-plan` is also an installed alias for `devpocket workspace plan`.

## Define the projects

Create `.devpocket-workspace.json` at the workspace root:

```json
{
  "version": 1,
  "shared_inputs": ["tooling"],
  "projects": {
    "library": {"path": "packages/lib"},
    "web": {"path": "apps/web", "needs": ["library"], "watch": ["schemas"]},
    "api": {"path": "apps/api", "config": "checks.json"}
  }
}
```

Each project must exist and have a valid, nonempty [project configuration](project-checks.md). `config` defaults to `.devpocket.json` relative to that project's root. `path`, `watch` and `shared_inputs` use canonical workspace-relative POSIX paths; watch/shared entries match a file or directory prefix. They are selection signals, not files read automatically. Nested project roots are permitted; a changed path selects every containing root. Roots must be distinct, and symlink components are refused.

All checks in a project's `needs` projects must pass before its own checks can start. Within-project `needs` edges still apply. An explicitly allowed failure unblocks dependents; other failed or skipped prerequisites block them. A project name/check name pair, such as `web/assets`, identifies a check in combined reports.

## Select work conservatively

```bash
devpocket workspace check --project web
devpocket workspace plan --changed-file packages/lib/api.py --changed-file apps/api/deleted.py
devpocket workspace check --changed-files changed.json
```

Explicit `--project` selection includes prerequisites. Changed-file selection includes owners, projects watching the path, affected downstream projects, and all prerequisites of those selected projects. Configuration, shared-input and unmapped changes select the entire workspace. Supply deleted paths too. DevPocket does not derive changes from Git or infer imports.

`--changed-files` reads a root-contained JSON array of paths. An empty array explicitly selects no checks. Do not combine it with `--changed-file`; do not combine changed-file selection with `--project`. Treat the provided change list as an input requiring review. An incomplete list cannot establish that omitted projects are unaffected.

Plans show selection reasons (up to eight changed paths per project), qualified dependency edges, execution levels and a SHA-256 digest of configuration/selection. Tool inputs and environment values are omitted from the public plan.

```bash
devpocket workspace plan --format json --output reviewed-plan.json
devpocket workspace check --expect-plan PLAN_SHA256_FROM_THE_REPORT
```

The expected digest detects configuration or selection changes before any workers start. It is **not** a source snapshot, a plugin attestation or a guarantee against concurrent filesystem edits. Repeat exactly the same selection options when executing a reviewed plan.

## Reports, gates and caching

```bash
devpocket workspace check --format json --output workspace.json
devpocket baseline --from workspace.json --output accepted.json
devpocket workspace check --baseline accepted.json --format sarif --output workspace.sarif
devpocket workspace check --no-cache --fail-on error
```

Findings use workspace-relative paths and project-scoped fingerprints. A finding accepted for one project does not suppress an identical finding in another. Workspace baselines differ from single-project baselines. Cached worker reports remain project-local and unmodified; relocation, baseline and severity gating happen after decoding. Cache declarations must still include every result-affecting input. `--allow-exec` remains necessary for command-running tools.

Text/JSON/Markdown reports include selected scope and qualified check states. SARIF adds selected/unselected project names, scope and the plan digest to invocation properties. Its finding properties identify project/check. Successful execution of a selected scope certifies only that scope. Exit 0 means selected checks passed or were explicitly allowed to fail; 1 means a gate/dependency failed; 2 means a configuration, execution or resource error; interruption is 130.

## Assistant planning and bounds

The read-only `workspace-plan` SDK/MCP tool accepts `manifest`, `projects` or `changed_files` under the server root. It never runs checks, loads enabled plugin code or caches a plan. Workspace execution is a separate CLI operation.

Limits: 32 projects, 256 configured checks in total, 256 KiB per JSON input, 4,096 changed paths, 1 MiB public plans and 8 MiB aggregate execution reports. Worker, timeout, subprocess cleanup and cache bounds still apply. Resource exhaustion cancels active work and returns an explicit error. No dependencies are installed and no target code is run by planning.
