# Security considerations

DevPocket is an early developer utility, not a security boundary.

- Wrapped commands retain normal process permissions. Never use UndoRun to make malicious code safe.
- Reports and backups are local but may contain confidential code, package names, filenames or output. Redaction is heuristic. Review before sharing.
- UndoRun's journal must remain private and trusted. It verifies backup hashes and restore paths but does not defend against hostile processes concurrently rewriting the journal or filesystem. It has no transaction-wide rollback if applying a restore fails midway.
- Source snippets are opt-in. Environment snapshots omit environment values and host identifiers. Oopsfile's Git option includes only unstaged diff statistics.
- General source scanning skips symlinks and common secret-like filenames. AssetGuard instead refuses symlinks and reports private filenames in deployment output without reading their contents. Neither is a content-based secrets audit. Database files and excluded paths cannot be restored.
- A child process can start background writers. Stop them before restoration. Windows timeout handling kills only the immediate child.

For a vulnerability, avoid posting credentials, exploit-bearing private data or confidential reports in a public issue. Use GitHub's private vulnerability reporting if enabled on the repository; otherwise open a minimal issue requesting a private reporting channel without exploit details.

LogLens reads untrusted log text without executing it, removes common terminal controls and applies best-effort redaction. Its grouping intentionally loses some detail; preserve original logs separately. ImportDoctor does not import inspected target modules, but interpreter startup hooks and custom path hooks remain outside its control. Resolution findings are hints, not a safety audit or runtime guarantee.

## Extension platform

Installed plugins are arbitrary Python code. Metadata-only discovery does not import them; enabling a plugin explicitly trusts its installed entry point for the project. Describing a plugin or starting MCP with an explicit plugin loads its factory. CLI/check calls run in isolated processes, not a privilege sandbox. A read_only declaration is a contract, not enforced access control. The host never installs plugins automatically.

Structured command-running tools require --allow-exec. The MCP server never exposes those adapters, binds no listening socket and requires explicit selection of any enabled plugin. Default read-only tools still return local project and interpreter information to the connected client; that client controls subsequent model/network use.

Requests, results, group counts and capture buffers are bounded. JSON/SARIF reports and plugin diagnostics use best-effort redaction. Baselines suppress finding gates, never tool execution failures. Review enabled plugins, reports and baseline changes before sharing or relying on them.
