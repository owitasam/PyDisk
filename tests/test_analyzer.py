"""Tests for filtering and ranking helpers."""

from __future__ import annotations

import unittest
from pathlib import Path

from pydisk.analyzer import (
    file_type_summary,
    find_files,
    largest_files,
    largest_folders,
    normalize_extension,
)
from pydisk.scanner import FileInfo, ScanResult


def make_file(path: str, size: int) -> FileInfo:
    return FileInfo(path=Path(path), size=size)


class LargestFilesTests(unittest.TestCase):
    def test_sorted_descending_with_limit(self) -> None:
        files = [
            make_file("/scan/small.bin", 10),
            make_file("/scan/large.bin", 100),
            make_file("/scan/medium.bin", 50),
        ]

        result = largest_files(files, limit=2)

        self.assertEqual(
            [file.path.name for file in result],
            ["large.bin", "medium.bin"],
        )

    def test_zero_limit(self) -> None:
        self.assertEqual(largest_files([make_file("/scan/a", 1)], limit=0), [])

    def test_negative_limit_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            largest_files([], limit=-1)


class ExtensionTests(unittest.TestCase):
    def test_normalize_extension(self) -> None:
        self.assertEqual(normalize_extension(".MP4"), ".mp4")
        self.assertEqual(normalize_extension("mp4"), ".mp4")
        self.assertEqual(normalize_extension("*.mp4"), ".mp4")
        self.assertEqual(normalize_extension(" .TAR.GZ "), ".tar.gz")

    def test_empty_extension_is_rejected(self) -> None:
        for value in ["", ".", "   "]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_extension(value)


class FindFilesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.files = [
            make_file("/scan/video.MP4", 500),
            make_file("/scan/archive.tar.gz", 300),
            make_file("/scan/notes.txt", 50),
            make_file("/scan/big.txt", 2000),
        ]

    def test_extension_is_case_insensitive(self) -> None:
        matches = find_files(self.files, extension=".mp4")
        self.assertEqual([file.path.name for file in matches], ["video.MP4"])

    def test_compound_extension(self) -> None:
        matches = find_files(self.files, extension=".tar.gz")
        self.assertEqual([file.path.name for file in matches], ["archive.tar.gz"])

    def test_min_size_is_inclusive(self) -> None:
        matches = find_files(self.files, min_size=300)
        self.assertEqual(
            sorted(file.path.name for file in matches),
            ["archive.tar.gz", "big.txt", "video.MP4"],
        )

    def test_max_size_is_inclusive(self) -> None:
        matches = find_files(self.files, max_size=500)
        self.assertEqual(
            sorted(file.path.name for file in matches),
            ["archive.tar.gz", "notes.txt", "video.MP4"],
        )

    def test_size_range(self) -> None:
        matches = find_files(self.files, min_size=300, max_size=500)
        self.assertEqual(
            sorted(file.path.name for file in matches),
            ["archive.tar.gz", "video.MP4"],
        )

    def test_name_pattern_is_case_insensitive(self) -> None:
        self.assertEqual(
            [file.path.name for file in find_files(self.files, name="*.mp4")],
            ["video.MP4"],
        )
        self.assertEqual(
            [file.path.name for file in find_files(self.files, name="BIG*")],
            ["big.txt"],
        )

    def test_combined_filters(self) -> None:
        matches = find_files(self.files, extension=".txt", min_size=100)
        self.assertEqual([file.path.name for file in matches], ["big.txt"])

    def test_no_filters_returns_everything(self) -> None:
        self.assertEqual(len(find_files(self.files)), 4)

    def test_reversed_size_range_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            find_files(self.files, min_size=500, max_size=100)

    def test_negative_max_size_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            find_files(self.files, max_size=-1)

    def test_empty_name_pattern_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            find_files(self.files, name="   ")


class LargestFoldersTests(unittest.TestCase):
    def test_immediate_subdirectories_are_summed(self) -> None:
        result = ScanResult(
            root=Path("/scan"),
            files=[
                make_file("/scan/a/one.bin", 100),
                make_file("/scan/b/two.bin", 50),
                make_file("/scan/b/three.bin", 25),
                make_file("/scan/root-file.bin", 999),
                make_file("/scan/a/deep/four.bin", 10),
            ],
            directory_count=3,
        )

        folders = largest_folders(result, limit=10)

        self.assertEqual(
            [(folder.path, folder.size) for folder in folders],
            [(Path("/scan/a"), 110), (Path("/scan/b"), 75)],
        )

    def test_limit(self) -> None:
        result = ScanResult(
            root=Path("/scan"),
            files=[
                make_file("/scan/a/x.bin", 100),
                make_file("/scan/b/x.bin", 50),
            ],
        )

        self.assertEqual(len(largest_folders(result, limit=1)), 1)

    def test_no_subdirectories(self) -> None:
        result = ScanResult(
            root=Path("/scan"),
            files=[make_file("/scan/top.bin", 12)],
        )

        self.assertEqual(largest_folders(result), [])

    def test_depth_two_groups_nested_folders(self) -> None:
        result = ScanResult(
            root=Path("/scan"),
            files=[
                make_file("/scan/a/one.bin", 100),
                make_file("/scan/b/two.bin", 50),
                make_file("/scan/b/three.bin", 25),
                make_file("/scan/root-file.bin", 999),
                make_file("/scan/a/deep/four.bin", 10),
            ],
            directory_count=3,
        )

        folders = largest_folders(result, depth=2)

        self.assertEqual(
            [(folder.path, folder.size) for folder in folders],
            [
                (Path("/scan/a"), 100),
                (Path("/scan/b"), 75),
                (Path("/scan/a/deep"), 10),
            ],
        )

    def test_depth_must_be_at_least_one(self) -> None:
        result = ScanResult(root=Path("/scan"))

        with self.assertRaises(ValueError):
            largest_folders(result, depth=0)


class FileTypeSummaryTests(unittest.TestCase):
    def test_summary_is_grouped_and_sorted(self) -> None:
        files = [
            make_file("/scan/video.MP4", 500),
            make_file("/scan/photo.JPG", 2000),
            make_file("/scan/notes.txt", 50),
            make_file("/scan/readme", 10),
        ]

        summary = file_type_summary(files)

        self.assertEqual(
            [(item.extension, item.size, item.file_count) for item in summary],
            [
                (".jpg", 2000, 1),
                (".mp4", 500, 1),
                (".txt", 50, 1),
                ("(no extension)", 10, 1),
            ],
        )

    def test_limit(self) -> None:
        files = [
            make_file("/scan/a.mp4", 100),
            make_file("/scan/b.txt", 50),
        ]

        summary = file_type_summary(files, limit=1)

        self.assertEqual(len(summary), 1)
        self.assertEqual(summary[0].extension, ".mp4")

    def test_negative_limit_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            file_type_summary([], limit=-1)


if __name__ == "__main__":
    unittest.main()
