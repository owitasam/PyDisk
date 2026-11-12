"""Command-line interface for PyDisk Analyzer.

Usage examples:
    python main.py scan ~/Downloads
    python main.py scan ~/Downloads --top 20 --progress
    python main.py find ~/Downloads --extension .mp4
    python main.py find ~/Downloads --name 'report-*.pdf' --max-size 20MB
    python main.py tui ~/Downloads
    python main.py index ~/Downloads --database ~/pydisk-index.db
    python main.py report ~/Downloads --format json
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TextIO

from pydisk import __version__
from pydisk.analyzer import (
    FileTypeSummary,
    file_type_summary,
    find_files,
    largest_files,
    largest_folders,
    normalize_extension,
)
from pydisk.formatter import (
    escape_control_characters,
    human_readable_size,
    parse_size,
)
from pydisk.indexer import IndexWriter
from pydisk.reporter import (
    build_report,
    format_json_report,
    format_text_report,
    write_json_report,
    write_text_report,
)
from pydisk.scanner import (
    FileInfo,
    ScanIssue,
    ScanProgress,
    ScanResult,
    scan_directory,
)

# Reports go into a "reports" folder relative to the current directory.
REPORT_DIR = Path.cwd() / "reports"
ISSUE_PREVIEW_LIMIT = 5


class UserError(Exception):
    """An error caused by invalid command-line input."""


def non_negative_int(value: str) -> int:
    """argparse type: a whole number that is zero or greater."""
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"expected a whole number, got {value!r}"
        ) from exc
    if number < 0:
        raise argparse.ArgumentTypeError("value must be zero or greater")
    return number


def size_argument(value: str) -> int:
    """argparse type: a size such as 512, 100MB or 1.5 GB."""
    try:
        return parse_size(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def depth_argument(value: str) -> int:
    """argparse type: a folder depth of at least one."""
    number = non_negative_int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("depth must be one or greater")
    return number


def add_scan_options(parser: argparse.ArgumentParser) -> None:
    """Add options that control how a directory is scanned."""
    parser.add_argument(
        "-x",
        "--exclude",
        action="append",
        default=None,
        metavar="PATTERN",
        help=(
            "skip names or relative paths matching this glob; "
            "repeatable (for example: --exclude .git)"
        ),
    )
    parser.add_argument(
        "--exclude-from",
        action="append",
        type=Path,
        default=None,
        metavar="FILE",
        help=(
            "read exclude patterns from FILE, one per line; "
            "blank lines and lines starting with # are ignored"
        ),
    )
    parser.add_argument(
        "--progress",
        action="store_true",
        help="show scan progress on stderr when it is a terminal",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="suppress normal result output; exit codes still report errors",
    )
    parser.add_argument(
        "--one-file-system",
        action="store_true",
        help="do not descend into other mounted filesystems",
    )
    parser.add_argument(
        "--count-hardlinks",
        action="store_true",
        help="count every hard link separately (default: count each inode once)",
    )
    parser.add_argument(
        "--disk-usage",
        action="store_true",
        help="use allocated disk blocks instead of apparent file size",
    )
    parser.add_argument(
        "--max-skipped",
        type=non_negative_int,
        default=1000,
        metavar="N",
        help="keep details for at most N skipped paths (default: 1000)",
    )
    parser.add_argument(
        "--max-errors",
        type=non_negative_int,
        default=1000,
        metavar="N",
        help="keep details for at most N errors (default: 1000)",
    )


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="pydisk",
        description="Read-only disk usage analyzer for Linux.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        metavar="COMMAND",
    )

    scan_parser = subparsers.add_parser(
        "scan",
        help="scan a directory and show the biggest files and folders",
    )
    scan_parser.add_argument("path", type=Path, help="directory to scan")
    scan_parser.add_argument(
        "--top",
        type=non_negative_int,
        default=10,
        help="number of files, folders and types to show (default: 10)",
    )
    scan_parser.add_argument(
        "--depth",
        type=depth_argument,
        default=1,
        metavar="N",
        help="group folder totals by N directory levels (default: 1)",
    )
    add_scan_options(scan_parser)
    scan_parser.set_defaults(handler=run_scan)

    find_parser = subparsers.add_parser(
        "find",
        help="find files by name, extension and/or size",
    )
    find_parser.add_argument("path", type=Path, help="directory to scan")
    find_parser.add_argument(
        "-e",
        "--extension",
        help="only files ending with this extension (for example .mp4)",
    )
    find_parser.add_argument(
        "-n",
        "--name",
        help="only files matching this shell-style name pattern (report-*.pdf)",
    )
    find_parser.add_argument(
        "-m",
        "--min-size",
        type=size_argument,
        help="only files at least this large (for example 100MB)",
    )
    find_parser.add_argument(
        "-M",
        "--max-size",
        type=size_argument,
        help="only files at most this large (for example 10MB)",
    )
    find_parser.add_argument(
        "--top",
        type=non_negative_int,
        default=20,
        help="maximum number of matches to show (default: 20)",
    )
    find_parser.add_argument(
        "--all",
        action="store_true",
        help="show every match (ignores --top)",
    )
    add_scan_options(find_parser)
    find_parser.set_defaults(handler=run_find)

    tui_parser = subparsers.add_parser(
        "tui",
        help="browse a scan in an interactive terminal UI",
    )
    tui_parser.add_argument("path", type=Path, help="directory to scan")
    add_scan_options(tui_parser)
    tui_parser.set_defaults(handler=run_tui_command)

    index_parser = subparsers.add_parser(
        "index",
        help="scan into a new SQLite database without keeping files in memory",
    )
    index_parser.add_argument("path", type=Path, help="directory to scan")
    index_parser.add_argument(
        "-d",
        "--database",
        type=Path,
        required=True,
        metavar="FILE",
        help="new SQLite database file to create",
    )
    add_scan_options(index_parser)
    index_parser.set_defaults(handler=run_index)

    report_parser = subparsers.add_parser(
        "report",
        help="scan a directory and save a JSON or text report",
    )
    report_parser.add_argument("path", type=Path, help="directory to scan")
    report_parser.add_argument(
        "-f",
        "--format",
        choices=("json", "txt", "text"),
        default="json",
        help="report format; 'text' is an alias for 'txt' (default: json)",
    )
    report_parser.add_argument(
        "--top",
        type=non_negative_int,
        default=10,
        help="number of files, folders and types to include (default: 10)",
    )
    report_parser.add_argument(
        "--depth",
        type=depth_argument,
        default=1,
        metavar="N",
        help="group folder totals by N directory levels (default: 1)",
    )
    output_group = report_parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "-o",
        "--output",
        type=Path,
        help=(
            "file to create (default: a timestamped file in reports/; "
            "use - for stdout)"
        ),
    )
    output_group.add_argument(
        "--stdout",
        action="store_true",
        help="write the report to stdout instead of creating a file",
    )
    add_scan_options(report_parser)
    report_parser.set_defaults(handler=run_report)

    return parser


def read_exclude_patterns(paths: list[Path] | None) -> list[str]:
    """Read exclude patterns from files, ignoring blanks and comments."""
    patterns: list[str] = []
    for path in paths or []:
        source = path.expanduser()
        try:
            text = source.read_text(encoding="utf-8")
        except OSError as exc:
            raise UserError(
                f"cannot read exclude file {source}: {exc}"
            ) from exc
        except UnicodeError as exc:
            raise UserError(
                f"exclude file is not valid UTF-8: {source}"
            ) from exc

        for line in text.splitlines():
            pattern = line.strip()
            if pattern and not pattern.startswith("#"):
                patterns.append(pattern)
    return patterns


class ProgressReporter:
    """Print throttled scan progress to stderr for interactive use."""

    def __init__(
        self,
        stream: TextIO | None = None,
        interval: float = 0.1,
    ) -> None:
        self.stream = stream if stream is not None else sys.stderr
        self.interval = interval
        self.last_progress: ScanProgress | None = None
        self.last_update = 0.0

    def __call__(self, progress: ScanProgress) -> None:
        self.last_progress = progress
        now = time.monotonic()
        if self.last_update and now - self.last_update < self.interval:
            return
        self.last_update = now
        print(self._line(progress), end="\r", file=self.stream, flush=True)

    def finish(self, completed: bool = True) -> None:
        """Leave the final progress snapshot on its own line."""
        if self.last_progress is None:
            return
        suffix = " done" if completed else ""
        line = self._line(self.last_progress) + suffix
        print(line, file=self.stream, flush=True)

    @staticmethod
    def _line(progress: ScanProgress) -> str:
        return (
            f"Scanning: {progress.files} files, "
            f"{progress.directories} folders, "
            f"{progress.skipped} skipped, "
            f"{progress.errors} errors"
        )


def _stderr_is_tty() -> bool:
    """Return whether stderr is attached to an interactive terminal."""
    try:
        return bool(sys.stderr.isatty())
    except (AttributeError, OSError, ValueError):
        return False


def _stream_is_tty(stream: object) -> bool:
    """Return whether a stream is an interactive terminal."""
    try:
        return bool(stream.isatty())  # type: ignore[attr-defined]
    except (AttributeError, OSError, ValueError):
        return False


def _streams_are_interactive() -> bool:
    """Return whether both stdin and stdout can host the terminal UI."""
    return _stream_is_tty(sys.stdin) and _stream_is_tty(sys.stdout)


def scan_from_args(
    args: argparse.Namespace,
    *,
    collect_files: bool = True,
    file_callback: Callable[[FileInfo], None] | None = None,
) -> ScanResult:
    """Run a scan using the shared scan options on ``args``."""
    excludes = list(args.exclude or ())
    excludes.extend(read_exclude_patterns(args.exclude_from))
    progress = (
        ProgressReporter()
        if args.progress and not args.quiet and _stderr_is_tty()
        else None
    )

    completed = False
    try:
        result = scan_directory(
            args.path,
            excludes=excludes,
            one_file_system=args.one_file_system,
            count_hardlinks=args.count_hardlinks,
            disk_usage=args.disk_usage,
            max_skipped=args.max_skipped,
            max_errors=args.max_errors,
            progress=progress,
            collect_files=collect_files,
            file_callback=file_callback,
        )
        completed = True
        return result
    finally:
        if progress is not None:
            progress.finish(completed=completed)


def partial_scan_exit_code(result: ScanResult) -> int:
    """Return a non-zero code when the scan was incomplete."""
    return 1 if result.error_count else 0


def print_quiet_warning(result: ScanResult) -> None:
    """Make sure ``--quiet`` still tells scripts that a scan was incomplete."""
    if result.error_count:
        print(
            f"warning: {result.error_count} scan errors; "
            "rerun without --quiet for details",
            file=sys.stderr,
        )


def run_scan(args: argparse.Namespace) -> int:
    """Handle the ``scan`` command."""
    result = scan_from_args(args)
    if args.quiet:
        print_quiet_warning(result)
    else:
        print_scan_summary(result, args.top, depth=args.depth)
    return partial_scan_exit_code(result)


def run_tui_command(args: argparse.Namespace) -> int:
    """Handle the ``tui`` command."""
    if not _streams_are_interactive():
        raise UserError("tui requires an interactive terminal")

    # Imported lazily so the other commands still work on Python builds
    # without the curses extension.
    try:
        from pydisk.tui import run_terminal_ui
    except ImportError as exc:
        raise UserError(
            "the terminal UI is not available in this Python build"
        ) from exc

    if not args.quiet:
        args.progress = True
        print(
            "Scanning "
            + escape_control_characters(str(args.path))
            + " ...",
            file=sys.stderr,
            flush=True,
        )

    result = scan_from_args(args)
    run_terminal_ui(result)

    if result.error_count:
        print(
            f"warning: scan completed with {result.error_count} errors",
            file=sys.stderr,
        )
    return partial_scan_exit_code(result)


def run_index(args: argparse.Namespace) -> int:
    """Handle the ``index`` command."""
    writer = IndexWriter(args.database)
    try:
        result = scan_from_args(
            args,
            collect_files=False,
            file_callback=writer.add_file,
        )
        writer.finish(result)
    except sqlite3.Error as exc:
        writer.abort()
        raise OSError(f"index write failed: {exc}") from exc
    except BaseException:
        writer.abort()
        raise
    try:
        writer.close()
    except sqlite3.Error as exc:
        raise OSError(f"cannot close index: {exc}") from exc

    if args.quiet:
        print_quiet_warning(result)
    else:
        print(
            "Index written to "
            + escape_control_characters(str(writer.path))
        )
        print(
            f"Indexed {result.file_count} files in "
            + escape_control_characters(str(result.root))
            + f" ({human_readable_size(result.total_size)})"
        )
        print(f"Folders      : {result.directory_count}")
        print(f"Skipped      : {result.skipped_count}")
        print(f"Errors       : {result.error_count}")
    return partial_scan_exit_code(result)


def run_find(args: argparse.Namespace) -> int:
    """Handle the ``find`` command."""
    if (
        args.extension is None
        and args.name is None
        and args.min_size is None
        and args.max_size is None
    ):
        raise UserError(
            "provide at least one filter: --extension, --name, "
            "--min-size or --max-size"
        )
    if args.name is not None and not args.name.strip():
        raise UserError("name pattern must not be empty")
    if (
        args.min_size is not None
        and args.max_size is not None
        and args.min_size > args.max_size
    ):
        raise UserError("minimum size cannot be greater than maximum size")

    extension = (
        normalize_extension(args.extension) if args.extension is not None else None
    )

    result = scan_from_args(args)
    if args.quiet:
        print_quiet_warning(result)
        return partial_scan_exit_code(result)

    matches = find_files(
        result.files,
        extension=extension,
        min_size=args.min_size,
        max_size=args.max_size,
        name=args.name,
    )
    shown = matches if args.all else largest_files(matches, args.top)
    match_size = sum(file.size for file in matches)

    criteria = []
    if extension is not None:
        criteria.append(
            "name ends with " + escape_control_characters(extension)
        )
    if args.name is not None:
        pattern = escape_control_characters(args.name)
        criteria.append(f"name matches {pattern!r}")
    if args.min_size is not None:
        criteria.append(f"size >= {human_readable_size(args.min_size)}")
    if args.max_size is not None:
        criteria.append(f"size <= {human_readable_size(args.max_size)}")

    print(
        "Search location: "
        + escape_control_characters(str(result.root))
    )
    print(f"Criteria       : {', '.join(criteria)}")
    print(f"Matches        : {len(matches)} of {result.file_count} files")
    print(f"Showing        : {len(shown)} of {len(matches)} matches")
    print()

    if not shown:
        print("(no matching files)")
    for index, file in enumerate(shown, start=1):
        print(format_rank_line(index, file.size, match_size, file.path))

    print_issues("Scan errors", result.errors, result.error_count)
    return partial_scan_exit_code(result)


def run_report(args: argparse.Namespace) -> int:
    """Handle the ``report`` command."""
    stdout_output = args.stdout or (
        args.output is not None and str(args.output) == "-"
    )
    if (
        not stdout_output
        and args.output is not None
        and args.output.exists()
    ):
        raise UserError(
            "refusing to overwrite existing file: "
            + escape_control_characters(str(args.output))
        )

    report_format = "txt" if args.format == "text" else args.format
    result = scan_from_args(args)
    report = build_report(
        result,
        top=args.top,
        max_skipped=args.max_skipped,
        max_errors=args.max_errors,
        depth=args.depth,
    )

    if stdout_output:
        if report_format == "json":
            sys.stdout.write(format_json_report(report))
        else:
            sys.stdout.write(format_text_report(report))
        sys.stdout.flush()
    else:
        output = args.output or default_report_path(result.root, report_format)
        if report_format == "json":
            write_json_report(report, output)
        else:
            write_text_report(report, output)

        if not args.quiet:
            print(
                "Report written to "
                + escape_control_characters(str(output))
            )
            print(
                "Scanned "
                f"{result.file_count} files in "
                + escape_control_characters(str(result.root))
                + f" ({human_readable_size(result.total_size)})"
            )
            print(
                f"Skipped {result.skipped_count} items, "
                f"recorded {len(report['skipped'])} in the report"
            )
            if result.error_count:
                print(
                    f"Encountered {result.error_count} scan errors, "
                    f"recorded {len(report['errors'])} in the report"
                )

    if args.quiet:
        print_quiet_warning(result)
    return partial_scan_exit_code(result)


def default_report_path(directory: Path, report_format: str) -> Path:
    """Build a unique, timestamped report path inside ``REPORT_DIR``."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    folder_name = directory.expanduser().resolve().name or "root"
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", folder_name).strip("._")
    base = f"pydisk-{safe_name or 'scan'}-{stamp}"

    candidate = REPORT_DIR / f"{base}.{report_format}"
    counter = 2
    while candidate.exists():
        candidate = REPORT_DIR / f"{base}-{counter}.{report_format}"
        counter += 1
    return candidate


