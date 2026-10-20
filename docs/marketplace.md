# DevPocket GitHub Marketplace launch guide

[DevPocket](../README.md) · [GitHub Action reference](github-action.md) · [Example workflow](../examples/github-actions/devpocket.yml)

**Product:** DevPocket CI Diagnostics — project and workspace checks with JSON, SARIF, annotations and job summaries. Free, open source, zero runtime package dependencies and no hosted account.

## What users get

- A GitHub Action that checks a committed project or workspace configuration and propagates configured failure gates to CI.
- Structured JSON and SARIF reports, up to 50 new-finding annotations, and a short GitHub Actions job summary.
- Optional, explicitly installed plugins; workspace plans and build asset checks are available through the toolkit.
- Local execution without sending findings to DevPocket or requiring a service/API key. Installing Python/build tooling or approved plugins may contact package servers.

**Who it is for:** Python developers, repository maintainers, monorepo maintainers and teams that need reviewable local checks in CI. It is not a hosted vulnerability scanner, dependency update bot or automatic fix service.

## Marketplace publishing checklist

This repository has one root `action.yml` with `name`, `description`, `branding`, input/output metadata and a working composite runner. The repository is public and the real Action is exercised in Linux, Windows and macOS CI.

Publishing the Marketplace listing requires an account owner to:

1. Confirm the **DevPocket CI Diagnostics** action name is available/unique in the Marketplace release form.
2. Open [the GitHub Action metadata](../action.yml) in the browser and choose **Draft a release** (or open the new release form).
3. Accept the **GitHub Marketplace Developer Agreement** if GitHub requests it and ensure two-factor authentication is enabled.
4. Choose **Publish this Action to the GitHub Marketplace** when releasing the next successfully tested version. Suggested primary category: **Continuous integration**; choose only categories offered by GitHub and appropriate to the Action.
5. Check that the released tag points to the passing commit and that `v1` resolves to the latest verified compatible major release.
6. After publication, try the [copyable example workflow](../examples/github-actions/devpocket.yml) in a separate test repository and inspect actual annotations/SARIF artifacts.

**Important:** An automated `gh release create` without choosing the Marketplace publication option is a GitHub Release, not proof of a Marketplace listing. No listing, installs or usage metrics should be claimed before verification.

## Suggested repository About fields

The repository owner can set these in **About → gear icon** on GitHub (these settings are not populated by this document).

**Description:** `Local-first developer checks for GitHub Actions: workspace diagnostics, build asset audits, JSON/SARIF and plugins.`

**Topics:** `github-action`, `github-actions`, `developer-tools`, `continuous-integration`, `sarif`, `python`, `monorepo`, `static-analysis`, `build-tools`, `cli`.

Topics should describe what the project actually does; avoid unrelated trend keywords or claims of certified security scanning.

## Privacy, trust and usage statistics

The Action needs `contents: read` to check out the user's repository. It does not require DevPocket credentials, write access or a tracking service. Reports live in the caller's GitHub Actions environment; the caller controls retention and visibility. Do not introduce outbound telemetry to measure popularity.

Public GitHub metrics (stars, forks, release asset downloads and issue activity) are imperfect proxies for real adoption. Actual Action usage in other people's repositories is not reliably inferable from release ZIP download counts; private-repository use is not visible. View/clone traffic is accessible to maintainers through **Insights → Traffic**, and GitHub limits that window. For Marketplace performance, use any officially available creator analytics when eligible, and avoid equating impressions with installations.

## Suggested listing copy

**Short description:** Local-first CI diagnostics for projects and workspaces. Catch build asset and configuration mistakes and export actionable JSON/SARIF reports.

**Overview:** Add one GitHub Actions step to run reviewable project checks with failure gates, inline annotations and portable reports. Use the same commands locally or integrate optional Python plugins. No DevPocket account or hosted service required. Run only checks and plugins you explicitly trust; the Action is not a sandbox.
