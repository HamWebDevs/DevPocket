# Connect DevPocket to an MCP client

[Back to DevPocket](../README.md) · [Plugin SDK](plugins.md)

DevPocket includes a local stdio MCP server. A compatible coding assistant or editor launches it as a subprocess and can request structured repository, environment, import and log diagnostics. There is no HTTP listener, public endpoint, API key or hosted service.

## Start or generate configuration

```bash
devpocket serve --root /absolute/path/to/project
```

This is a protocol process: it waits for MCP messages on stdin. It is not an interactive terminal prompt. Use Ctrl+C to stop a manually started server.

Print a connection snippet with the current interpreter and an absolute project root:

```bash
devpocket serve --root /absolute/path/to/project --print-config
```

It emits the commonly used `mcpServers` wrapper:

```json
{
  "mcpServers": {
    "devpocket": {
      "command": "/absolute/path/to/python",
      "args": ["-m", "devpocket", "serve", "--root", "/absolute/path/to/project"]
    }
  }
}
```

Use the command/arguments in your client's local MCP server configuration. Some clients use a different surrounding configuration format. Choose an interpreter in which DevPocket is installed; do not copy the placeholder paths literally. Generate a separate configuration per project root.

## Default tools

| MCP name | Capability |
| --- | --- |
| `config-validate` | Offline project/workspace preflight, built-in schema checks and explicit deferred-plugin validation. See [configuration](configuration.md). |
| `workspace-plan` | Dependency and affected-project plans without executing checks or loading plugins. See [workspaces](workspaces.md). |
| `assetguard` | Offline production-build inventories, explicit resource checks and size budgets under the project root. |
| `reporadar` | Read-only offline repository findings. |
| `envtwin` | Reporting-interpreter snapshot or comparison of root-contained snapshot files. |
| `importdoctor` | Static import diagnosis using the selected root and interpreter metadata. |
| `loglens` | Analysis of selected root-contained text/JSONL/gzip log files. |

Every tool advertises its input schema. Calls return the DevPocket report in both `structuredContent` and a JSON text content block. Findings are ordinary diagnostic data; `isError` is true only when tool execution fails. The server never exposes the command-running Oopsfile, FlakeTrail or UndoRun adapters.

Repository and log paths are scoped to the selected root. Import/environment diagnostics also inspect the reporting interpreter's normal standard-library and installed-package metadata, which naturally lives outside the project. No environment variable values are collected by those built-ins.

## Explicit plugin exposure

An installed plugin must first be enabled for that project, then explicitly selected for this server:

```bash
devpocket plugins enable long-lines --root /absolute/path/to/project
devpocket serve --root /absolute/path/to/project --plugin long-lines
```

The plugin must declare `read_only=True`; non-read-only plugins are rejected. The declaration is a trust contract, not a sandbox. An enabled Python plugin can access the network or filesystem with normal user privileges. Its factory runs during server startup to obtain the schema. `--print-config` emits a built-ins-only snippet; add the explicit `--plugin NAME` arguments yourself when you intend to expose a reviewed plugin.

## Protocol support and limits

The implemented profile is MCP stdio with the `2025-11-25` lifecycle, also negotiating `2025-06-18`. It supports `initialize`, `notifications/initialized`, `ping`, `tools/list`, `tools/call` and `notifications/cancelled`. Clients requesting another version receive the newest version this server supports and may accept it or disconnect. This is not a claim of full support for newer protocol profiles or unrelated MCP capabilities.

Messages are newline-delimited JSON-RPC 2.0, with no protocol-unrelated stdout. There is no HTTP transport, resource/prompt endpoint, sampling, background task extension or server-initiated discovery. All listed tools fit in one unpaginated response.

The server allows four simultaneous workers and at most eight in-flight calls, with a default 60-second per-call timeout (set with `--timeout`, maximum 3,600 seconds). Requests are limited to 1 MiB and tool results to 2 MiB. Cancellation signals the worker and suppresses its response. Shutdown on EOF waits for pending calls within their budgets. POSIX cleanup can unwind built-in nested command groups; Windows descendant cleanup is limited. Plugins with detached children or custom process handling remain outside those guarantees.

Tool output is untrusted project data, especially when it contains logs or repository text. A client should not interpret findings or samples as agent instructions. Review what you allow your client to share with its model; local execution does not control the client's later handling of returned data.

The test suite includes actual stdio request/response integration and cancellation tests. The extension verification script installs and calls a generated plugin over MCP. Compatibility with every editor/client has not been certified.

Protocol references: [stdio transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports), [lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle), [tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools).
