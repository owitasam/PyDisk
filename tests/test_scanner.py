"""Tests for the directory scanner."""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydisk.scanner import scan_directory


class _FakeEntry:
    """Minimal stand-in for os.DirEntry used by the one-file-system test."""

    def __init__(self, path: Path, mode: int, device: int) -> None:
        self.path = str(path)
        self._stat = os.stat_result(
            (mode, 1, device, 2, 0, 0, 0, 0, 0, 0)
        )

    def is_symlink(self) -> bool:
        return False

    def stat(self, follow_symlinks: bool = False) -> os.stat_result:
        return self._stat


class _FakeScandir:
    def __init__(self, entries: list[_FakeEntry]) -> None:
        self._entries = entries

    def __enter__(self) -> object:
        return iter(self._entries)

    def __exit__(self, *args: object) -> bool:
        return False


class ScannerTests(unittest.TestCase):
    """Scanning behaviour using throw-away temporary directories."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def create_file(self, relative_path: str, size: int) -> Path:
        """Create a file of exactly ``size`` bytes inside the temp root."""
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
        return path

    def test_empty_directory(self) -> None:
        result = scan_directory(self.root)

        self.assertEqual(result.root, self.root.resolve())
        self.assertEqual(result.file_count, 0)
        self.assertEqual(result.directory_count, 0)
        self.assertEqual(result.total_size, 0)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.skipped, [])

    def test_multiple_files_and_total_size(self) -> None:
        self.create_file("one.bin", 10)
        self.create_file("two.bin", 20)
        self.create_file("three.bin", 30)

        result = scan_directory(self.root)

        self.assertEqual(result.file_count, 3)
        self.assertEqual(result.directory_count, 0)
        self.assertEqual(result.total_size, 60)
        self.assertEqual(
            sorted(file.path.name for file in result.files),
            ["one.bin", "three.bin", "two.bin"],
        )

    def test_nested_folders(self) -> None:
        self.create_file("a/b/c/deep.txt", 7)
        self.create_file("a/shallow.txt", 3)
        self.create_file("top.txt", 5)

        result = scan_directory(self.root)

        self.assertEqual(result.file_count, 3)
        self.assertEqual(result.directory_count, 3)
        self.assertEqual(result.total_size, 15)

    def test_missing_directory_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            scan_directory(self.root / "does-not-exist")

    def test_file_instead_of_directory_raises(self) -> None:
        file_path = self.create_file("plain.txt", 4)

        with self.assertRaises(NotADirectoryError):
            scan_directory(file_path)

    def test_unusual_file_names(self) -> None:
        names = [
            "file with spaces.txt",
            "üñïçødé-📁.bin",
            "weird$name&[1].txt",
            "-leading-dash",
        ]
        for name in names:
            self.create_file(name, 1)

        result = scan_directory(self.root)

        self.assertEqual(
            sorted(file.path.name for file in result.files),
            sorted(names),
        )

    def test_symbolic_links_are_not_followed(self) -> None:
        self.create_file("real.txt", 4)
        self.create_file("real_dir/inner.txt", 3)

        try:
            os.symlink(self.root / "real.txt", self.root / "link.txt")
            os.symlink(self.root / "real_dir", self.root / "link_dir")
            os.symlink(self.root, self.root / "loop")
        except OSError as exc:  # pragma: no cover - filesystem limitation
            self.skipTest(f"symbolic links are not supported here: {exc}")

        result = scan_directory(self.root)

        # The real file and real directory are counted exactly once.
        self.assertEqual(result.file_count, 2)
        self.assertEqual(result.directory_count, 1)
        self.assertEqual(result.total_size, 7)
        self.assertEqual(len(result.skipped), 3)
        self.assertTrue(
            all("symbolic link" in issue.reason for issue in result.skipped)
        )

    @unittest.skipUnless(
        hasattr(os, "geteuid") and os.geteuid() != 0,
        "permission checks do not apply to root",
    )
    def test_inaccessible_directory_is_reported(self) -> None:
        blocked = self.root / "blocked"
        blocked.mkdir()
        os.chmod(blocked, 0o000)
        try:
            result = scan_directory(self.root)
        finally:
            os.chmod(blocked, 0o700)

        self.assertEqual(result.directory_count, 1)
        self.assertEqual(result.file_count, 0)
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.errors[0].path, blocked)
        self.assertEqual(result.errors[0].reason, "permission denied")

    def test_hard_links_are_counted_once_by_default(self) -> None:
        original = self.create_file("original.bin", 10)
        try:
            os.link(original, self.root / "copy.bin")
        except OSError as exc:  # pragma: no cover - filesystem limitation
            self.skipTest(f"hard links are not supported here: {exc}")

        once = scan_directory(self.root)
        self.assertEqual(once.file_count, 1)
        self.assertEqual(once.total_size, 10)
        self.assertTrue(
            any("hard link" in issue.reason for issue in once.skipped)
        )

        twice = scan_directory(self.root, count_hardlinks=True)
        self.assertEqual(twice.file_count, 2)
        self.assertEqual(twice.total_size, 20)
        self.assertTrue(twice.count_hardlinks)

    def test_disk_usage_uses_allocated_blocks(self) -> None:
        sparse = self.root / "sparse.bin"
        with sparse.open("wb") as handle:
            handle.truncate(4 * 1024 * 1024)

        apparent = scan_directory(self.root)
        allocated = scan_directory(self.root, disk_usage=True)

        self.assertGreaterEqual(apparent.total_size, 4 * 1024 * 1024)
        self.assertLessEqual(allocated.total_size, apparent.total_size)
        self.assertFalse(apparent.disk_usage)
        self.assertTrue(allocated.disk_usage)

    def test_exclude_patterns_match_names_and_paths(self) -> None:
        self.create_file("keep.txt", 5)
        self.create_file("skip.log", 5)
        self.create_file("node_modules/pkg/index.js", 5)

        result = scan_directory(
            self.root,
            excludes=["*.log", "node_modules"],
        )

        self.assertEqual(result.file_count, 1)
        self.assertEqual(result.total_size, 5)
        self.assertEqual(result.directory_count, 0)
        self.assertEqual(result.excludes, ("*.log", "node_modules"))
        self.assertEqual(len(result.skipped), 2)
        reasons = [issue.reason for issue in result.skipped]
        self.assertTrue(any("*.log" in reason for reason in reasons))
        self.assertTrue(any("node_modules" in reason for reason in reasons))

    def test_exclude_patterns_can_use_relative_paths(self) -> None:
        self.create_file("a/b/drop.bin", 5)
        self.create_file("a/b/c/keep.bin", 7)

        result = scan_directory(self.root, excludes=["a/b/*.bin"])

        self.assertEqual(
            [file.path.name for file in result.files],
            ["keep.bin"],
        )
        self.assertEqual(result.total_size, 7)

    def test_one_file_system_on_the_same_device_is_a_no_op(self) -> None:
        self.create_file("inside.bin", 5)

        result = scan_directory(self.root, one_file_system=True)

        self.assertEqual(result.file_count, 1)
        self.assertTrue(result.one_file_system)

    def test_one_file_system_skips_other_devices(self) -> None:
        root_device = self.root.stat().st_dev
        mount_point = self.root / "mnt"
        entry = _FakeEntry(
            mount_point,
            stat.S_IFDIR | 0o755,
            root_device + 1,
        )

        def fake_scandir(path: str | Path) -> _FakeScandir:
            if Path(path) == self.root:
                return _FakeScandir([entry])
            return _FakeScandir([])

        with patch("pydisk.scanner.os.scandir", side_effect=fake_scandir):
            normal = scan_directory(self.root)
            isolated = scan_directory(self.root, one_file_system=True)

        self.assertEqual(normal.directory_count, 1)
        self.assertEqual(isolated.directory_count, 0)
        self.assertEqual(isolated.skipped_count, 1)
        self.assertIn("different filesystem", isolated.skipped[0].reason)

    def test_progress_callback_receives_start_and_final_counts(self) -> None:
        self.create_file("a.bin", 5)
        self.create_file("sub/b.bin", 7)
        updates = []

        scan_directory(self.root, progress=updates.append)

        self.assertGreaterEqual(len(updates), 2)
        self.assertEqual(updates[0].files, 0)
        self.assertEqual(updates[-1].files, 2)
        self.assertEqual(updates[-1].directories, 1)
        self.assertEqual(updates[-1].skipped, 0)
        self.assertEqual(updates[-1].errors, 0)
        self.assertEqual(updates[-1].current_path, self.root)

    def test_streaming_mode_does_not_store_file_list(self) -> None:
        self.create_file("a.bin", 5)
        self.create_file("sub/b.bin", 7)
        seen = []

        result = scan_directory(
            self.root,
            collect_files=False,
            file_callback=seen.append,
        )

        self.assertEqual(result.files, [])
        self.assertEqual(result.file_count, 2)
        self.assertEqual(result.total_size, 12)
        self.assertEqual(
            sorted(file.path.name for file in seen),
            ["a.bin", "b.bin"],
        )

    def test_skipped_details_can_be_capped(self) -> None:
        for index in range(5):
            try:
                os.symlink(
                    self.root / "missing-target",
                    self.root / f"link-{index}",
                )
            except OSError as exc:  # pragma: no cover - filesystem limitation
                self.skipTest(f"symbolic links are not supported here: {exc}")

        result = scan_directory(self.root, max_skipped=2)

        self.assertEqual(len(result.skipped), 2)
        self.assertEqual(result.skipped_count, 5)
        self.assertEqual(
            result.skipped_summary,
            {"symbolic link (not followed)": 5},
        )

    @unittest.skipUnless(
        hasattr(os, "geteuid") and os.geteuid() != 0,
        "permission checks do not apply to root",
    )
    def test_error_details_can_be_capped(self) -> None:
        blocked = []
        for index in range(3):
            path = self.root / f"blocked-{index}"
            path.mkdir()
            os.chmod(path, 0o000)
            blocked.append(path)

        try:
            result = scan_directory(self.root, max_errors=1)
        finally:
            for path in blocked:
                os.chmod(path, 0o700)

        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.error_count, 3)
        self.assertEqual(result.errors_summary, {"permission denied": 3})

    def test_negative_issue_limits_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            scan_directory(self.root, max_skipped=-1)
        with self.assertRaises(ValueError):
            scan_directory(self.root, max_errors=-1)

    def test_scanning_does_not_modify_files(self) -> None:
        path = self.create_file("precious.bin", 123)
        before = (
            hashlib.sha256(path.read_bytes()).hexdigest(),
            path.stat().st_mtime_ns,
        )

        scan_directory(self.root)

        after = (
            hashlib.sha256(path.read_bytes()).hexdigest(),
            path.stat().st_mtime_ns,
        )
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
