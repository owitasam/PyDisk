"""End-to-end tests for the SQLite index command."""

from __future__ import annotations

import contextlib
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pydisk.cli import main


class IndexCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tree_temp = tempfile.TemporaryDirectory()
        self.db_temp = tempfile.TemporaryDirectory()
        self.root = Path(self.tree_temp.name)
        self.database = Path(self.db_temp.name) / "index.db"
        (self.root / "video.mp4").write_bytes(b"v" * 500)
        (self.root / "notes.txt").write_bytes(b"n" * 50)
        (self.root / "sub").mkdir()
        (self.root / "sub" / "clip.mp4").write_bytes(b"c" * 100)

    def tearDown(self) -> None:
        self.tree_temp.cleanup()
        self.db_temp.cleanup()

    def run_cli(self, *arguments: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                code = main(list(arguments))
            except SystemExit as exc:
                code = int(exc.code or 0)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_index_creates_a_queryable_database(self) -> None:
        code, stdout, stderr = self.run_cli(
            "index",
            str(self.root),
            "--database",
            str(self.database),
        )

        self.assertEqual(code, 0, stderr)
        self.assertTrue(self.database.is_file())
        self.assertIn("Index written to", stdout)

        with contextlib.closing(sqlite3.connect(self.database)) as connection:
            file_count, total_size = connection.execute(
                "SELECT file_count, total_size_bytes FROM scan"
            ).fetchone()
            top_path, top_size = connection.execute(
                "SELECT path, size_bytes FROM files "
                "ORDER BY size_bytes DESC LIMIT 1"
            ).fetchone()
            schema_version = connection.execute(
                "PRAGMA user_version"
            ).fetchone()[0]

        self.assertEqual(file_count, 3)
        self.assertEqual(total_size, 650)
        self.assertEqual(Path(top_path), self.root / "video.mp4")
        self.assertEqual(top_size, 500)
        self.assertEqual(schema_version, 1)

    def test_index_refuses_to_overwrite_existing_database(self) -> None:
        self.database.write_text("keep me", encoding="utf-8")

        code, _, stderr = self.run_cli(
            "index",
            str(self.root),
            "--database",
            str(self.database),
        )

        self.assertEqual(code, 2)
        self.assertIn("refusing to overwrite", stderr)
        self.assertEqual(
            self.database.read_text(encoding="utf-8"),
            "keep me",
        )

    def test_index_records_excluded_and_skipped_items(self) -> None:
        (self.root / "skip.log").write_bytes(b"log")

        code, _, stderr = self.run_cli(
            "index",
            str(self.root),
            "--database",
            str(self.database),
            "--exclude",
            "*.log",
        )

        self.assertEqual(code, 0, stderr)
        with contextlib.closing(sqlite3.connect(self.database)) as connection:
            skipped = connection.execute(
                "SELECT path, reason FROM skipped"
            ).fetchall()
            summary = connection.execute(
                "SELECT skipped_summary FROM scan"
            ).fetchone()[0]

        self.assertEqual(len(skipped), 1)
        self.assertTrue(skipped[0][0].endswith("skip.log"))
        self.assertIn("excluded by pattern", skipped[0][1])
        self.assertIn("*.log", summary)

    def test_index_quiet_mode_is_silent(self) -> None:
        code, stdout, stderr = self.run_cli(
            "index",
            str(self.root),
            "--database",
            str(self.database),
            "--quiet",
        )

        self.assertEqual(code, 0, stderr)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        self.assertTrue(self.database.is_file())

    def test_failed_index_removes_partial_database(self) -> None:
        code, _, stderr = self.run_cli(
            "index",
            str(self.root / "missing"),
            "--database",
            str(self.database),
        )

        self.assertEqual(code, 2)
        self.assertIn("does not exist", stderr)
        self.assertFalse(self.database.exists())


if __name__ == "__main__":
    unittest.main()
