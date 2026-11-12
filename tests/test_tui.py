"""Tests for the terminal UI model and rendering helpers."""

from __future__ import annotations

import curses
import tempfile
import unittest
from pathlib import Path

from pydisk.scanner import scan_directory
from pydisk.tui import SORT_MODES, TuiApp, TuiModel


class FakeScreen:
    """Small stand-in for a curses window used by rendering tests."""

    def __init__(self, height: int = 12, width: int = 80) -> None:
        self.height = height
        self.width = width
        self.writes: list[tuple[int, int, str, int]] = []

    def getmaxyx(self) -> tuple[int, int]:
        return self.height, self.width

    def erase(self) -> None:
        self.writes.clear()

    def addnstr(
        self,
        y: int,
        x: int,
        text: str,
        length: int,
        attribute: int = 0,
    ) -> None:
        self.writes.append((y, x, text[:length], attribute))

    def refresh(self) -> None:
        return None


class TuiModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "alpha").mkdir()
        (self.root / "alpha" / "a.txt").write_bytes(b"a" * 20)
        (self.root / "alpha" / "nested").mkdir()
        (self.root / "alpha" / "nested" / "b.bin").write_bytes(b"b" * 30)
        (self.root / "z_big.txt").write_bytes(b"z" * 40)
        (self.root / "a_small.txt").write_bytes(b"s" * 5)
        self.result = scan_directory(self.root)
        self.model = TuiModel(self.result)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def names(self) -> list[str]:
        return [entry.name for entry in self.model.visible_entries()]

    def test_root_summary_and_size_sorting(self) -> None:
        self.assertEqual(self.model.current_path, self.root.resolve())
        self.assertEqual(self.model.current_size, 95)
        self.assertEqual(self.model.current_file_count, 4)
        self.assertEqual(self.model.current_share, 100.0)
        self.assertEqual(self.names(), ["alpha", "z_big.txt", "a_small.txt"])

        alpha = self.model.visible_entries()[0]
        self.assertTrue(alpha.is_dir)
        self.assertEqual(alpha.size, 50)
        self.assertEqual(alpha.file_count, 2)

    def test_enter_and_go_up_restore_parent_selection(self) -> None:
        self.assertTrue(self.model.enter())
        self.assertEqual(self.model.current_path, self.root.resolve() / "alpha")
        self.assertEqual(self.model.current_size, 50)
        self.assertEqual(self.model.current_file_count, 2)
        self.assertEqual(self.names(), ["nested", "a.txt"])
        self.assertAlmostEqual(self.model.current_share, 50 / 95 * 100)

        self.assertTrue(self.model.go_up())
        self.assertEqual(self.model.current_path, self.root.resolve())
        self.assertEqual(self.model.selected_entry().name, "alpha")

    def test_enter_on_a_file_does_nothing(self) -> None:
        self.model.select_index(1)
        self.assertEqual(self.model.selected_entry().name, "z_big.txt")
        self.assertFalse(self.model.enter())
        self.assertEqual(self.model.current_path, self.root.resolve())

    def test_name_sort_uses_names_and_keeps_directories_first(self) -> None:
        self.model.cycle_sort()
        self.assertEqual(self.model.sort_mode, "name")
        self.assertEqual(self.names(), ["alpha", "a_small.txt", "z_big.txt"])

    def test_sort_cycles_through_all_modes(self) -> None:
        seen = [self.model.sort_mode]
        for _ in range(len(SORT_MODES) - 1):
            seen.append(self.model.cycle_sort())
        self.assertEqual(seen, list(SORT_MODES))

    def test_filter_is_case_insensitive(self) -> None:
        self.model.set_filter("ALPHA")
        self.assertEqual(self.names(), ["alpha"])
        self.assertEqual(self.model.selected_entry().name, "alpha")

    def test_empty_filter_result_has_no_selection(self) -> None:
        self.model.set_filter("does-not-exist")
        self.assertEqual(self.names(), [])
        self.assertIsNone(self.model.selected_entry())

        self.model.set_filter("")
        self.assertEqual(len(self.names()), 3)

    def test_ensure_visible_scrolls_to_selection(self) -> None:
        self.model.select_index(2)
        self.model.ensure_visible(2)
        self.assertEqual(self.model.scroll_offset, 1)
        self.assertEqual(self.model.selected_index, 2)

    def test_empty_directory(self) -> None:
        empty = self.root / "empty"
        empty.mkdir()
        result = scan_directory(empty)
        model = TuiModel(result)

        self.assertEqual(model.visible_entries(), [])
        self.assertIsNone(model.selected_entry())
        self.assertEqual(model.current_size, 0)
        self.assertEqual(model.current_file_count, 0)
        self.assertFalse(model.enter())
        self.assertFalse(model.go_up())


class TuiRenderingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "folder").mkdir()
        (self.root / "folder" / "data.bin").write_bytes(b"x" * 10)
        (self.root / "file.txt").write_bytes(b"y" * 5)
        self.model = TuiModel(scan_directory(self.root))
        self.app = TuiApp(self.model)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_draw_renders_entries_and_selected_row(self) -> None:
        screen = FakeScreen()
        self.app._draw(screen)  # type: ignore[arg-type]

        text = "\n".join(write[2] for write in screen.writes)
        self.assertIn("folder/", text)
        self.assertIn("file.txt", text)
        selected = [
            write for write in screen.writes
            if write[3] & curses.A_REVERSE
        ]
        self.assertTrue(selected)
        self.assertIn("folder/", selected[0][2])

    def test_long_paths_do_not_break_rendering(self) -> None:
        self.model.current_path = Path("/" + "x" * 200)
        screen = FakeScreen()
        self.app._draw(screen)  # type: ignore[arg-type]
        self.assertTrue(screen.writes)


if __name__ == "__main__":
    unittest.main()
