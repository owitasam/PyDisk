"""Recursive, read-only directory scanning.

The scanner walks a directory tree with ``os.scandir`` and collects regular
files and their sizes. Symbolic links are never followed, which keeps scans
fast and prevents infinite loops between linked directories.
"""

from __future__ import annotations

import fnmatch
import os
import stat
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

PROGRESS_INTERVAL = 1000


@dataclass(frozen=True)
class FileInfo:
    """A regular file found during a scan."""

    path: Path
    size: int


@dataclass(frozen=True)
class ScanIssue:
    """A path that was skipped or could not be read, with the reason why."""

    path: Path
    reason: str


@dataclass(frozen=True)
class ScanProgress:
    """A snapshot of a scan that is still running."""

    current_path: Path
    files: int
    directories: int
    skipped: int
    errors: int


@dataclass
class ScanResult:
    """Everything collected while scanning one directory tree."""

    root: Path
    files: list[FileInfo] = field(default_factory=list)
    files_total: int = 0
    total_size_bytes: int = 0
    directory_count: int = 0
    errors: list[ScanIssue] = field(default_factory=list)
    skipped: list[ScanIssue] = field(default_factory=list)
    errors_total: int = 0
    errors_summary: dict[str, int] = field(default_factory=dict)
    skipped_total: int = 0
    skipped_summary: dict[str, int] = field(default_factory=dict)
    excludes: tuple[str, ...] = ()
    one_file_system: bool = False
    count_hardlinks: bool = False
    disk_usage: bool = False

    @property
    def file_count(self) -> int:
        """Return the number of regular files found."""
        return max(self.files_total, len(self.files))

    @property
    def total_size(self) -> int:
        """Return the total size of all counted files, in bytes."""
        if self.files_total:
            return self.total_size_bytes
        return sum(file.size for file in self.files)

    @property
    def skipped_count(self) -> int:
        """Return the total number of skipped paths, including unrecorded ones."""
        return max(self.skipped_total, len(self.skipped))

    @property
    def error_count(self) -> int:
        """Return the total number of errors, including unrecorded ones."""
        return max(self.errors_total, len(self.errors))


@dataclass
class _ScanState:
    """Options and bookkeeping shared by every scanned entry."""

    root: Path
    root_device: int
    excludes: tuple[str, ...]
    one_file_system: bool
    count_hardlinks: bool
    disk_usage: bool
    max_skipped: int | None
    max_errors: int | None
    collect_files: bool = True
    file_callback: Callable[[FileInfo], None] | None = None
    progress: Callable[[ScanProgress], None] | None = None
    seen_inodes: set[tuple[int, int]] = field(default_factory=set)
    entries_since_progress: int = 0

    def report_progress(
        self,
        result: ScanResult,
        current_path: Path,
        *,
        force: bool = False,
    ) -> None:
        """Send a progress snapshot every ``PROGRESS_INTERVAL`` entries."""
        if self.progress is None:
            return

        self.entries_since_progress += 1
        if not force and self.entries_since_progress < PROGRESS_INTERVAL:
            return

        self.entries_since_progress = 0
        self.progress(
            ScanProgress(
                current_path=current_path,
                files=result.file_count,
                directories=result.directory_count,
                skipped=result.skipped_count,
                errors=result.error_count,
            )
        )

    def record_skipped(self, result: ScanResult, issue: ScanIssue) -> None:
        """Count a skipped path and keep its details up to the limit."""
        result.skipped_total += 1
        result.skipped_summary[issue.reason] = (
            result.skipped_summary.get(issue.reason, 0) + 1
        )
        if self.max_skipped is None or len(result.skipped) < self.max_skipped:
            result.skipped.append(issue)

    def record_error(self, result: ScanResult, issue: ScanIssue) -> None:
        """Count an error and keep its details up to the limit."""
        result.errors_total += 1
        result.errors_summary[issue.reason] = (
            result.errors_summary.get(issue.reason, 0) + 1
        )
        if self.max_errors is None or len(result.errors) < self.max_errors:
            result.errors.append(issue)

    def matched_exclude(self, path: Path) -> str | None:
        """Return the first exclude pattern matching ``path``, if any.

        Patterns without a slash match the entry name (``node_modules``,
        ``*.log``). Patterns containing a slash match the path relative to the
        scan root with path-aware globbing (``build/*.o``), so ``*`` does not
        accidentally swallow directory separators.
        """
        if not self.excludes:
            return None

        try:
            relative = path.relative_to(self.root).as_posix()
        except ValueError:
            relative = path.name

        for pattern in self.excludes:
            if "/" in pattern:
                if PurePosixPath(relative).match(pattern):
                    return pattern
            elif fnmatch.fnmatchcase(path.name, pattern):
                return pattern
        return None


