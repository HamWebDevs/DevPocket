"""Bounded, offline production-artifact inspection and content-aware snapshots."""
from __future__ import annotations

from collections import defaultdict
import gzip
import hashlib
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
from urllib.parse import unquote, urljoin, urlsplit
import zlib

from .common import load_json, redact, sensitive, write_json
from .assetrefs import css_resources

MAX_FILES = 3000
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_REFERENCES = 20000
ORIGIN = "https://assetguard.invalid"
GROUPS = {"script": {".js", ".mjs", ".cjs"}, "style": {".css"}, "html": {".html", ".htm"}, "image": {".avif", ".gif", ".ico", ".jpeg", ".jpg", ".png", ".svg", ".webp"}, "font": {".eot", ".otf", ".ttf", ".woff", ".woff2"}, "source-map": {".map"}}


def kind(path):
    suffix = PurePosixPath(path).suffix.lower()
    return next((name for name, suffixes in GROUPS.items() if suffix in suffixes), "other")


def private_asset(path):
    return sensitive(path) or path.name in {".git", ".hg", ".svn"}


def safe_path(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 1024:
        raise ValueError("Asset paths must contain 1..1024 characters")
    parts = PurePosixPath(value)
    if parts.is_absolute() or ".." in parts.parts or any(c in value for c in "\\:") or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Asset paths must be relative, printable POSIX paths")
    return value


def mount_path(value):
    if not isinstance(value, str) or not value.startswith("/") or len(value) > 1024:
        raise ValueError("public_path must be an absolute URL path such as / or /docs/")
    parsed = urlsplit(value)
    decoded = unquote(parsed.path)
    if parsed.netloc or parsed.query or parsed.fragment or any(c in decoded for c in "\\:%?#") or any(ord(c) < 32 or ord(c) == 127 for c in decoded) or ".." in decoded.split("/"):
        raise ValueError("public_path cannot contain an origin, query, fragment or traversal")
    parts = [part for part in decoded.split("/") if part not in {"", "."}]
    return "/" + "/".join(parts) + "/" if parts else "/"


class Resources(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.base = None
        self.references = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "base" and self.base is None and attrs.get("href") is not None:
            self.base = attrs["href"]
        fields = {"script": ("src",), "img": ("src",), "source": ("src",), "video": ("src", "poster"), "audio": ("src",), "input": ("src",)}.get(tag, ())
        if tag == "link" and set((attrs.get("rel") or "").lower().split()) & {"stylesheet", "preload", "modulepreload", "icon", "manifest"}:
            fields = ("href",)
        for field in fields:
            if attrs.get(field):
                if len(self.references) == MAX_REFERENCES:
                    raise ValueError("HTML resource references exceed the inspection limit")
                self.references.append((attrs[field], self.getpos()[0]))


def validate_snapshot(data):
    if not isinstance(data, dict) or type(data.get("schema")) is not int or data["schema"] != 1 or data.get("kind") != "assetguard-snapshot" or data.get("compression") != "gzip-9":
        raise ValueError("Expected an AssetGuard schema 1 gzip-9 snapshot")
    if not isinstance(data.get("compressor"), str) or not re.fullmatch(r"[0-9][A-Za-z0-9._-]{0,63}", data["compressor"]):
        raise ValueError("Snapshot needs a valid zlib runtime version")
    if not isinstance(data.get("files"), list) or not 1 <= len(data["files"]) <= MAX_FILES:
        raise ValueError("Snapshot file inventory is empty or exceeds the file limit")
    seen = set()
    total = 0
    for item in data["files"]:
        if not isinstance(item, dict) or set(item) != {"path", "raw_bytes", "gzip_bytes", "sha256"}:
            raise ValueError("Invalid snapshot asset")
        path = safe_path(item["path"])
        if path in seen or PurePosixPath(path).as_posix() != path or path == ".":
            raise ValueError("Snapshot contains duplicate or non-canonical paths")
        seen.add(path)
        if type(item["raw_bytes"]) is not int or not 0 <= item["raw_bytes"] <= MAX_FILE_BYTES:
            raise ValueError("Invalid snapshot raw byte count")
        total += item["raw_bytes"]
        if item["gzip_bytes"] is None and item["sha256"] is None:
            if not private_asset(Path(path)):
                raise ValueError("Only sensitive assets may lack snapshot content measurements")
        elif type(item["gzip_bytes"]) is not int or not 0 <= item["gzip_bytes"] <= MAX_FILE_BYTES + 65536 or not isinstance(item["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", item["sha256"]):
            raise ValueError("Invalid snapshot compressed byte count or digest")
    if total > MAX_TOTAL_BYTES:
        raise ValueError("Snapshot exceeds the total byte limit")
    mount_path(data.get("public_path", "/"))
    if type(data.get("private_directories", 0)) is not int or not 0 <= data.get("private_directories", 0) <= MAX_FILES:
        raise ValueError("Invalid snapshot private-directory count")
    return data


def totals(files):
    groups = {}
    for name in sorted({kind(f["path"]) for f in files}):
        rows = [f for f in files if kind(f["path"]) == name]
        groups[name] = {"files": len(rows), "raw_bytes": sum(f["raw_bytes"] for f in rows), "gzip_bytes": sum(f["gzip_bytes"] or 0 for f in rows)}
    return {"files": len(files), "raw_bytes": sum(f["raw_bytes"] for f in files), "gzip_bytes": sum(f["gzip_bytes"] or 0 for f in files), "measured_files": sum(f["gzip_bytes"] is not None for f in files), "by_kind": groups}


def compare(current, previous):
    validate_snapshot(previous)
    if current["public_path"] != mount_path(previous.get("public_path", "/")):
        raise ValueError("Baseline and current build must use the same public_path")
    reason = "Compression runtimes differ; regenerate the baseline with the same zlib version" if current["compressor"] != previous["compressor"] else "A build contains unmeasured private entries" if any(data.get("private_directories", 0) or any(f["gzip_bytes"] is None for f in data["files"]) for data in (current, previous)) else None
    if reason:
        return {"comparable": False, "reason": reason, "gzip_delta_bytes": None, "raw_delta_bytes": None, "added": [], "removed": [], "changed": [], "renamed_identical": [], "new_unique_content_gzip_bytes": None, "by_kind": {}}
    old = {f["path"]: f for f in previous["files"]}
    new = {f["path"]: f for f in current["files"]}
    old_hashes = {f["sha256"] for f in old.values() if f["sha256"]}
    renamed = []
    by_hash = defaultdict(list)
    for path in sorted(old.keys() - new.keys()):
        if old[path]["sha256"]:
            by_hash[old[path]["sha256"]].append(path)
    for path in sorted(new.keys() - old.keys()):
        candidates = by_hash.get(new[path]["sha256"], [])
        if candidates:
            renamed.append({"before": candidates.pop(0), "after": path})
    fresh = {f["sha256"]: f for f in new.values() if f["sha256"] and f["sha256"] not in old_hashes}
    before, after = totals(previous["files"]), totals(current["files"])
    return {"comparable": True, "reason": None, "gzip_delta_bytes": after["gzip_bytes"] - before["gzip_bytes"], "raw_delta_bytes": after["raw_bytes"] - before["raw_bytes"], "added": sorted(new.keys() - old.keys()), "removed": sorted(old.keys() - new.keys()), "changed": sorted(path for path in old.keys() & new.keys() if new[path]["sha256"] != old[path]["sha256"]), "renamed_identical": renamed, "new_unique_content_gzip_bytes": sum(f["gzip_bytes"] for f in fresh.values()), "by_kind": {name: after["by_kind"].get(name, {}).get("gzip_bytes", 0) - before["by_kind"].get(name, {}).get("gzip_bytes", 0) for name in sorted(before["by_kind"].keys() | after["by_kind"].keys())}}


def analyse(root, *, baseline=None, public_path="/", max_total_gzip_kib=None, max_asset_gzip_kib=None, max_growth_kib=None):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Build root must be a regular directory, not a symlink")
    public_path = mount_path(public_path)
    limits = {"total": max_total_gzip_kib, "asset": max_asset_gzip_kib, "growth": max_growth_kib}
    if any(value is not None and (type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 1048576) for value in limits.values()):
        raise ValueError("Budgets must be finite KiB values between 0 and 1048576")
    if max_growth_kib is not None and baseline is None:
        raise ValueError("A growth budget requires a baseline snapshot")
    inventory, findings, pages, stylesheets, stamps = [], [], [], [], {}
    total_bytes, private_directories = 0, 0

    def finding(rule, message, severity="warning", path=None, line=None):
        if len(findings) >= 1000:
            raise ValueError("Build has more than 1000 findings; narrow the build directory")
        result = {"rule": rule, "message": message, "severity": severity}
        if path:
            result["path"] = path
        if line:
            result["line"] = line
        findings.append(result)

    def checked_stat(path):
        value = path.stat()
        return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns

    def walk_error(error):
        raise error

    for base, directories, names in os.walk(root, followlinks=False, onerror=walk_error):
        if len(stamps) > MAX_FILES * 2:
            raise ValueError("Build exceeds the directory traversal limit")
        stamps[Path(base)] = checked_stat(Path(base))
        for name in sorted(directories):
            path = Path(base) / name
            relative = safe_path(path.relative_to(root).as_posix())
            if path.is_symlink():
                raise ValueError("Build contains a symlink; inspect a materialized artifact directory")
            if name in {".git", ".svn", ".hg"}:
                finding("private-build-entry", "Version-control metadata is present in the deployment output", "error", relative)
                directories.remove(name)
                private_directories += 1
        directories.sort()
        for name in sorted(names):
            path = Path(base) / name
            relative = safe_path(path.relative_to(root).as_posix())
            if path.is_symlink() or not path.is_file():
                raise ValueError("Build contains a symlink or non-regular file")
            if len(inventory) >= MAX_FILES:
                raise ValueError("Build exceeds 3000 files; narrow the directory")
            stamps[path] = checked_stat(path)
            size = stamps[path][2]
            total_bytes += size
            if size > MAX_FILE_BYTES or total_bytes > MAX_TOTAL_BYTES:
                raise ValueError("Build exceeds the 32 MiB file or 256 MiB total inspection limit")
            row = {"path": relative, "raw_bytes": size, "gzip_bytes": None, "sha256": None}
            if private_asset(path):
                finding("private-build-entry", "Potentially private file is present in the deployment output; contents were not read", "error", relative)
            else:
                with path.open("rb") as stream:
                    payload = stream.read(MAX_FILE_BYTES + 1)
                if len(payload) != size or checked_stat(path) != stamps[path]:
                    raise ValueError("Build changed during inspection; run against a finished build")
                row.update(gzip_bytes=len(gzip.compress(payload, compresslevel=9, mtime=0)), sha256=hashlib.sha256(payload).hexdigest())
                if kind(relative) == "html":
                    parser = Resources()
                    parser.feed(payload.decode("utf-8", errors="replace"))
                    parser.close()
                    pages.append((relative, parser))
                elif kind(relative) == "style":
                    parser = css_resources(payload, MAX_REFERENCES)
                    stylesheets.append((relative, parser))
                    if parser.unparsed:
                        finding("css-reference-coverage", "Some CSS tokens or the stylesheet encoding could not be inspected; literal resource coverage is incomplete", "warning", relative)
                if kind(relative) == "source-map":
                    finding("published-source-map", "Source map is included in the deployment output; review whether publishing it is intended", "note", relative)
            inventory.append(row)
    if not inventory:
        raise ValueError("Build directory has no regular asset files")
    snapshot = {"schema": 1, "kind": "assetguard-snapshot", "compression": "gzip-9", "compressor": zlib.ZLIB_RUNTIME_VERSION, "public_path": public_path, "private_directories": private_directories, "files": inventory}
    validate_snapshot(snapshot)
    known = {f["path"] for f in inventory}
    local_references, external_references = 0, 0
    reference_count = sum(len(parser.references) for _, parser in pages + stylesheets)
    if reference_count > MAX_REFERENCES:
        raise ValueError("Build exceeds 20000 HTML/CSS resource references")
    for page, parser in pages + stylesheets:
        page_url = ORIGIN + public_path + page
        base = getattr(parser, 'base', None)
        base_url = urljoin(page_url, base) if base is not None else page_url
        for reference, line in parser.references:
            try:
                url = urlsplit(urljoin(base_url, reference))
                if url.scheme not in {"http", "https"} or url.netloc != "assetguard.invalid" or url.scheme != "https":
                    external_references += 1
                    continue
                decoded = unquote(url.path)
                if "\\" in decoded or any(ord(c) < 32 or ord(c) == 127 for c in decoded):
                    raise ValueError("Invalid URL path")
                normalized = posixpath.normpath(decoded)
            except ValueError:
                finding("invalid-resource-url", "Document contains an invalid local resource URL", "error", page, line)
                continue
            local_references += 1
            if not normalized.startswith(public_path):
                finding("resource-outside-public-path", "A resource URL points outside the configured deployment path", "error", page, line)
                continue
            target = normalized[len(public_path):]
            if target not in known:
                finding("missing-build-resource", "Referenced resource is absent from the build: " + target[:200], "error", page, line)
    summary = totals(inventory)
    summary.update(local_resource_references=local_references, external_resource_references=external_references, skipped_private_directories=private_directories)
    summary.update(css_stylesheets=len(stylesheets), css_resource_references=sum(len(p.references) for _, p in stylesheets), css_unparsed_tokens=sum(p.unparsed for _, p in stylesheets), css_fragment_references=sum(p.fragments for _, p in stylesheets))
    duplicates = []
    hashes = defaultdict(list)
    for row in inventory:
        if row["sha256"] and row["raw_bytes"]:
            hashes[row["sha256"]].append(row)
    for rows in hashes.values():
        if len(rows) > 1:
            duplicates.append({"paths": [f["path"] for f in rows], "redundant_raw_bytes": (len(rows) - 1) * rows[0]["raw_bytes"]})
            finding("duplicate-build-content", f"{len(rows)} assets have identical content; review whether multiple copies are intended", "note", rows[0]["path"])
    delta = compare(snapshot, baseline) if baseline is not None else None
    incomplete = summary["measured_files"] != summary["files"] or private_directories
    if (max_total_gzip_kib is not None or max_asset_gzip_kib is not None) and incomplete or max_growth_kib is not None and not delta["comparable"]:
        finding("asset-budget-unknown", "Missing content measurements or incompatible compression runtimes prevent verification of a requested size budget", "error")
    if max_total_gzip_kib is not None and summary["gzip_bytes"] > max_total_gzip_kib * 1024:
        finding("total-gzip-budget", f"Build gzip estimate {summary['gzip_bytes']} bytes exceeds the {max_total_gzip_kib:g} KiB budget", "error")
    if max_asset_gzip_kib is not None:
        for row in inventory:
            if row["gzip_bytes"] is not None and row["gzip_bytes"] > max_asset_gzip_kib * 1024:
                finding("asset-gzip-budget", f"Asset gzip estimate {row['gzip_bytes']} bytes exceeds the {max_asset_gzip_kib:g} KiB budget", "error", row["path"])
    if max_growth_kib is not None and delta["comparable"] and delta["gzip_delta_bytes"] > max_growth_kib * 1024:
        finding("gzip-growth-budget", f"Build gzip estimate grew by {delta['gzip_delta_bytes']} bytes, exceeding the {max_growth_kib:g} KiB growth budget", "error")
    if any(path.is_symlink() or checked_stat(path) != value for path, value in stamps.items()):
        raise ValueError("Build changed during inspection; run against a finished build")
    return {"schema": 1, "tool": "assetguard", "summary": summary, "findings": findings, "duplicates": duplicates, "comparison": delta, "snapshot": snapshot, "interpretation": "Gzip level 9 estimates describe files on disk, not browser transfer or initial-route cost. Resource checks cover explicit HTML src/href and literal url()/@import in UTF-8 CSS files. Inline styles, srcset, image-set string candidates, computed values, JavaScript imports, dynamic routes and remote availability remain outside coverage. CSS conditions are not evaluated. Identical content is not proof of waste. Source maps may be intentional. No target code is executed."}


def execute(args):
    if args.snapshot and (Path(args.snapshot).exists() or Path(args.snapshot).is_symlink()):
        raise ValueError("Snapshot output already exists; choose a fresh filename")
    baseline = load_json(Path(args.baseline)) if args.baseline else None
    result = analyse(args.root, baseline=baseline, public_path=args.public_path, max_total_gzip_kib=args.max_total_gzip_kib, max_asset_gzip_kib=args.max_asset_gzip_kib, max_growth_kib=args.max_growth_kib)
    if args.snapshot:
        target = Path(args.snapshot).resolve()
        if target.is_relative_to(Path(args.root).resolve()):
            raise ValueError("Save snapshots outside the build directory so they cannot become deployment assets")
        write_json(target, result["snapshot"])
    if args.json:
        from .engine import clean
        print(json.dumps(clean(result), indent=2, allow_nan=False))
    else:
        summary = result["summary"]
        print(f"{summary['files']} assets; {summary['raw_bytes'] / 1024:.1f} KiB raw; {summary['gzip_bytes'] / 1024:.1f} KiB gzip estimate")
        if result["comparison"] and result["comparison"]["comparable"]:
            print(f"Gzip change: {result['comparison']['gzip_delta_bytes']:+d} bytes; {len(result['comparison']['renamed_identical'])} identical-content rename(s)")
        elif result["comparison"]:
            print("Build comparison unavailable: " + result["comparison"]["reason"])
        for item in result["findings"]:
            print(redact(f"[{item['severity']}] {item['rule']}: {item.get('path', '.')} — {item['message']}"))
        print(result["interpretation"])
    return int(any(item["severity"] == "error" for item in result["findings"]))
