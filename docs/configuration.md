# Configuration contracts and preflight

[Back to DevPocket](../README.md) · [Project checks](project-checks.md) · [Workspaces](workspaces.md)

Validate a configuration before running it:

```bash
devpocket config validate --root . --format json
devpocket config validate --root examples/workspace --workspace --format sarif
config-validate --root .
```

Preflight checks shape, dependencies, roots, configured tool availability and built-in parameter schemas. Enabled plugins must have one installed, nonconflicting entry point. Their factories are not imported: plugin parameter checks are explicitly marked deferred and occur in execution workers. A valid preflight is not proof that files referenced by tools exist or that checks will pass. No target commands or checks run, and no schema URLs are fetched.

`--config` is relative to `--root` and must remain contained without symlink components. Default filenames are `.devpocket.json` and `.devpocket-workspace.json`. Empty/missing project configuration cannot certify any checks. Preflight returns 0 for structurally valid checks (including explicit deferred-plugin notes), 1 for configuration findings and 2 for malformed/unsafe/unreadable inputs. Reports support text, JSON, Markdown and SARIF; output files are never overwritten.

The read-only `config-validate` SDK/MCP tool accepts `config` and `workspace` parameters. It has no result-cache contract, so every call reads current configuration metadata.

## Editor schemas

Both schemas ship in the wheel and source package:

```bash
devpocket config schema --kind project --output project-schema.json
devpocket config schema --kind workspace --output workspace-schema.json
```

`devpocket init` adds a `$schema` editor hint. You can add the same field to an existing config:

```json
{
  "$schema": "https://raw.githubusercontent.com/HamWebDevs/DevPocket/v1/devpocket/schemas/project-v1.json",
  "version": 1,
  "checks": {
    "imports": {"tool": "importdoctor", "input": {"module": "json"}}
  }
}
```

For workspaces, use `workspace-v1.json` at the same location. Editors may fetch schema URLs according to their settings; DevPocket never fetches them. An offline editor can point at an exported local schema instead. Editor schemas describe JSON structure; runtime validation additionally checks dependency references/cycles, canonical paths, resources and installed tool inputs. They do not replace preflight.

## Resource boundaries

Project configs are bounded to 256 KiB; each project has at most 100 checks. Workspaces retain their 32-project/256-check total limits. Both project and workspace aggregate reports are bounded to 8 MiB of compact JSON, cancel remaining work on exhaustion and return an execution error even if a check was allowed to fail.

Baselines are read and validated once before a run, then shared immutably across current gates. Changes to the baseline file during a run take effect on the next invocation. Baselines are limited to 8 MiB, 50,000 keys and 256 characters per key. Ordinary JSON imports retain the 32 MiB default byte limit; bounded reads enforce it even if an input grows. Nonfinite JSON numbers are rejected. Single-worker results, subprocess streams, caches and MCP messages retain their own tighter limits.
