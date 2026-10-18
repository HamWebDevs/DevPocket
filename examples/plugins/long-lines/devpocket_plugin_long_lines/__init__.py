"""Example DevPocket API v1 plugin: find long lines in a selected text file."""
from devpocket.sdk import Finding, ToolResult, ToolSpec


def inspect(context, params):
    path = context.resolve(params["path"])
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("Example plugin accepts files up to 1 MiB")
    maximum = params.get("max_length", 100)
    findings = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if len(line) > maximum:
            findings.append(Finding("long-line", f"Line has {len(line)} characters (limit {maximum})", path=path.relative_to(context.root).as_posix(), line=number))
    return ToolResult(f"{len(findings)} long lines", findings)


def build_tool():
    return ToolSpec(
        name="long-lines",
        description="Example plugin: find long lines in a selected text file",
        input_schema={"type": "object", "properties": {"path": {"type": "string", "maxLength": 4096}, "max_length": {"type": "integer", "minimum": 1, "maximum": 100000}}, "required": ["path"], "additionalProperties": False},
        run=inspect,
        cache_version="long-lines-v1",
    )