def scan_directory(
    directory: str | Path,
    *,
    excludes: Sequence[str] | None = None,
    one_file_system: bool = False,
    count_hardlinks: bool = False,
    disk_usage: bool = False,
    max_skipped: int | None = None,
    max_errors: int | None = None,
    progress: Callable[[ScanProgress], None] | None = None,
    collect_files: bool = True,
    file_callback: Callable[[FileInfo], None] | None = None,
) -> ScanResult:
    """Recursively scan ``directory`` without following symbolic links.

    Missing paths raise ``FileNotFoundError`` and paths that are not
    directories raise ``NotADirectoryError``. Individual entries that cannot be
    read are recorded in ``result.errors`` so the rest of the scan can finish.

    The root directory itself is not counted in ``directory_count``; only
    subdirectories found inside it are counted.

    Args:
        directory: Directory to scan.
        excludes: Glob patterns for names or relative paths to skip.
        one_file_system: Do not descend into other mounted filesystems.
        count_hardlinks: Count every hard link separately instead of once.
        disk_usage: Use allocated disk blocks instead of apparent file size.
        max_skipped: Keep details for at most this many skipped paths. Counts
            and per-reason summaries always include every skipped path.
        max_errors: Keep details for at most this many errors. Counts and
            per-reason summaries always include every error.
        progress: Optional callback invoked periodically with a
            :class:`ScanProgress` snapshot. It is also called at the start and
            end of the scan.
        collect_files: Store every :class:`FileInfo` in ``result.files``.
            Set to ``False`` when using ``file_callback`` to stream huge trees
            somewhere else, such as a SQLite index.
        file_callback: Optional callback invoked once for every counted file.
            It works independently of ``collect_files``.
    """
    if max_skipped is not None and max_skipped < 0:
        raise ValueError("max_skipped must be zero or greater")
    if max_errors is not None and max_errors < 0:
        raise ValueError("max_errors must be zero or greater")

    root = Path(directory).expanduser()

    try:
        root_stat = root.stat()
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"directory does not exist: {root}") from exc
    except PermissionError as exc:
        raise PermissionError(f"permission denied: {root}") from exc
    except NotADirectoryError as exc:
        raise NotADirectoryError(f"not a directory: {root}") from exc
    except OSError as exc:
        raise OSError(f"cannot access {root}: {exc}") from exc

    if not stat.S_ISDIR(root_stat.st_mode):
        raise NotADirectoryError(f"not a directory: {root}")

    # Use the real path so every collected path has one consistent prefix.
    root = root.resolve()
    pattern_tuple = tuple(excludes or ())

    result = ScanResult(
        root=root,
        excludes=pattern_tuple,
        one_file_system=one_file_system,
        count_hardlinks=count_hardlinks,
        disk_usage=disk_usage,
    )
    state = _ScanState(
        root=root,
        root_device=root_stat.st_dev,
        excludes=pattern_tuple,
        one_file_system=one_file_system,
        count_hardlinks=count_hardlinks,
        disk_usage=disk_usage,
        max_skipped=max_skipped,
        max_errors=max_errors,
        progress=progress,
        collect_files=collect_files,
        file_callback=file_callback,
    )

    # An explicit stack avoids recursion limits on deep directory trees.
    pending = [root]
    state.report_progress(result, root, force=True)

    while pending:
        current = pending.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    _process_entry(entry, result, pending, state)
                    state.report_progress(result, current)
        except OSError as exc:
            # For example a permission error on the directory itself.
            state.record_error(
                result,
                ScanIssue(current, _describe_error(exc)),
            )

    state.report_progress(result, root, force=True)
    result.files.sort(key=lambda file: str(file.path))
    return result


def _process_entry(
    entry: os.DirEntry,
    result: ScanResult,
    pending: list[Path],
    state: _ScanState,
) -> None:
    """Inspect one directory entry and record what it is."""
    path = Path(entry.path)
    try:
        if entry.is_symlink():
            state.record_skipped(
                result,
                ScanIssue(path, "symbolic link (not followed)"),
            )
            return

        pattern = state.matched_exclude(path)
        if pattern is not None:
            state.record_skipped(
                result,
                ScanIssue(path, f"excluded by pattern {pattern!r}"),
            )
            return

        stat_result = entry.stat(follow_symlinks=False)

        if (
            state.one_file_system
            and stat_result.st_dev != state.root_device
        ):
            state.record_skipped(
                result,
                ScanIssue(path, "different filesystem (--one-file-system)"),
            )
            return

        if stat.S_ISDIR(stat_result.st_mode):
            result.directory_count += 1
            pending.append(path)
            return

        if stat.S_ISREG(stat_result.st_mode):
            inode = (stat_result.st_dev, stat_result.st_ino)
            is_hard_link = stat_result.st_nlink > 1

            if (
                not state.count_hardlinks
                and is_hard_link
                and inode in state.seen_inodes
            ):
                state.record_skipped(
                    result,
                    ScanIssue(path, "hard link to an already counted file"),
                )
                return

            if is_hard_link:
                state.seen_inodes.add(inode)

            size = (
                stat_result.st_blocks * 512
                if state.disk_usage
                else stat_result.st_size
            )
            file_info = FileInfo(path=path, size=size)
            result.files_total += 1
            result.total_size_bytes += size
            if state.collect_files:
                result.files.append(file_info)
            if state.file_callback is not None:
                state.file_callback(file_info)
            return

        # Sockets, FIFOs, devices and other special files have no useful size.
        state.record_skipped(
            result,
            ScanIssue(path, "not a regular file or directory"),
        )
    except OSError as exc:
        state.record_error(result, ScanIssue(path, _describe_error(exc)))


def _describe_error(error: OSError) -> str:
    """Turn an OSError into a short message suitable for a report."""
    if isinstance(error, PermissionError):
        return "permission denied"
    if isinstance(error, FileNotFoundError):
        return "no longer exists"
    return str(error) or error.__class__.__name__
