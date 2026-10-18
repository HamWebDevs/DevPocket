"""CLI entry points for the toolkit and five standalone aliases."""
from __future__ import annotations
import argparse
import sys
from . import __version__
from . import envtwin, flaketrail, oopsfile, reporadar, undorun


def command_options(parser):
    parser.add_argument("--root", default=".", help="Working directory (default: current directory)")
    parser.add_argument("--timeout", type=float, default=60, help="Per-command timeout in seconds (default: 60)")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Command and arguments after --; no implicit shell")


def parser():
    p = argparse.ArgumentParser(prog="devpocket", description="Five tools for the frustrating parts of programming.")
    p.add_argument("--version", action="version", version=__version__)
    tools = p.add_subparsers(dest="tool", required=True)
    o = tools.add_parser("oopsfile", help="Capture a failed command as a Markdown debugging report")
    oa = o.add_subparsers(dest="action", required=True)
    r = oa.add_parser("run")
    r.add_argument("--output", default="oops-report.md")
    r.add_argument("--include-source", action="store_true", help="Opt in to project-local traceback source snippets")
    r.add_argument("--include-diff", action="store_true", help="Opt in to unstaged Git diff statistics (no patch text)")
    command_options(r)
    o.set_defaults(handler=oopsfile.execute)
    e = tools.add_parser("envtwin", help="Snapshot and compare Python environments")
    ea = e.add_subparsers(dest="action", required=True)
    s = ea.add_parser("snapshot")
    s.add_argument("--output", default="env-snapshot.json")
    d = ea.add_parser("diff")
    d.add_argument("left")
    d.add_argument("right")
    d.add_argument("--json", action="store_true")
    e.set_defaults(handler=envtwin.execute)
    u = tools.add_parser("undorun", help="Back up scoped files before a command; preview and restore changes")
    ua = u.add_subparsers(dest="action", required=True)
    r = ua.add_parser("run")
    r.add_argument("--exclude", action="append", default=[], help="Relative glob to exclude; repeatable")
    command_options(r)
    r = ua.add_parser("restore")
    r.add_argument("run_id")
    r.add_argument("--root", default=".")
    r.add_argument("--apply", action="store_true", help="Actually restore; without this flag only preview")
    u.set_defaults(handler=undorun.execute)
    f = tools.add_parser("flaketrail", help="Repeat a command and compare passing/failing output")
    f.add_argument("--runs", type=int, default=10)
    f.add_argument("--output", default="flake-report.json")
    command_options(f)
    f.set_defaults(handler=flaketrail.execute)
    r = tools.add_parser("reporadar", help="Find broken local links, missing scripts and setup gaps")
    r.add_argument("--root", default=".")
    r.add_argument("--json", action="store_true")
    r.set_defaults(handler=reporadar.execute)
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    if hasattr(args, "command"):
        if args.command[:1] == ["--"]:
            args.command = args.command[1:]
        if not args.command:
            p.error("a command is required after --")
    try:
        return args.handler(args)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"devpocket: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("devpocket: interrupted", file=sys.stderr)
        return 130


def oops_main():
    return main(["oopsfile", *sys.argv[1:]])


def env_main():
    return main(["envtwin", *sys.argv[1:]])


def undo_main():
    return main(["undorun", *sys.argv[1:]])


def flake_main():
    return main(["flaketrail", *sys.argv[1:]])


def radar_main():
    return main(["reporadar", *sys.argv[1:]])
