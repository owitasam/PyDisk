"""Optional SQLite index for scans that should not be held in memory.

The normal ``scan``, ``find`` and ``report`` commands keep every file in a
Python list. That is convenient but uses a lot of RAM for enormous directory
trees. The ``index`` command uses the same scanner with ``collect_files=False``
and streams each file into a new SQLite database instead.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from . import __version__
from .scanner import FileInfo, ScanResult

INDEX_SCHEMA_VERSION = 1
BATCH_SIZE = 1000

_SCHEMA = """
CREATE TABLE scan (
    id INTEGER PRIMARY KEY,
    root TEXT NOT NULL,
    scanned_at TEXT NOT NULL,
    tool_version TEXT NOT NULL,
    total_size_bytes INTEGER NOT NULL,
    file_count INTEGER NOT NULL,
    folder_count INTEGER NOT NULL,
    skipped_total INTEGER NOT NULL,
    errors_total INTEGER NOT NULL,
    disk_usage INTEGER NOT NULL,
    one_file_system INTEGER NOT NULL,
    count_hardlinks INTEGER NOT NULL,
    excludes TEXT NOT NULL,
    skipped_summary TEXT NOT NULL,
    errors_summary TEXT NOT NULL
);

CREATE TABLE files (
    scan_id INTEGER NOT NULL,
    path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL
);

CREATE INDEX files_by_size ON files (scan_id, size_bytes DESC);
CREATE INDEX files_by_path ON files (scan_id, path);

CREATE TABLE skipped (
    scan_id INTEGER NOT NULL,
    path TEXT NOT NULL,
    reason TEXT NOT NULL
);

CREATE TABLE errors (
    scan_id INTEGER NOT NULL,
    path TEXT NOT NULL,
    reason TEXT NOT NULL
);
"""


class IndexWriter:
    """Create a SQLite index and receive files as they are scanned."""

    def __init__(self, database: str | Path) -> None:
        self.path = Path(database).expanduser()
        if self.path.exists():
            raise FileExistsError(
                f"refusing to overwrite existing index: {self.path}"
            )

        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.connection = sqlite3.connect(self.path)
        except sqlite3.Error as exc:
            raise OSError(
                f"cannot create index {self.path}: {exc}"
            ) from exc

        try:
            self.connection.executescript(_SCHEMA)
            self.connection.execute(
                f"PRAGMA user_version = {INDEX_SCHEMA_VERSION}"
            )
            self.connection.commit()
        except sqlite3.Error as exc:
            self.connection.close()
            self.path.unlink(missing_ok=True)
            raise OSError(
                f"cannot initialize index {self.path}: {exc}"
            ) from exc
        except BaseException:
            self.connection.close()
            self.path.unlink(missing_ok=True)
            raise

        self._batch: list[tuple[str, int]] = []

    def add_file(self, file: FileInfo) -> None:
        """Buffer one file row and flush it in reasonably sized batches."""
        self._batch.append((str(file.path), file.size))
        if len(self._batch) >= BATCH_SIZE:
            self._flush()

    def finish(self, result: ScanResult) -> None:
        """Write metadata, issues and the remaining file rows."""
        self._flush()

        if result.skipped:
            self.connection.executemany(
                "INSERT INTO skipped (scan_id, path, reason) "
                "VALUES (1, ?, ?)",
                [
                    (str(issue.path), issue.reason)
                    for issue in result.skipped
                ],
            )
        if result.errors:
            self.connection.executemany(
                "INSERT INTO errors (scan_id, path, reason) "
                "VALUES (1, ?, ?)",
                [
                    (str(issue.path), issue.reason)
                    for issue in result.errors
                ],
            )

        scanned_at = datetime.now().astimezone().isoformat(timespec="seconds")
        self.connection.execute(
            """
            INSERT INTO scan (
                id, root, scanned_at, tool_version, total_size_bytes,
                file_count, folder_count, skipped_total, errors_total,
                disk_usage, one_file_system, count_hardlinks, excludes,
                skipped_summary, errors_summary
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(result.root),
                scanned_at,
                __version__,
                result.total_size,
                result.file_count,
                result.directory_count,
                result.skipped_count,
                result.error_count,
                int(result.disk_usage),
                int(result.one_file_system),
                int(result.count_hardlinks),
                json.dumps(list(result.excludes)),
                json.dumps(result.skipped_summary),
                json.dumps(result.errors_summary),
            ),
        )
        self.connection.commit()

    def close(self) -> None:
        """Close the database after a successful scan."""
        self.connection.close()

    def abort(self) -> None:
        """Close and remove a partially written index."""
        try:
            self.connection.rollback()
        except sqlite3.Error:
            pass
        self.connection.close()
        self.path.unlink(missing_ok=True)

    def _flush(self) -> None:
        if not self._batch:
            return
        self.connection.executemany(
            "INSERT INTO files (scan_id, path, size_bytes) VALUES (1, ?, ?)",
            self._batch,
        )
        self._batch.clear()
