"""Which file a chunk came from: the full path is its identity, the base name is only for display.

Ray's ``read_binary_files(include_paths=True)`` yields a ``path`` column holding the object's full location
(``bucket/prefix/dir/file.pdf``; a leading ``s3://`` is tolerated) and no ``filename`` column. Two files in
different folders can share a base name, and the sinks derive chunk IDs and the stale-chunk sweep from the file's
identity, so keying on the base name would let one file overwrite or sweep away another's chunks.
"""

from __future__ import annotations

import posixpath
from typing import Tuple

_SCHEMES = ("s3://", "s3a://", "s3n://")


def file_identity(path: str) -> Tuple[str, str]:
    """Return ``(source_path, display_name)`` for a Ray ``path`` value.

    ``source_path`` is the path without a URL scheme; ``display_name`` is its last segment. An empty path, or one
    that ends in a separator, names no file and raises ``ValueError`` rather than producing an empty identity.
    """
    source_path = str(path).strip()
    for scheme in _SCHEMES:
        if source_path.lower().startswith(scheme):
            source_path = source_path[len(scheme) :]
            break
    display_name = posixpath.basename(source_path)
    if not source_path or not display_name:
        raise ValueError(f"cannot identify a file from the path {path!r}")
    return source_path, display_name
