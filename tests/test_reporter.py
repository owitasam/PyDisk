"""Tests for report building and export."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pydisk import __version__
from pydisk.reporter import (
    SCHEMA_VERSION,
    build_report,
    format_json_report,
    format_text_report,
    write_json_report,
    write_text_report,
)
from pydisk.scanner import FileInfo, ScanIssue, ScanResult


class ReporterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.temp_dir.name)
        self.result = ScanResult(
            root=Path("/example/data"),
            files=[
                FileInfo(Path("/example/data/big.bin"), 2048),
                FileInfo(Path("/example/data/small.txt"), 10),
            ],
            directory_count=1,
            errors=[ScanIssue(Path("/example/data/secret"), "permission denied")],
            skipped=[ScanIssue(Path("/example/data/link"), "symbolic link")],
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_build_report_contains_required_fields(self) -> None:
        report = build_report(self.result, top=5)

        self.assertEqual(report["scan_location"], "/example/data")
        self.assertEqual(report["total_size_bytes"], 2058)
        self.assertEqual(report["total_size"], "2.0 KB")
        self.assertEqual(report["file_count"], 2)
        self.assertEqual(report["folder_count"], 1)
        self.assertEqual(len(report["largest_files"]), 2)
        self.assertIn("scanned_at", report)
        self.assertEqual(report["schema_version"], SCHEMA_VERSION)
        self.assertEqual(report["tool_version"], __version__)
        self.assertEqual(report["scan_options"]["size_metric"], "apparent")
        self.assertEqual(report["scan_options"]["folder_depth"], 1)
        self.assertEqual(report["errors"][0]["reason"], "permission denied")
        self.assertEqual(report["errors_total"], 1)
        self.assertEqual(report["errors_summary"], {"permission denied": 1})
        self.assertFalse(report["errors_truncated"])
        self.assertEqual(report["skipped"][0]["reason"], "symbolic link")
        self.assertEqual(report["skipped_total"], 1)
        self.assertEqual(report["skipped_summary"], {"symbolic link": 1})
        self.assertFalse(report["skipped_truncated"])
        self.assertEqual(report["largest_files"][0]["share_percent"], 99.5)
        self.assertEqual(report["file_types"][0]["extension"], ".bin")
        self.assertEqual(report["file_types"][0]["size_bytes"], 2048)

    def test_build_report_respects_top(self) -> None:
        report = build_report(self.result, top=1)

        self.assertEqual(len(report["largest_files"]), 1)
        self.assertEqual(report["largest_files"][0]["size_bytes"], 2048)

    def test_skipped_items_are_capped_and_summarized(self) -> None:
        result = ScanResult(
            root=Path("/example/many"),
            skipped=[
                ScanIssue(Path(f"/example/many/link-{index}"), "symbolic link")
                for index in range(250)
            ]
            + [
                ScanIssue(Path("/example/many/pipe"), "not a regular file")
                for _ in range(5)
            ],
        )

        report = build_report(result, max_skipped=10)

        self.assertEqual(report["skipped_total"], 255)
        self.assertEqual(len(report["skipped"]), 10)
        self.assertTrue(report["skipped_truncated"])
        self.assertEqual(report["skipped_summary"]["symbolic link"], 250)
        self.assertEqual(report["skipped_summary"]["not a regular file"], 5)
        self.assertIn("... and 245 more not listed", format_text_report(report))

    def test_errors_are_capped_and_summarized(self) -> None:
        result = ScanResult(
            root=Path("/example/broken"),
            errors=[
                ScanIssue(Path(f"/example/broken/secret-{index}"), "permission denied")
                for index in range(5)
            ],
        )

        report = build_report(result, max_errors=2)
        text = format_text_report(report)

        self.assertEqual(report["errors_total"], 5)
        self.assertEqual(len(report["errors"]), 2)
        self.assertTrue(report["errors_truncated"])
        self.assertEqual(report["errors_summary"], {"permission denied": 5})
        self.assertIn("Errors (5 total)", text)
        self.assertIn("... and 3 more not listed", text)

    def test_report_includes_folder_depth(self) -> None:
        result = ScanResult(
            root=Path("/example/tree"),
            files=[
                FileInfo(Path("/example/tree/a/b/file.bin"), 100),
            ],
        )

        report = build_report(result, depth=2)
        text = format_text_report(report)

        self.assertEqual(report["scan_options"]["folder_depth"], 2)
        self.assertIn("Folder depth  : 2", text)
        self.assertIn("/example/tree/a/b", text)

    def test_text_report_escapes_control_characters(self) -> None:
        result = ScanResult(
            root=Path("/example/data"),
            files=[
                FileInfo(Path("/example/data/line\nbreak.txt"), 10),
            ],
            skipped=[
                ScanIssue(
                    Path("/example/data/tab\tname"),
                    "symbolic link\nnot followed",
                )
            ],
        )

        text = format_text_report(build_report(result))

        self.assertIn("line\\nbreak.txt", text)
        self.assertIn("tab\\tname", text)
        self.assertIn("symbolic link\\nnot followed", text)

    def test_format_json_report_is_parseable_and_ends_with_newline(self) -> None:
        text = format_json_report(build_report(self.result))

        self.assertTrue(text.endswith("\n"))
        self.assertEqual(json.loads(text)["file_count"], 2)

    def test_zero_total_has_zero_share(self) -> None:
        empty = ScanResult(
            root=Path("/example/zero"),
            files=[FileInfo(Path("/example/zero/empty"), 0)],
        )

        report = build_report(empty)

        self.assertEqual(report["largest_files"][0]["share_percent"], 0.0)
        self.assertEqual(report["total_size"], "0 B")

    def test_text_report_mentions_disk_usage_metric(self) -> None:
        result = ScanResult(root=Path("/example/disk"), disk_usage=True)
        text = format_text_report(build_report(result))

        self.assertIn("Size metric   : allocated disk blocks", text)

    def test_write_json_report_round_trip(self) -> None:
        report = build_report(self.result)
        output = self.output_dir / "nested" / "report.json"

        returned = write_json_report(report, output)

        self.assertEqual(returned, output)
        loaded = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(loaded["file_count"], 2)
        self.assertEqual(loaded["largest_files"][0]["size"], "2.0 KB")

    def test_write_text_report(self) -> None:
        report = build_report(self.result)
        output = self.output_dir / "report.txt"

        write_text_report(report, output)

        text = output.read_text(encoding="utf-8")
        self.assertIn("PyDisk Analyzer report", text)
        self.assertIn("Scan location : /example/data", text)
        self.assertIn("big.bin", text)
        self.assertIn("permission denied", text)

    def test_text_report_handles_empty_results(self) -> None:
        empty = ScanResult(root=Path("/example/empty"))
        text = format_text_report(build_report(empty))

        self.assertIn("(no files found)", text)
        self.assertIn("(no subdirectories with files)", text)
        self.assertIn("(none)", text)

    def test_writer_refuses_to_overwrite(self) -> None:
        output = self.output_dir / "report.json"
        output.write_text("keep me", encoding="utf-8")

        with self.assertRaises(FileExistsError):
            write_json_report(build_report(self.result), output)

        self.assertEqual(output.read_text(encoding="utf-8"), "keep me")


if __name__ == "__main__":
    unittest.main()
