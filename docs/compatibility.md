# Version 1 compatibility and migration

[Back to DevPocket](../README.md)

DevPocket 1.0.0 establishes the following supported contracts for the 1.x series. Stability refers to these interfaces and meanings; it is not a claim that every plugin or environment has been tested.

| Surface | v1 contract |
| --- | --- |
| Python | Python 3.10+; Linux, Windows and macOS CI. Raising the minimum requires a major release. |
| Runtime installation | Standard library only; no telemetry, mandatory service or runtime dependency. |
| Plugin API | `devpocket.sdk` API v1: `ToolSpec`, `ToolContext`, `ToolResult`, `Finding`, input validation and API version. |
| Discovery | `devpocket.tools` entry points; disabled plugins are not imported and built-ins cannot be shadowed. |
| Configurations | Project/workspace `version: 1`; new optional fields can be added, existing meanings remain. |
| Reports | Structured envelope `schema: 1`, stable finding fingerprints and SARIF 2.1.0. Additive JSON fields are allowed; consumers should ignore unknown fields. |
| Execution | Explicit command opt-in, bounded workers and failure/dependency gates. Read-only plugins remain trusted code. |
| MCP | Local stdio, initialization and read-only defaults; explicit plugin exposure. Client protocol compatibility is documented in the MCP guide. |
| GitHub Action | `action.yml` documented inputs/outputs and gate propagation; `v1` tracks verified releases. |

Text/Markdown presentation, internal Python modules, cache bytes and plan digests are not stable APIs. Import the SDK rather than CLI internals. Runtime/source changes invalidate caches; a plan digest includes the host version, so regenerate a reviewed plan after upgrading. Cache reuse is optional and can safely bypass on resource, filesystem or contention errors.

Structured `run`, project/workspace checks and preflight use 0 for passing gates, 1 for findings/failed checks and 2 for input/execution/resource errors; interruption is 130. The direct runner's JSON `exit_code` describes the tool's operational result; the CLI also applies severity/baseline gates, so a warning can return CLI status 1 while the tool envelope's operational code is 0. Combined checks and Action output report the combined gate. Original command-wrapping utilities preserve their documented wrapped-command statuses.

`ToolResult.exit_code != 0` is an operational failure and cannot be suppressed by a findings baseline or `--fail-on none`. A project can explicitly configure `allow_failure`; that is a separate, visible policy decision. Baseline absence refers to the selected report, not proof that debt in unselected projects has disappeared.

## Upgrade from 0.x

Version 1.1 extends AssetGuard to literal CSS imports and URLs, including fonts and background images. Existing snapshot/config schemas and SDK API v1 remain unchanged. New CSS coverage counters are additive; missing CSS resources can now produce findings in a build that previously checked only HTML references. Review those findings before updating a baseline.

1. Install the v1 wheel/source in the same environment as reviewed plugins. Nothing is published to PyPI by this repository.
2. Run `devpocket config validate`; fix invalid built-in parameters, missing/disabled/conflicting plugins and resource-limit violations.
3. Run the configured checks without cache and review reports, then re-enable declared caching.
4. Regenerate reviewed workspace plan hashes after upgrading.

Existing project/workspace configurations and baseline fingerprints remain usable within the documented bounds. The new `$schema` hint is optional and requires a host that supports it; omit it when sharing a config with a pre-1.0 host. Large pre-1.0 configs/baselines may need splitting to meet the documented v1 bounds.

API v1 plugins written before the optional cache extension remain source-compatible. A frozen pre-cache plugin is built and installed in extension CI to verify that contract. Package metadata can still block installation: if an existing plugin declares a bound such as `<0.7`, its maintainer must review/test against v1 and widen the dependency range. The current scaffold uses `devpocket-toolkit>=1,<2`. A plugin deliberately supporting older API v1 hosts can declare a wider tested range and omit optional unsupported fields.

Deprecations will be documented before removal in a new major release. Fixes may tighten rejection of malformed/unsafe input or correct diagnostics; reviewed baselines and budgets remain user policy, not permanent guarantees about future findings. See [releases](releases.md), [security](../SECURITY.md) and [contributing](../CONTRIBUTING.md).