def print_scan_summary(result: ScanResult, top: int, depth: int = 1) -> None:
    """Print the totals plus the largest files, folders and file types."""
    metric = "allocated disk blocks" if result.disk_usage else "apparent file size"
    print(
        "Scan location: "
        + escape_control_characters(str(result.root))
    )
    print(f"Size metric  : {metric}")
    if depth != 1:
        print(f"Folder depth : {depth}")
    if result.excludes:
        patterns = ", ".join(
            escape_control_characters(pattern) for pattern in result.excludes
        )
        print("Excludes     : " + patterns)
    print(
        f"Total size   : {human_readable_size(result.total_size)} "
        f"({result.total_size} bytes)"
    )
    print(f"Files        : {result.file_count}")
    print(f"Folders      : {result.directory_count}")

    print()
    print("Largest files")
    print("-------------")
    files = largest_files(result.files, top)
    if not files:
        print("(no files found)")
    for index, file in enumerate(files, start=1):
        print(format_rank_line(index, file.size, result.total_size, file.path))

    folder_heading = (
        "Largest folders"
        if depth == 1
        else f"Largest folders (depth {depth})"
    )
    print()
    print(folder_heading)
    print("-" * len(folder_heading))
    folders = largest_folders(result, top, depth=depth)
    if not folders:
        print("(no subdirectories with files)")
    for index, folder in enumerate(folders, start=1):
        print(format_rank_line(index, folder.size, result.total_size, folder.path))

    print()
    print("File types")
    print("----------")
    types = file_type_summary(result.files, limit=top)
    if not types:
        print("(no files found)")
    for index, item in enumerate(types, start=1):
        print(format_type_line(index, item, result.total_size))

    print_issues("Skipped items", result.skipped, result.skipped_count)
    print_issues("Scan errors", result.errors, result.error_count)


