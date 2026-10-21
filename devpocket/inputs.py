"""Bounded reads for explicit, root-contained diagnostic inputs."""
from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
import stat


def read_text(root, relative, max_bytes):
    """Read UTF-8 without following symlinks or including content in errors."""
    root = Path(root).resolve()
    name = PurePosixPath(relative)
    if not relative or name.is_absolute() or ".." in name.parts or "\\" in relative or ":" in relative:
        raise ValueError("Diagnostic inputs must be relative POSIX paths inside the project")
    path = root.joinpath(*name.parts)

    def check_path():
        current = root
        for part in name.parts:
            current /= part
            if current.is_symlink() or current.resolve() != current:
                raise ValueError("Diagnostic inputs cannot use symlinks or redirected directories")

    check_path()
    try:
        before = path.stat()
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("Diagnostic input must be a regular file")
        if before.st_size > max_bytes:
            raise ValueError(f"Diagnostic input exceeds {max_bytes} bytes")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode):
                raise ValueError("Diagnostic input must be a regular file")
            payload = stream.read(max_bytes + 1)
            after = os.fstat(stream.fileno())
        check_path()
        current = path.stat()
    except OSError:
        raise ValueError("Cannot read diagnostic input as a regular project file") from None
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
    version = lambda s: (*identity(s), s.st_ctime_ns)
    # Windows Python 3.12+ can report creation time via stat(path) and change
    # time via fstat(fd). Compare ctime only within the same metadata API.
    if version(before) != version(current) or version(opened) != version(after) or identity(before) != identity(opened) or len(payload) != before.st_size:
        raise ValueError("Diagnostic input changed during inspection; retry with a stable file")
    if len(payload) > max_bytes:
        raise ValueError(f"Diagnostic input exceeds {max_bytes} bytes")
    try:
        return payload.decode("utf-8-sig")
    except UnicodeError:
        raise ValueError("Diagnostic input must be UTF-8 text") from None
