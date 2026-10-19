# GitHub Action

[Back to DevPocket](../README.md) · [Configuration preflight](configuration.md) · [v1 compatibility](compatibility.md)

Use the repository's composite Action to run project or workspace checks in an isolated Python environment. It produces complete JSON and SARIF files, up to 50 new-finding annotations and a job summary. The gate propagates to the workflow even when reports are produced on failure. It needs no GitHub token or write permission.

```yaml
name: Developer diagnostics
on: [push, pull_request]
permissions:
  contents: read
jobs:
  checks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: HamWebDevs/DevPocket@v1
        id: diagnostics
        with:
          root: .
          jobs: '4'
          fail-on: warning
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: developer-diagnostics
          path: ${{ steps.diagnostics.outputs.directory }}
```

Commit a `.devpocket.json` first; `devpocket init` creates a starter config. The Action refuses missing or empty configuration. Its default mode is `project`; set `mode: workspace` for `.devpocket-workspace.json`. Build your application in a preceding workflow step if checks need finished build files. DevPocket does not build or capture applications automatically.

`@v1` tracks verified releases in major version 1. Use `@v1.0.0` or a reviewed full commit SHA to fix the action source exactly. Python/build-tool downloads during installation still use the configured package registry; pin plugin dependencies for reproducible installs. The diagnostic package itself has no runtime dependencies.

## Inputs

| Input | Default | Meaning |
| --- | --- | --- |
| `root` | `.` | Existing project/workspace directory beneath the checkout. |
| `mode` | `project` | `project` or `workspace`. |
| `config` | mode-specific default | Config/manifest file relative to `root`. |
| `baseline` | empty | Accepted-findings baseline relative to `root`. |
| `jobs` | `4` | Global worker limit, integer 1–8. |
| `fail-on` | `warning` | `error`, `warning` or `none`; execution failures still fail. |
| `allow-exec` | `false` | Explicit permission for command-running checks. |
| `plugin-requirements` | empty | Requirements file relative to the checkout; explicitly installs those packages. |
| `python-version` | `3.12` | Interpreter selected by `actions/setup-python`. |

Inputs travel through environment variables and argument arrays, never interpolated shell source. Paths must be contained, canonical POSIX paths without symlink components. The target can use spaces or literal shell punctuation in filenames without executing it. All file inputs are checked before installation. Plugin requirements resolve local paths from the checkout; a constraint prevents them from replacing the Action's selected DevPocket version.

The Action creates separate environments and report directories beneath `RUNNER_TEMP`. Package installation may use the network and run package build code. Enabled plugins are trusted Python code; the read-only flag is a declaration, not a sandbox. `allow-exec: false` does not sandbox installed packages or plugin imports. Review dependencies and project configuration as you would any code in a workflow. Check execution has a two-hour outer limit, with each check retaining its configured timeout.

## Outputs and gates

| Output | Meaning |
| --- | --- |
| `report` | Absolute filename of the full JSON report. |
| `sarif` | Absolute filename of SARIF 2.1.0 output. |
| `directory` | Directory containing both files. |
| `exit-code` | Gate status, including when a completed diagnostic step fails. |

Ordinary gate/config-preflight failures produce artifacts before returning status 1 or 2. Installation failures, invalid Action inputs and interruptions can stop before artifacts exist. Use `if: always()` for artifact upload. The Action does not post PR comments, upload to Code Scanning or require `security-events: write`; integrate the SARIF file with your chosen uploader separately.

Accepted baseline findings are retained in artifacts and omitted from new-finding annotations. The annotation/summary limits do not truncate the JSON/SARIF evidence. Workspace locations include the selected root prefix; combined reports retain selection scope. Configuration preflight never imports plugins; their input validation occurs in the isolated execution workers.

The repository tests the actual composite Action on Linux, Windows and macOS, including a passing project, an intentionally failing gate, workspace execution and artifact/output propagation.
