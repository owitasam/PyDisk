"""Build and save disk usage reports."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from . import __version__
from .analyzer import (
    FileTypeSummary,
    FolderSize,
    file_type_summary,
    largest_files,
    largest_folders,
)
from .formatter import escape_control_characters, human_readable_size
from .scanner import FileInfo, ScanIssue, ScanResult

SCHEMA_VERSION = 2


def build_report(
    result: ScanResult,
    top: int = 10,
    max_skipped: int | None = None,
    max_errors: int | None = None,
    depth: int = 1,
) -> dict[str, Any]:
    """Turn a :class:`ScanResult` into a plain dictionary.

    The dictionary is JSON-friendly, so it can be exported directly and is
    also used by the text report. ``max_skipped`` and ``max_errors`` limit how
    many detailed entries are included; full counts and per-reason summaries
    are always kept.
    """
    if top < 0:
        raise ValueError("top must be zero or greater")
    if max_skipped is not None and max_skipped < 0:
        raise ValueError("max_skipped must be zero or greater")
    if max_errors is not None and max_errors < 0:
        raise ValueError("max_errors must be zero or greater")
    if depth < 1:
        raise ValueError("depth must be one or greater")

    scanned_at = datetime.now().astimezone().isoformat(timespec="seconds")
    total = result.total_size
    files = largest_files(result.files, top)
    folders = largest_folders(result, top, depth=depth)
    file_types = file_type_summary(result.files, limit=top)

    skipped_total = result.skipped_count
    errors_total = result.error_count
    skipped = result.skipped if max_skipped is None else result.skipped[:max_skipped]
    errors = result.errors if max_errors is None else result.errors[:max_errors]

    skipped_summary = result.skipped_summary or Counter(
        issue.reason for issue in result.skipped
    )
    errors_summary = result.errors_summary or Counter(
        issue.reason for issue in result.errors
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "tool_version": __version__,
        "scan_location": str(result.root),
        "scanned_at": scanned_at,
        "scan_options": {
            "excludes": list(result.excludes),
            "one_file_system": result.one_file_system,
            "count_hardlinks": result.count_hardlinks,
            "size_metric": "disk_usage" if result.disk_usage else "apparent",
            "folder_depth": depth,
        },
        "total_size_bytes": total,
        "total_size": human_readable_size(total),
        "file_count": result.file_count,
        "folder_count": result.directory_count,
        "largest_files": [_file_to_dict(file, total) for file in files],
        "largest_folders": [_folder_to_dict(folder, total) for folder in folders],
        "file_types": [_type_to_dict(item, total) for item in file_types],
        "skipped_total": skipped_total,
        "skipped_summary": dict(Counter(skipped_summary).most_common()),
        "skipped_truncated": skipped_total > len(skipped),
        "skipped": [_issue_to_dict(issue) for issue in skipped],
        "errors_total": errors_total,
        "errors_summary": dict(Counter(errors_summary).most_common()),
        "errors_truncated": errors_total > len(errors),
        "errors": [_issue_to_dict(issue) for issue in errors],
    }


def format_json_report(report: dict[str, Any]) -> str:
    """Render a report dictionary as indented JSON text."""
    return json.dumps(report, indent=2, ensure_ascii=False) + "\n"


def write_json_report(report: dict[str, Any], output_path: str | Path) -> Path:
    """Write ``report`` as indented JSON and return the created path."""
    path = Path(output_path)
    _write_new_file(path, format_json_report(report))
    return path


def write_text_report(report: dict[str, Any], output_path: str | Path) -> Path:
    """Write ``report`` as plain text and return the created path."""
    path = Path(output_path)
    _write_new_file(path, format_text_report(report))
    return path


def format_text_report(report: dict[str, Any]) -> str:
    """Render a report dictionary as a readable plain-text document."""
    options = report.get("scan_options", {})
    metric = (
        "allocated disk blocks"
        if options.get("size_metric") == "disk_usage"
        else "apparent file size"
    )
    depth = options.get("folder_depth", 1)

    lines = [
        "PyDisk Analyzer report",
        "======================",
        f"Tool version  : {report.get('tool_version', 'unknown')}",
        "Scan location : "
        + escape_control_characters(report["scan_location"]),
        f"Scan timestamp: {report['scanned_at']}",
        f"Size metric   : {metric}",
    ]
    if depth != 1:
        lines.append(f"Folder depth  : {depth}")
    if options.get("excludes"):
        patterns = ", ".join(
            escape_control_characters(pattern) for pattern in options["excludes"]
        )
        lines.append("Excludes      : " + patterns)

    lines.extend(
        [
            f"Total size    : {report['total_size']} "
            f"({report['total_size_bytes']} bytes)",
            f"Files         : {report['file_count']}",
            f"Folders       : {report['folder_count']}",
            "",
            "Largest files",
            "-------------",
        ]
    )

    if report["largest_files"]:
        for index, entry in enumerate(report["largest_files"], start=1):
            lines.append(_ranking_line(index, entry))
    else:
        lines.append("(no files found)")

    lines.extend(["", "Largest folders", "---------------"])
    if report["largest_folders"]:
        for index, entry in enumerate(report["largest_folders"], start=1):
            lines.append(_ranking_line(index, entry))
    else:
        lines.append("(no subdirectories with files)")

    lines.extend(["", "File types", "----------"])
    if report.get("file_types"):
        for index, entry in enumerate(report["file_types"], start=1):
            lines.append(_type_line(index, entry))
    else:
        lines.append("(no files found)")

    skipped_total = report.get("skipped_total", len(report["skipped"]))
    skipped_heading = f"Skipped items ({skipped_total} total)"
    lines.extend(["", skipped_heading, "-" * len(skipped_heading)])
    if report["skipped_summary"]:
        lines.append("By reason:")
        for reason, count in report["skipped_summary"].items():
            lines.append(
                f"  {count:>7}  {escape_control_characters(reason)}"
            )
    if report["skipped"]:
        lines.append("Recorded paths:")
        for entry in report["skipped"]:
            lines.append(_issue_line(entry))
    if report.get("skipped_truncated"):
        omitted = skipped_total - len(report["skipped"])
        lines.append(f"... and {omitted} more not listed")
    if skipped_total == 0:
        lines.append("(none)")

    errors_total = report.get("errors_total", len(report["errors"]))
    errors_heading = f"Errors ({errors_total} total)"
    lines.extend(["", errors_heading, "-" * len(errors_heading)])
    if report["errors_summary"]:
        lines.append("By reason:")
        for reason, count in report["errors_summary"].items():
            lines.append(
                f"  {count:>7}  {escape_control_characters(reason)}"
            )
    if report["errors"]:
        lines.append("Recorded paths:")
        for entry in report["errors"]:
            lines.append(_issue_line(entry))
    if report.get("errors_truncated"):
        omitted = errors_total - len(report["errors"])
        lines.append(f"... and {omitted} more not listed")
    if errors_total == 0:
        lines.append("(none)")

    return "\n".join(lines) + "\n"


def _ranking_line(index: int, entry: dict[str, Any]) -> str:
    """Format one line of a largest-files or largest-folders table."""
    share = entry.get("share_percent", 0.0)
    path = escape_control_characters(entry["path"])
    return f"{index:>3}. {entry['size']:>10} {share:>5.1f}%  {path}"


def _type_line(index: int, entry: dict[str, Any]) -> str:
    """Format one line of a file-type summary table."""
    share = entry.get("share_percent", 0.0)
    extension = escape_control_characters(entry["extension"])
    count = entry["file_count"]
    label = "file" if count == 1 else "files"
    return (
        f"{index:>3}. {entry['size']:>10} {share:>5.1f}%  "
        f"{extension} ({count} {label})"
    )


def _issue_line(entry: dict[str, str]) -> str:
    path = escape_control_characters(entry["path"])
    reason = escape_control_characters(entry["reason"])
    return f"- {path}: {reason}"


def _share_percent(size: int, total: int) -> float:
    return round(size / total * 100, 1) if total else 0.0


def _file_to_dict(file: FileInfo, total: int) -> dict[str, Any]:
    return {
        "path": str(file.path),
        "size_bytes": file.size,
        "size": human_readable_size(file.size),
        "share_percent": _share_percent(file.size, total),
    }


def _folder_to_dict(folder: FolderSize, total: int) -> dict[str, Any]:
    return {
        "path": str(folder.path),
        "size_bytes": folder.size,
        "size": human_readable_size(folder.size),
        "share_percent": _share_percent(folder.size, total),
    }


def _type_to_dict(item: FileTypeSummary, total: int) -> dict[str, Any]:
    return {
        "extension": item.extension,
        "size_bytes": item.size,
        "size": human_readable_size(item.size),
        "file_count": item.file_count,
        "share_percent": _share_percent(item.size, total),
    }


def _issue_to_dict(issue: ScanIssue) -> dict[str, str]:
    return {"path": str(issue.path), "reason": issue.reason}


def _write_new_file(path: Path, text: str) -> None:
    """Create ``path`` and write ``text``, refusing to overwrite.

    Opening with mode ``"x"`` is atomic, so an existing report is never
    silently replaced (the application treats user files as read-only).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(text)
    except FileExistsError as exc:
        raise FileExistsError(
            f"refusing to overwrite existing file: {path}"
        ) from exc
