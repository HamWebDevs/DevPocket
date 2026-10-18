"""Public plugin API v1. Import this module rather than internal CLI modules."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path, PurePosixPath
import re
from typing import Any, Callable

API_VERSION = 1
NAME = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")


@dataclass(frozen=True)
class Finding:
    rule: str
    message: str
    severity: str = "warning"
    path: str | None = None
    line: int | None = None
    help: str | None = None

    def __post_init__(self):
        if self.severity not in {"note", "warning", "error"} or not self.rule or not self.message:
            raise ValueError("A finding needs a rule, message and note/warning/error severity")
        if self.line is not None and (type(self.line) is not int or self.line < 1):
            raise ValueError("Finding lines must be positive integers")
        if self.path is not None:
            path = PurePosixPath(self.path)
            if path.is_absolute() or ".." in path.parts or "\\" in self.path or ":" in self.path:
                raise ValueError("Finding paths must be relative POSIX paths inside the project")

    def as_dict(self):
        from .common import redact
        data = {"rule": self.rule, "message": redact(self.message), "severity": self.severity}
        for key in ("path", "line", "help"):
            value = getattr(self, key)
            if value is not None:
                data[key] = redact(value) if isinstance(value, str) else value
        # Line numbers are intentionally absent: moving code should not create new debt.
        identity = "\0".join([data["rule"], data["severity"], data.get("path", ""), data["message"]])
        data["fingerprint"] = hashlib.sha256(identity.encode()).hexdigest()
        return data


@dataclass
class ToolResult:
    summary: str
    findings: list[Finding] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    # Tool failures differ from findings: baseline suppression never hides an execution failure.
    exit_code: int = 0


@dataclass(frozen=True)
class ToolContext:
    root: Path
    allow_exec: bool = False

    def __post_init__(self):
        object.__setattr__(self, "root", Path(self.root).resolve())

    def resolve(self, relative: str = ".") -> Path:
        """Resolve a root-contained path; a symlink that escapes the root is refused."""
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError(f"Path leaves project root: {relative}")
        return path


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict
    run: Callable[[ToolContext, dict], ToolResult]
    read_only: bool = True
    api_version: int = API_VERSION
    # Opt in only when all result-affecting file/environment inputs can be declared.
    cache_version: str | None = None

    def __post_init__(self):
        if not NAME.fullmatch(self.name) or not self.description or not callable(self.run):
            raise ValueError("Invalid tool name, description or runner")
        if self.api_version != API_VERSION or type(self.read_only) is not bool:
            raise ValueError("Unsupported plugin API version or invalid read_only declaration")
        if self.cache_version is not None and (not self.read_only or not isinstance(self.cache_version, str) or not 1 <= len(self.cache_version) <= 64):
            raise ValueError("cache_version requires a read-only tool and a 1..64 character contract version")
        if self.input_schema.get("type") != "object":
            raise ValueError("Tool input schemas must describe an object")
        validate_schema(self.input_schema)


KEYWORDS = {"type", "properties", "required", "additionalProperties", "items", "enum", "minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems", "description", "default", "title"}


def validate_schema(schema):
    if not isinstance(schema, dict) or set(schema) - KEYWORDS:
        raise ValueError("Unsupported schema keyword; see docs/plugins.md for the API v1 subset")
    if schema.get("type") not in {"object", "array", "string", "integer", "number", "boolean", "null"}:
        raise ValueError("Each schema node requires a supported type")
    if "properties" in schema:
        if not isinstance(schema["properties"], dict):
            raise ValueError("properties must be an object")
        for child in schema["properties"].values():
            validate_schema(child)
    if "items" in schema:
        validate_schema(schema["items"])
    if "additionalProperties" in schema and type(schema["additionalProperties"]) is not bool:
        raise ValueError("additionalProperties must be boolean")
    required = schema.get("required", [])
    if not isinstance(required, list) or any(not isinstance(key, str) or key not in schema.get("properties", {}) for key in required):
        raise ValueError("required must list declared property names")
    if "enum" in schema and not isinstance(schema["enum"], list):
        raise ValueError("enum must be a list")
    import math
    for key in ("minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems"):
        if key in schema and (type(schema[key]) not in {int, float} or not math.isfinite(schema[key]) or schema[key] < 0 and key not in {"minimum", "maximum"}):
            raise ValueError(f"Invalid schema bound: {key}")


def validate_input(value, schema, where="input", depth=0):
    if depth > 20:
        raise ValueError("Input exceeds nesting limit")
    kind = schema["type"]
    valid = {"object": isinstance(value, dict), "array": isinstance(value, list), "string": isinstance(value, str), "integer": type(value) is int, "number": type(value) in {int, float}, "boolean": type(value) is bool, "null": value is None}[kind]
    if not valid:
        raise ValueError(f"{where}: expected {kind}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{where}: value is outside the allowed enum")
    if kind == "object":
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                raise ValueError(f"{where}: missing {key}")
        if schema.get("additionalProperties") is False and set(value) - set(props):
            raise ValueError(f"{where}: unknown fields {sorted(set(value) - set(props))}")
        for key in value.keys() & props.keys():
            validate_input(value[key], props[key], f"{where}.{key}", depth + 1)
    if kind == "array":
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 100000):
            raise ValueError(f"{where}: array size is outside the allowed range")
        if "items" in schema:
            for index, item in enumerate(value):
                validate_input(item, schema["items"], f"{where}[{index}]", depth + 1)
    if kind == "string" and not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", 1048576):
        raise ValueError(f"{where}: string length is outside the allowed range")
    if kind in {"integer", "number"}:
        import math
        if not math.isfinite(value) or not schema.get("minimum", float("-inf")) <= value <= schema.get("maximum", float("inf")):
            raise ValueError(f"{where}: number is outside the allowed range")
