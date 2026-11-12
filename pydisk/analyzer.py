"""Analysis helpers for files and folders found by the scanner."""

from __future__ import annotations

import fnmatch
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .scanner import FileInfo, ScanResult


@dataclass(frozen=True)
class FolderSize:
    """The total size of one folder at the requested depth."""

    path: Path
    size: int


@dataclass(frozen=True)
class FileTypeSummary:
    """Total size and file count for one extension."""

    extension: str
    size: int
    file_count: int


def largest_files(files: Iterable[FileInfo], limit: int = 10) -> list[FileInfo]:
    """Return the ``limit`` largest files, biggest first."""
    if limit < 0:
        raise ValueError("limit must be zero or greater")
    ordered = sorted(files, key=lambda file: (-file.size, str(file.path)))
    return ordered[:limit]


def normalize_extension(extension: str) -> str:
    """Normalize user input such as ``mp4`` or ``*.MP4`` to ``.mp4``."""
    normalized = extension.strip().lower()
    if normalized.startswith("*."):
        normalized = normalized[1:]
    if normalized and not normalized.startswith("."):
        normalized = "." + normalized
    if normalized in {"", "."}:
        raise ValueError("extension must not be empty (try '.mp4')")
    return normalized


def find_files(
    files: Iterable[FileInfo],
    extension: str | None = None,
    min_size: int | None = None,
    max_size: int | None = None,
    name: str | None = None,
) -> list[FileInfo]:
    """Filter files by name, extension and/or a size range.

    Extension matching is case-insensitive and also matches compound suffixes
    such as ``.tar.gz``. ``name`` is a case-insensitive shell-style filename
    pattern such as ``report-*.pdf``. Size limits are inclusive and measured in
    bytes.
    """
    if min_size is not None and min_size < 0:
        raise ValueError("minimum size must be zero or greater")
    if max_size is not None and max_size < 0:
        raise ValueError("maximum size must be zero or greater")
    if (
        min_size is not None
        and max_size is not None
        and min_size > max_size
    ):
        raise ValueError("minimum size cannot be greater than maximum size")
    if name is not None and not name.strip():
        raise ValueError("name pattern must not be empty")

    matches = list(files)

    if extension is not None:
        suffix = normalize_extension(extension)
        matches = [
            file for file in matches if file.path.name.lower().endswith(suffix)
        ]

    if name is not None:
        pattern = name.lower()
        matches = [
            file
            for file in matches
            if fnmatch.fnmatchcase(file.path.name.lower(), pattern)
        ]

    if min_size is not None:
        matches = [file for file in matches if file.size >= min_size]

    if max_size is not None:
        matches = [file for file in matches if file.size <= max_size]

    return matches


def largest_folders(
    result: ScanResult,
    limit: int = 10,
    depth: int = 1,
) -> list[FolderSize]:
    """Return the largest folders of the scan root, grouped by ``depth``.

    Depth 1 gives the immediate subdirectories (the default). Depth 2 merges
    files into their first two directory levels, and so on. A folder's size is
    the sum of every file below it. Files sitting directly in the scan root are
    not attributed to any subdirectory.
    """
    if limit < 0:
        raise ValueError("limit must be zero or greater")
    if depth < 1:
        raise ValueError("depth must be one or greater")

    totals: dict[Path, int] = defaultdict(int)
    for file in result.files:
        try:
            relative = file.path.relative_to(result.root)
        except ValueError:
            # Defensive: ignore files outside the scanned tree.
            continue
        if len(relative.parts) > 1:
            directory_parts = relative.parts[:-1]
            totals[result.root.joinpath(*directory_parts[:depth])] += file.size

    ordered = sorted(
        (FolderSize(path=path, size=size) for path, size in totals.items()),
        key=lambda folder: (-folder.size, str(folder.path)),
    )
    return ordered[:limit]


def file_type_summary(
    files: Iterable[FileInfo],
    limit: int | None = None,
) -> list[FileTypeSummary]:
    """Summarize size and file count by extension, biggest first.

    Files without a suffix are grouped under ``(no extension)``. ``limit`` of
    ``None`` returns every extension.
    """
    if limit is not None and limit < 0:
        raise ValueError("limit must be zero or greater")

    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for file in files:
        extension = file.path.suffix.lower() or "(no extension)"
        totals[extension][0] += file.size
        totals[extension][1] += 1

    ordered = sorted(
        (
            FileTypeSummary(
                extension=extension,
                size=size,
                file_count=file_count,
            )
            for extension, (size, file_count) in totals.items()
        ),
        key=lambda item: (-item.size, item.extension),
    )
    return ordered if limit is None else ordered[:limit]