def format_rank_line(index: int, size: int, total: int, path: Path) -> str:
    """Format one line of a largest-items ranking with a percentage."""
    percentage = (size / total * 100) if total else 0.0
    return (
        f"{index:>3}. {human_readable_size(size):>10} "
        f"{percentage:>5.1f}%  {escape_control_characters(str(path))}"
    )


def format_type_line(
    index: int,
    item: FileTypeSummary,
    total: int,
) -> str:
    """Format one line of the file-type summary."""
    percentage = (item.size / total * 100) if total else 0.0
    label = "file" if item.file_count == 1 else "files"
    extension = escape_control_characters(item.extension)
    return (
        f"{index:>3}. {human_readable_size(item.size):>10} "
        f"{percentage:>5.1f}%  {extension} ({item.file_count} {label})"
    )


def print_issues(
    title: str,
    issues: list[ScanIssue],
    total: int | None = None,
    limit: int = ISSUE_PREVIEW_LIMIT,
) -> None:
    """Print a short summary of skipped items or errors."""
    actual_total = len(issues) if total is None else max(total, len(issues))
    if actual_total == 0 and not issues:
        return

    print()
    print(f"{title}: {actual_total}")
    for issue in issues[:limit]:
        path = escape_control_characters(str(issue.path))
        reason = escape_control_characters(issue.reason)
        print(f"  {path}: {reason}")
    shown = min(len(issues), limit)
    if actual_total > shown:
        print(f"  ... and {actual_total - shown} more")


def _configure_output() -> None:
    """Make stdout/stderr tolerant of characters the locale cannot encode."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="backslashreplace")
        except (OSError, ValueError):
            pass


def _silence_broken_pipe() -> None:
    """Point stdout at /dev/null so interpreter shutdown stays quiet."""
    try:
        target = sys.stdout.fileno()
        devnull = os.open(os.devnull, os.O_WRONLY)
    except (OSError, ValueError):
        return

    try:
        if devnull != target:
            os.dup2(devnull, target)
    finally:
        if devnull != target:
            os.close(devnull)


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, run the chosen command, and return an exit code."""
    _configure_output()
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return args.handler(args)
    except BrokenPipeError:
        _silence_broken_pipe()
        return 0
    except (UserError, ValueError, OSError) as exc:
        message = escape_control_characters(str(exc))
        print(f"error: {message}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
