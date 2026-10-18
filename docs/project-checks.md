# Project checks, reports and baselines

[Back to DevPocket](../README.md) · [Plugin SDK](plugins.md) · [MCP](mcp.md)

## Configure once, run locally and in CI

```bash
devpocket init
devpocket check --jobs 4
```

`init` creates `.devpocket.json` with one repository check and refuses to overwrite an existing file. Configuration is JSON, so Python 3.10 needs no TOML dependency. Only the selected root's config is loaded; the host does not walk parent directories or import repository configuration code. `--config PATH` selects an explicit alternative; a missing explicit config is an error.

```json
{
  "version": 1,
  "plugins": ["long-lines"],
  "checks": {
    "repository": {"tool": "reporadar", "input": {}},
    "imports": {
      "tool": "importdoctor",
      "input": {"module": "json"},
      "timeout": 20
    },
    "style": {
      "tool": "long-lines",
      "input": {"path": "README.md", "max_length": 120},
      "needs": ["repository"],
      "allow_failure": false
    }
  }
}
```

This example assumes you installed and reviewed the `long-lines` plugin. Listing it in `plugins` is an explicit trust decision, equivalent to `plugins enable long-lines`.

Independent checks run concurrently in separate worker processes. `needs` is a list of check IDs, not tool names; a dependent starts after every dependency passes or has an explicitly allowed failure. Failed dependencies cause skips. Cycles and unknown dependencies are rejected before running. Report order follows configuration order, even if checks finish in another order.

Limits: 100 configured checks; 1–8 parallel workers; default 4 workers and 60 seconds per check. Per-check `timeout` is greater than zero and at most 3,600 seconds. Worker results and inputs have the SDK limits described in [plugins.md](plugins.md). Interrupting a pipeline signals its active workers to stop; process cleanup limits still apply.

## Structured runs for all seven tools

```bash
devpocket run reporadar --format json
devpocket run importdoctor --input '{"module":"json"}'
devpocket run loglens --input '{"paths":["examples/events.log"]}' --format sarif
devpocket tools describe flaketrail
```

`tools describe NAME` prints the exact input schema, so clients do not need to infer flags from text help. Inputs can come from JSON files using `--input @input.json`. Tool input paths resolve beneath `--root`. CLI control paths such as `--output`, `--baseline`, `--config` and `@input.json` resolve from your terminal's current directory.

The original seven standalone commands keep their existing flags and exit conventions. Structured adapters provide a common report contract. RepoRadar findings are warnings, LogLens warning/error events become findings, ImportDoctor's likely problems are errors and informational diagnoses are notes. EnvTwin uses `{"action":"snapshot"}` by default, or `{"action":"diff","left":"a.json","right":"b.json"}`.

Oopsfile, FlakeTrail and UndoRun can execute commands or write files, so the structured runner requires an explicit `--allow-exec`. Wrapped commands remain argv arrays, never implicit shell strings:

```bash
devpocket run oopsfile --allow-exec --input '{"command":["python","app.py"],"output":".devpocket/app-error.md"}'
```

The structured UndoRun adapter records a run; restoration remains the original explicit `undorun restore` command. For a structured command-running tool, outer `--timeout` is the entire worker budget, while an input `timeout` is the nested command budget. Set the outer budget appropriately when repeating commands.

## Reports and severity gates

```bash
devpocket check --format json --output checks.json
devpocket check --format markdown --output checks.md
devpocket check --format sarif --output checks.sarif
```

Reports never overwrite an existing output file. An existing output is rejected before checks run. Progress goes to stderr; stdout stays clean for machine-readable output. Supported formats are text, JSON schema 1, Markdown and SARIF 2.1.0. SARIF includes stable rule IDs, relative file locations, fingerprints, invocation status and baseline state. Export does not upload to any external system.

`--fail-on warning` is the default and fails on new warnings or errors. `--fail-on error` fails on new errors only. `--fail-on none` disables finding-based gating. Tool execution failures still fail under every mode. `allow_failure` accepts a configured step's failure and lets its dependents proceed; its evidence remains in the report.

Structured run exit codes are 0 for a passing gate, 1 for findings or command failure, 2 for tool/config/worker errors, and 130 for interruption. Check exit codes are 0 when all steps pass or are explicitly allowed to fail, 1 for failed/skipped checks, and 2 for an unallowed tool error. These conventions do not change the original standalone tools.

## Introduce checks without blocking on existing debt

Capture a JSON report, then create a baseline from it:

```bash
devpocket check --format json --output first-run.json
devpocket baseline --from first-run.json --output .devpocket-baseline.json
devpocket check --baseline .devpocket-baseline.json
```

The first command may exit 1 while still writing a complete report. Baselines store fingerprints, not raw log samples. Existing findings remain visible but do not fail a finding-based gate. New findings still fail according to severity. Execution failures cannot be suppressed by a finding baseline. Tool name is part of baseline identity; check name is not, so the same finding from the same tool in two checks shares baseline identity.

Reports count existing/new/absent fingerprints. "Absent" means not observed in the current invocation; it is not proof a problem is fixed if you changed the selected checks or inputs. Baseline creation refuses to overwrite a file; review a new baseline before replacing an old one.

## JSON envelope

Each tool report includes `schema`, host `version`, `tool`, execution `status`, `summary`, raw tool `exit_code`, `seconds`, `findings` and `data`. Pipeline reports additionally include ordered `checks`, and findings carry their originating tool/check. `status="completed"` means execution succeeded; it can still contain errors that fail the severity gate. JSON is intended for integrations; text output is for people.
