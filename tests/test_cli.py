"""End-to-end tests for the command-line interface."""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from pydisk import __version__
from pydisk.cli import default_report_path, main
from pydisk.reporter import SCHEMA_VERSION
from pydisk.scanner import ScanIssue, ScanResult


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "video.mp4").write_bytes(b"v" * 500)
        (self.root / "notes.txt").write_bytes(b"n" * 50)
        (self.root / "sub").mkdir()
        (self.root / "sub" / "clip.mp4").write_bytes(b"c" * 100)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_cli(self, *arguments: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                code = main(list(arguments))
            except SystemExit as exc:
                # argparse reports usage errors by raising SystemExit(2).
                code = int(exc.code or 0)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_scan_success(self) -> None:
        code, stdout, stderr = self.run_cli("scan", str(self.root))

        self.assertEqual(code, 0, stderr)
        self.assertIn("Files        : 3", stdout)
        self.assertIn("Folders      : 1", stdout)
        self.assertIn("video.mp4", stdout)

    def test_tui_requires_an_interactive_terminal(self) -> None:
        code, stdout, stderr = self.run_cli("tui", str(self.root))

        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("interactive terminal", stderr)

    def test_scan_missing_directory(self) -> None:
        code, stdout, stderr = self.run_cli("scan", str(self.root / "missing"))

        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("error:", stderr)
        self.assertIn("does not exist", stderr)

    def test_find_requires_a_filter(self) -> None:
        code, stdout, stderr = self.run_cli("find", str(self.root))

        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("--extension", stderr)

    def test_find_by_extension(self) -> None:
        code, stdout, stderr = self.run_cli(
            "find", str(self.root), "--extension", ".mp4"
        )

        self.assertEqual(code, 0, stderr)
        self.assertIn("video.mp4", stdout)
        self.assertIn("clip.mp4", stdout)
        self.assertNotIn("notes.txt", stdout)

    def test_find_by_min_size(self) -> None:
        code, stdout, stderr = self.run_cli(
            "find", str(self.root), "--min-size", "100B"
        )

        self.assertEqual(code, 0, stderr)
        self.assertIn("video.mp4", stdout)
        self.assertIn("clip.mp4", stdout)
        self.assertNotIn("notes.txt", stdout)

    def test_find_by_max_size(self) -> None:
        code, stdout, stderr = self.run_cli(
            "find", str(self.root), "--max-size", "100B"
        )

        self.assertEqual(code, 0, stderr)
        self.assertIn("clip.mp4", stdout)
        self.assertIn("notes.txt", stdout)
        self.assertNotIn("video.mp4", stdout)

    def test_find_by_name(self) -> None:
        code, stdout, stderr = self.run_cli(
            "find", str(self.root), "--name", "*.MP4"
        )

        self.assertEqual(code, 0, stderr)
        self.assertIn("video.mp4", stdout)
        self.assertIn("clip.mp4", stdout)
        self.assertNotIn("notes.txt", stdout)

    def test_find_rejects_reversed_size_range(self) -> None:
        code, _, stderr = self.run_cli(
            "find",
            str(self.root),
            "--min-size",
            "1K",
            "--max-size",
            "100B",
        )

        self.assertEqual(code, 2)
        self.assertIn("minimum size cannot be greater", stderr)

    def test_find_rejects_invalid_size(self) -> None:
        code, stdout, stderr = self.run_cli(
            "find", str(self.root), "--min-size", "huge"
        )

        self.assertEqual(code, 2)
        self.assertIn("invalid size", stderr)

    def test_find_accepts_short_size_units(self) -> None:
        code, stdout, stderr = self.run_cli(
            "find", str(self.root), "--min-size", "1K"
        )

        self.assertEqual(code, 0, stderr)
        self.assertIn("Matches        : 0 of 3 files", stdout)

    def test_report_json(self) -> None:
        output = self.root / "out" / "report.json"

        code, stdout, stderr = self.run_cli(
            "report", str(self.root), "--format", "json", "--output", str(output)
        )

        self.assertEqual(code, 0, stderr)
        self.assertTrue(output.is_file())
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(report["file_count"], 3)
        self.assertEqual(report["folder_count"], 1)
        self.assertIn("Report written to", stdout)

    def test_report_text(self) -> None:
        output = self.root / "report.txt"

        code, _, stderr = self.run_cli(
            "report", str(self.root), "--format", "txt", "--output", str(output)
        )

        self.assertEqual(code, 0, stderr)
        self.assertIn("PyDisk Analyzer report", output.read_text(encoding="utf-8"))

    def test_report_to_stdout_as_json(self) -> None:
        code, stdout, stderr = self.run_cli("report", str(self.root), "--stdout")

        self.assertEqual(code, 0, stderr)
        report = json.loads(stdout)
        self.assertEqual(report["schema_version"], SCHEMA_VERSION)
        self.assertEqual(report["file_count"], 3)
        self.assertNotIn("Report written to", stdout)
        self.assertEqual(stderr, "")

    def test_report_output_dash_is_stdout(self) -> None:
        code, stdout, stderr = self.run_cli(
            "report", str(self.root), "--output", "-"
        )

        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["file_count"], 3)

    def test_report_to_stdout_as_text(self) -> None:
        code, stdout, stderr = self.run_cli(
            "report", str(self.root), "--format", "text", "--stdout"
        )

        self.assertEqual(code, 0, stderr)
        self.assertIn("PyDisk Analyzer report", stdout)
        self.assertIn("Largest files", stdout)

    def test_report_stdout_and_output_are_mutually_exclusive(self) -> None:
        code, stdout, stderr = self.run_cli(
            "report",
            str(self.root),
            "--stdout",
            "--output",
            str(self.root / "report.json"),
        )

        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("not allowed with argument", stderr)

    def test_report_refuses_to_overwrite(self) -> None:
        output = self.root / "report.json"
        output.write_text("keep me", encoding="utf-8")

        code, _, stderr = self.run_cli(
            "report", str(self.root), "--output", str(output)
        )

        self.assertEqual(code, 2)
        self.assertIn("refusing to overwrite", stderr)
        self.assertEqual(output.read_text(encoding="utf-8"), "keep me")

    def test_top_must_be_a_non_negative_number(self) -> None:
        code, _, stderr = self.run_cli("scan", str(self.root), "--top", "-1")

        self.assertEqual(code, 2)
        self.assertIn("zero or greater", stderr)

    def test_find_reports_how_many_matches_are_shown(self) -> None:
        code, stdout, stderr = self.run_cli(
            "find", str(self.root), "--extension", ".mp4", "--top", "1"
        )

        self.assertEqual(code, 0, stderr)
        self.assertIn("Showing        : 1 of 2 matches", stdout)

    def test_find_all_shows_every_match(self) -> None:
        code, stdout, stderr = self.run_cli(
            "find",
            str(self.root),
            "--extension",
            ".mp4",
            "--top",
            "1",
            "--all",
        )

        self.assertEqual(code, 0, stderr)
        self.assertIn("Showing        : 2 of 2 matches", stdout)
        self.assertIn("video.mp4", stdout)
        self.assertIn("clip.mp4", stdout)

    def test_scan_excludes_patterns(self) -> None:
        code, stdout, stderr = self.run_cli(
            "scan", str(self.root), "--exclude", "*.mp4"
        )

        self.assertEqual(code, 0, stderr)
        self.assertIn("Files        : 1", stdout)
        self.assertIn("notes.txt", stdout)
        # Excluded names still appear in the "Skipped items" section, but they
        # must not appear in the ranking above it.
        ranking = stdout.split("Skipped items")[0]
        self.assertNotIn("video.mp4", ranking)
        self.assertNotIn("clip.mp4", ranking)
        self.assertIn("Skipped items: 2", stdout)
        self.assertIn("excluded by pattern", stdout)

    def test_exclude_from_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            patterns = Path(temp_dir) / "exclude.txt"
            patterns.write_text(
                "# media files\n\n*.mp4\n",
                encoding="utf-8",
            )

            code, stdout, stderr = self.run_cli(
                "scan",
                str(self.root),
                "--exclude-from",
                str(patterns),
            )

        self.assertEqual(code, 0, stderr)
        self.assertIn("Files        : 1", stdout)
        self.assertIn("Excludes     : *.mp4", stdout)
        self.assertIn("notes.txt", stdout)
        self.assertIn("Skipped items: 2", stdout)

    def test_exclude_from_missing_file(self) -> None:
        code, _, stderr = self.run_cli(
            "scan",
            str(self.root),
            "--exclude-from",
            str(self.root / "missing.txt"),
        )

        self.assertEqual(code, 2)
        self.assertIn("cannot read exclude file", stderr)

    def test_progress_reports_to_a_terminal(self) -> None:
        with patch("pydisk.cli._stderr_is_tty", return_value=True):
            code, _, stderr = self.run_cli(
                "scan", str(self.root), "--progress"
            )

        self.assertEqual(code, 0, stderr)
        self.assertIn("Scanning:", stderr)
        self.assertIn("3 files", stderr)
        self.assertIn("done", stderr)

    def test_progress_is_quiet_when_stderr_is_not_a_terminal(self) -> None:
        code, _, stderr = self.run_cli("scan", str(self.root), "--progress")

        self.assertEqual(code, 0, stderr)
        self.assertEqual(stderr, "")

    def test_quiet_scan_prints_nothing(self) -> None:
        code, stdout, stderr = self.run_cli("scan", str(self.root), "--quiet")

        self.assertEqual(code, 0, stderr)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")

    def test_quiet_find_prints_nothing(self) -> None:
        code, stdout, stderr = self.run_cli(
            "find",
            str(self.root),
            "--extension",
            ".mp4",
            "--quiet",
        )

        self.assertEqual(code, 0, stderr)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")

    def test_quiet_report_suppresses_status(self) -> None:
        output = self.root / "quiet-report.json"

        code, stdout, stderr = self.run_cli(
            "report",
            str(self.root),
            "--quiet",
            "--output",
            str(output),
        )

        self.assertEqual(code, 0, stderr)
        self.assertEqual(stdout, "")
        self.assertTrue(output.is_file())

    def test_quiet_report_stdout_still_outputs_data(self) -> None:
        code, stdout, stderr = self.run_cli(
            "report", str(self.root), "--quiet", "--stdout"
        )

        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["file_count"], 3)

    def test_quiet_scan_warns_about_errors(self) -> None:
        fake_result = ScanResult(
            root=self.root,
            errors=[ScanIssue(self.root, "permission denied")],
        )

        with patch("pydisk.cli.scan_directory", return_value=fake_result):
            code, stdout, stderr = self.run_cli(
                "scan", str(self.root), "--quiet"
            )

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("warning: 1 scan errors", stderr)

    def test_quiet_suppresses_progress(self) -> None:
        with patch("pydisk.cli._stderr_is_tty", return_value=True):
            code, stdout, stderr = self.run_cli(
                "scan", str(self.root), "--quiet", "--progress"
            )

        self.assertEqual(code, 0, stderr)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")

    def test_scan_disk_usage(self) -> None:
        code, stdout, stderr = self.run_cli(
            "scan", str(self.root), "--disk-usage"
        )

        self.assertEqual(code, 0, stderr)
        self.assertIn("Size metric  : allocated disk blocks", stdout)

    def test_partial_scan_errors_return_exit_code_one(self) -> None:
        fake_result = ScanResult(
            root=self.root,
            errors=[ScanIssue(self.root, "permission denied")],
        )

        with patch("pydisk.cli.scan_directory", return_value=fake_result):
            code, _, _ = self.run_cli("scan", str(self.root))

        self.assertEqual(code, 1)

    def test_reports_default_to_unique_files(self) -> None:
        reports_dir = self.root / "reports"

        with patch("pydisk.cli.REPORT_DIR", reports_dir):
            first_code, _, first_error = self.run_cli("report", str(self.root))
            second_code, _, second_error = self.run_cli("report", str(self.root))

        self.assertEqual(first_code, 0, first_error)
        self.assertEqual(second_code, 0, second_error)
        reports = list(reports_dir.glob("pydisk-*.json"))
        self.assertEqual(len(reports), 2)
        report = json.loads(reports[0].read_text(encoding="utf-8"))
        self.assertEqual(report["schema_version"], SCHEMA_VERSION)
        self.assertEqual(report["tool_version"], __version__)

    def test_default_report_path_avoids_existing_files(self) -> None:
        class FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):  # noqa: ANN001, ANN206 - test double
                return cls(2026, 1, 1, 12, 0, 0, 123456)

        reports_dir = self.root / "reports"
        with patch("pydisk.cli.REPORT_DIR", reports_dir):
            with patch("pydisk.cli.datetime", FrozenDatetime):
                first = default_report_path(self.root, "json")
                first.parent.mkdir(parents=True)
                first.touch()
                second = default_report_path(self.root, "json")

        self.assertNotEqual(first, second)
        self.assertTrue(second.name.endswith("-2.json"))

    def test_version_flag(self) -> None:
        code, stdout, stderr = self.run_cli("--version")

        self.assertEqual(code, 0, stderr)
        self.assertIn(__version__, stdout)

    def test_legacy_main_wrapper_still_works(self) -> None:
        import main as wrapper

        self.assertTrue(callable(wrapper.main))

    def test_scan_shows_file_types(self) -> None:
        code, stdout, stderr = self.run_cli("scan", str(self.root))

        self.assertEqual(code, 0, stderr)
        self.assertIn("File types", stdout)
        self.assertIn(".mp4", stdout)
        self.assertIn(".txt", stdout)

    def test_scan_depth_groups_nested_folders(self) -> None:
        deeper = self.root / "sub" / "deeper"
        deeper.mkdir()
        (deeper / "data.bin").write_bytes(b"d" * 42)

        code, stdout, stderr = self.run_cli(
            "scan", str(self.root), "--depth", "2"
        )

        self.assertEqual(code, 0, stderr)
        self.assertIn("Folder depth : 2", stdout)
        self.assertIn("Largest folders (depth 2)", stdout)
        self.assertIn(str(deeper), stdout)

    def test_scan_control_characters_are_escaped(self) -> None:
        (self.root / "odd\nname.txt").write_bytes(b"x")

        code, stdout, stderr = self.run_cli("scan", str(self.root))

        self.assertEqual(code, 0, stderr)
        self.assertIn("odd\\nname.txt", stdout)
        self.assertNotIn("odd\nname.txt", stdout)

    def test_scan_max_skipped_limits_recorded_details(self) -> None:
        for index in range(3):
            try:
                os.symlink(
                    self.root / "missing-target",
                    self.root / f"link-{index}",
                )
            except OSError as exc:  # pragma: no cover - filesystem limitation
                self.skipTest(f"symbolic links are not supported here: {exc}")

        code, stdout, stderr = self.run_cli(
            "scan", str(self.root), "--max-skipped", "0"
        )

        self.assertEqual(code, 0, stderr)
        self.assertIn("Skipped items: 3", stdout)
        self.assertIn("... and 3 more", stdout)

    def test_scan_counts_hardlinks_only_when_asked(self) -> None:
        try:
            os.link(self.root / "video.mp4", self.root / "video-copy.mp4")
        except OSError as exc:  # pragma: no cover - filesystem limitation
            self.skipTest(f"hard links are not supported here: {exc}")

        default_code, default_output, default_error = self.run_cli(
            "scan", str(self.root)
        )
        all_code, all_output, all_error = self.run_cli(
            "scan", str(self.root), "--count-hardlinks"
        )

        self.assertEqual(default_code, 0, default_error)
        self.assertEqual(all_code, 0, all_error)
        self.assertIn("Files        : 3", default_output)
        self.assertIn("Files        : 4", all_output)

    def test_report_format_text_alias(self) -> None:
        output = self.root / "report.txt"

        code, _, stderr = self.run_cli(
            "report", str(self.root), "--format", "text", "--output", str(output)
        )

        self.assertEqual(code, 0, stderr)
        self.assertTrue(output.is_file())
        self.assertIn("PyDisk Analyzer report", output.read_text(encoding="utf-8"))

    def test_broken_pipe_exits_cleanly(self) -> None:
        fake_result = ScanResult(root=self.root)

        with patch("pydisk.cli.scan_directory", return_value=fake_result):
            with patch("builtins.print", side_effect=BrokenPipeError):
                code, _, stderr = self.run_cli("scan", str(self.root))

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")

    def test_python_dash_m_pydisk(self) -> None:
        project_root = Path(__file__).resolve().parent.parent

        completed = subprocess.run(
            [sys.executable, "-m", "pydisk", "--version"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(__version__, completed.stdout)


if __name__ == "__main__":
    unittest.main()
