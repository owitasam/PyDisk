"""Interactive curses browser for a completed scan.

The scanner still owns all filesystem access. This module builds a small
in-memory tree from :class:`~pydisk.scanner.ScanResult` and renders it with the
standard library ``curses`` module. It only reads terminal input and never
modifies files.
"""

from __future__ import annotations

import curses
import locale
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .formatter import escape_control_characters, human_readable_size
from .scanner import ScanResult

SORT_MODES = ("size", "name", "type")
LIST_TOP = 3


@dataclass(frozen=True)
class TuiEntry:
    """One direct child of a directory in the browser."""

    path: Path
    size: int
    is_dir: bool
    file_count: int = 0

    @property
    def name(self) -> str:
        """Return the display name for this entry."""
        return self.path.name or str(self.path)


class TuiModel:
    """Navigation, sorting and filtering state for the terminal UI.

    The model contains no curses code so it can be tested without a terminal.
    """

    def __init__(self, result: ScanResult) -> None:
        self.result = result
        self.root = Path(result.root)
        self.current_path = self.root
        self.sort_mode = "size"
        self.filter_text = ""
        self.selected_index = 0
        self.scroll_offset = 0
        self._children: dict[Path, list[TuiEntry]] = defaultdict(list)
        self._dir_sizes: dict[Path, int] = {self.root: result.total_size}
        self._dir_file_counts: dict[Path, int] = {
            self.root: result.file_count,
        }
        self._visible_cache_key: tuple[Path, str, str] | None = None
        self._visible_cache: list[TuiEntry] = []
        self._build_tree()

    def _build_tree(self) -> None:
        """Group scanned files into direct children and folder totals."""
        directory_paths: set[Path] = set()

        for file in self.result.files:
            try:
                relative = file.path.relative_to(self.root)
            except ValueError:
                # Defensive: ignore files outside the scanned tree.
                continue

            parts = relative.parts
            if not parts:
                continue

            self._children[file.path.parent].append(
                TuiEntry(
                    path=file.path,
                    size=file.size,
                    is_dir=False,
                )
            )

            for index in range(1, len(parts)):
                directory = self.root.joinpath(*parts[:index])
                self._dir_sizes[directory] = (
                    self._dir_sizes.get(directory, 0) + file.size
                )
                self._dir_file_counts[directory] = (
                    self._dir_file_counts.get(directory, 0) + 1
                )
                directory_paths.add(directory)

        for directory in directory_paths:
            self._children[directory.parent].append(
                TuiEntry(
                    path=directory,
                    size=self._dir_sizes.get(directory, 0),
                    is_dir=True,
                    file_count=self._dir_file_counts.get(directory, 0),
                )
            )

    @property
    def current_size(self) -> int:
        """Return the counted size of the current directory."""
        if self.current_path == self.root:
            return self.result.total_size
        return self._dir_sizes.get(self.current_path, 0)

    @property
    def current_file_count(self) -> int:
        """Return the number of counted files below the current directory."""
        if self.current_path == self.root:
            return self.result.file_count
        return self._dir_file_counts.get(self.current_path, 0)

    @property
    def current_share(self) -> float:
        """Return the current directory's percentage of the scan total."""
        total = self.result.total_size
        return (self.current_size / total * 100.0) if total else 0.0

    def visible_entries(self) -> list[TuiEntry]:
        """Return the current directory's entries after filtering and sorting."""
        key = (self.current_path, self.sort_mode, self.filter_text)
        if key == self._visible_cache_key:
            return self._visible_cache

        entries = list(self._children.get(self.current_path, []))
        if self.filter_text:
            needle = self.filter_text.casefold()
            entries = [
                entry
                for entry in entries
                if needle in entry.name.casefold()
            ]

        entries = self._sort_entries(entries)
        self._visible_cache_key = key
        self._visible_cache = entries
        return entries

    def _sort_entries(self, entries: list[TuiEntry]) -> list[TuiEntry]:
        """Sort entries according to the current sort mode."""
        if self.sort_mode == "name":
            return sorted(
                entries,
                key=lambda entry: (
                    not entry.is_dir,
                    entry.name.casefold(),
                    str(entry.path),
                ),
            )

        if self.sort_mode == "type":
            return sorted(
                entries,
                key=lambda entry: (
                    not entry.is_dir,
                    (
                        ""
                        if entry.is_dir
                        else entry.path.suffix.casefold()
                    ),
                    entry.name.casefold(),
                    str(entry.path),
                ),
            )

        return sorted(
            entries,
            key=lambda entry: (
                -entry.size,
                not entry.is_dir,
                entry.name.casefold(),
                str(entry.path),
            ),
        )

    def selected_entry(self) -> TuiEntry | None:
        """Return the currently selected entry, if the list is not empty."""
        entries = self.visible_entries()
        if not entries:
            return None
        index = min(self.selected_index, len(entries) - 1)
        return entries[index]

    def move_selection(self, delta: int) -> None:
        """Move the selection by ``delta`` entries, clamped to the list."""
        entries = self.visible_entries()
        if not entries:
            self.selected_index = 0
            return
        self.selected_index = max(
            0,
            min(len(entries) - 1, self.selected_index + delta),
        )

    def select_index(self, index: int) -> None:
        """Select an entry by index, clamped to the list."""
        entries = self.visible_entries()
        if not entries:
            self.selected_index = 0
            return
        self.selected_index = max(0, min(len(entries) - 1, index))

    def ensure_visible(self, height: int) -> None:
        """Adjust scrolling so the selected row is inside the viewport."""
        if height <= 0:
            return

        entries = self.visible_entries()
        if not entries:
            self.selected_index = 0
            self.scroll_offset = 0
            return

        self.selected_index = max(
            0,
            min(self.selected_index, len(entries) - 1),
        )
        if self.selected_index < self.scroll_offset:
            self.scroll_offset = self.selected_index
        elif self.selected_index >= self.scroll_offset + height:
            self.scroll_offset = self.selected_index - height + 1

        maximum_offset = max(0, len(entries) - height)
        self.scroll_offset = max(
            0,
            min(self.scroll_offset, maximum_offset),
        )

    def enter(self) -> bool:
        """Enter the selected directory. Return whether navigation happened."""
        entry = self.selected_entry()
        if entry is None or not entry.is_dir:
            return False

        self.current_path = entry.path
        self.selected_index = 0
        self.scroll_offset = 0
        return True

    def go_up(self) -> bool:
        """Move to the parent directory and select the directory we left."""
        if self.current_path == self.root:
            return False

        previous = self.current_path
        self.current_path = self.current_path.parent
        self.selected_index = 0
        self.scroll_offset = 0

        for index, entry in enumerate(self.visible_entries()):
            if entry.path == previous:
                self.selected_index = index
                break
        return True

    def cycle_sort(self) -> str:
        """Switch to the next sort mode and return its name."""
        index = SORT_MODES.index(self.sort_mode)
        self.sort_mode = SORT_MODES[(index + 1) % len(SORT_MODES)]
        self.selected_index = 0
        self.scroll_offset = 0
        return self.sort_mode

    def set_filter(self, text: str) -> None:
        """Filter the current directory by a case-insensitive name substring."""
        self.filter_text = text.strip()
        self.selected_index = 0
        self.scroll_offset = 0


class TuiApp:
    """Curses rendering and keyboard handling for a :class:`TuiModel`."""

    def __init__(self, model: TuiModel) -> None:
        self.model = model
        self._colors = False

    def run(self, screen: curses.window) -> None:
        """Run the main event loop until the user presses ``q``."""
        try:
            curses.curs_set(0)
        except curses.error:
            pass

        screen.keypad(True)
        self._init_colors()
        try:
            while True:
                self._draw(screen)
                key = screen.getch()
                if key == -1:
                    continue
                if not self._handle_key(screen, key):
                    break
        finally:
            try:
                curses.curs_set(1)
            except curses.error:
                pass

    def _init_colors(self) -> None:
        """Enable a small colour palette when the terminal supports it."""
        try:
            if not curses.has_colors():
                return
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_CYAN, -1)
            curses.init_pair(2, curses.COLOR_BLUE, -1)
            curses.init_pair(3, curses.COLOR_RED, -1)
            self._colors = True
        except curses.error:
            self._colors = False

    def _attr(self, pair: int, extra: int = 0) -> int:
        """Return a curses attribute, with colour when available."""
        if self._colors:
            return curses.color_pair(pair) | extra
        return extra

    def _draw(self, screen: curses.window) -> None:
        """Draw the whole screen from the current model state."""
        height, width = screen.getmaxyx()
        screen.erase()

        if height < 6 or width < 30:
            _put(
                screen,
                0,
                0,
                "Terminal too small. Resize the window or press q.",
                0,
            )
            screen.refresh()
            return

        self._draw_header(screen, width)
        self._draw_entries(screen, height, width)
        self._draw_footer(screen, height, width)
        screen.refresh()

    def _draw_header(self, screen: curses.window, width: int) -> None:
        """Draw the title, current path and summary line."""
        title = "PyDisk Analyzer  "
        path = escape_control_characters(str(self.model.current_path))
        path = _fit_path(path, max(0, width - len(title) - 1))
        _put(screen, 0, 0, title + path, self._attr(1, curses.A_BOLD))

        line = (
            f"Current: {human_readable_size(self.model.current_size)}  "
            f"Files: {self.model.current_file_count}  "
            f"Of scan: {self.model.current_share:.1f}%  "
            f"Sort: {self.model.sort_mode}"
        )
        if self.model.result.error_count:
            line += f"  Errors: {self.model.result.error_count}"
        if self.model.filter_text:
            line += (
                '  Filter: "'
                + escape_control_characters(self.model.filter_text)
                + '"'
            )
        _put(screen, 1, 0, line, self._attr(1))
        _put(screen, 2, 0, "-" * max(1, width - 1), 0)

    def _draw_entries(
        self,
        screen: curses.window,
        height: int,
        width: int,
    ) -> None:
        """Draw the visible slice of the current directory."""
        list_height = max(1, height - LIST_TOP - 2)
        entries = self.model.visible_entries()
        self.model.ensure_visible(list_height)

        if not entries:
            message = (
                "(no entries match the filter)"
                if self.model.filter_text
                else "(no counted files or subdirectories here)"
            )
            _put(screen, LIST_TOP, 1, message, self._attr(3))
            return

        total = self.model.current_size
        start = self.model.scroll_offset
        for row, entry in enumerate(entries[start : start + list_height]):
            index = start + row
            percentage = (entry.size / total * 100.0) if total else 0.0
            kind = "DIR " if entry.is_dir else "FILE"
            name = escape_control_characters(entry.name)
            if entry.is_dir:
                name += "/"

            line = (
                f"{kind} {human_readable_size(entry.size):>10} "
                f"{percentage:>5.1f}%  {name}"
            )
            attribute = 0
            if entry.is_dir:
                attribute |= self._attr(2, curses.A_BOLD)
            if index == self.model.selected_index:
                attribute |= curses.A_REVERSE
                padded = line[: max(0, width - 1)].ljust(
                    max(0, width - 1)
                )
                _put(screen, LIST_TOP + row, 0, padded, attribute)
            else:
                _put(screen, LIST_TOP + row, 0, line, attribute)

    def _draw_footer(
        self,
        screen: curses.window,
        height: int,
        width: int,
    ) -> None:
        """Draw the keyboard help line."""
        if width >= 78:
            text = (
                "Up/Down move  Enter open  Left/Backspace up  "
                "s sort  / filter  c clear  ? help  q quit"
            )
        elif width >= 52:
            text = (
                "Up/Down  Enter  Backspace  s sort  "
                "/ filter  ? help  q quit"
            )
        else:
            text = "? help  q quit"
        _put(screen, height - 1, 0, text, self._attr(1, curses.A_DIM))

    def _handle_key(self, screen: curses.window, key: int) -> bool:
        """Apply one keypress. Return whether the UI should keep running."""
        if key == curses.KEY_RESIZE:
            return True
        if key in (ord("q"), ord("Q")):
            return False
        if key == ord("?"):
            self._show_help(screen)
            return True
        if key in (curses.KEY_UP, ord("k")):
            self.model.move_selection(-1)
        elif key in (curses.KEY_DOWN, ord("j")):
            self.model.move_selection(1)
        elif key == curses.KEY_PPAGE:
            self.model.move_selection(-self._page_size(screen))
        elif key == curses.KEY_NPAGE:
            self.model.move_selection(self._page_size(screen))
        elif key in (curses.KEY_HOME, ord("g")):
            self.model.select_index(0)
        elif key in (curses.KEY_END, ord("G")):
            self.model.select_index(len(self.model.visible_entries()) - 1)
        elif key in (
            curses.KEY_ENTER,
            10,
            13,
            curses.KEY_RIGHT,
            ord("l"),
        ):
            self.model.enter()
        elif key in (
            curses.KEY_BACKSPACE,
            127,
            8,
            curses.KEY_LEFT,
            ord("h"),
        ):
            self.model.go_up()
        elif key == ord("s"):
            self.model.cycle_sort()
        elif key == ord("/"):
            self._prompt_filter(screen)
        elif key == ord("c"):
            self.model.set_filter("")
        return True

    def _page_size(self, screen: curses.window) -> int:
        """Return the number of rows in the list viewport."""
        height, _ = screen.getmaxyx()
        return max(1, height - LIST_TOP - 2)

    def _show_help(self, screen: curses.window) -> None:
        """Draw a simple full-screen help page and wait for a key."""
        height, width = screen.getmaxyx()
        lines = [
            "PyDisk Analyzer - terminal UI",
            "",
            "Up/Down, k/j       move selection",
            "PageUp/PageDown    move one page",
            "Home/End, g/G      first or last item",
            "Enter/Right/l      open directory",
            "Left/Backspace/h   go to parent directory",
            "s                  cycle sort: size, name, type",
            "/                  filter current directory",
            "c                  clear the filter",
            "?                  show this help",
            "q                  quit",
            "",
            "Press any key to return.",
        ]
        screen.erase()
        for row, line in enumerate(lines):
            if row >= height - 1:
                break
            attribute = self._attr(1, curses.A_BOLD) if row == 0 else 0
            _put(screen, row, 1, line, attribute)
        screen.refresh()
        screen.getch()

    def _prompt_filter(self, screen: curses.window) -> None:
        """Ask for a filter string on the bottom line."""
        height, width = screen.getmaxyx()
        if height < 2:
            return
        prompt = "Filter (empty clears): "
        row = height - 1
        screen.move(row, 0)
        screen.clrtoeol()
        _put(screen, row, 0, prompt, self._attr(1))
        screen.refresh()

        try:
            curses.curs_set(1)
        except curses.error:
            pass

        try:
            curses.echo()
            raw = screen.getstr(
                row,
                len(prompt),
                max(1, width - len(prompt) - 1),
            )
        finally:
            curses.noecho()
            try:
                curses.curs_set(0)
            except curses.error:
                pass

        if isinstance(raw, bytes):
            text = raw.decode("utf-8", "replace")
        else:  # pragma: no cover - older curses implementations
            text = str(raw)
        self.model.set_filter(text)


def _fit_path(path: str, width: int) -> str:
    """Fit a path into ``width`` characters, keeping its final components."""
    if width <= 0:
        return ""
    if len(path) <= width:
        return path
    if width <= 3:
        return path[:width]
    return "..." + path[-(width - 3) :]


def _put(
    screen: curses.window,
    y: int,
    x: int,
    text: str,
    attribute: int = 0,
) -> None:
    """Write text safely, avoiding the bottom-right cell and curses errors."""
    height, width = screen.getmaxyx()
    if not text or y < 0 or y >= height or x < 0 or x >= width:
        return

    available = width - x
    if y == height - 1:
        available -= 1
    if available <= 0:
        return

    try:
        screen.addnstr(y, x, text, available, attribute)
    except (curses.error, UnicodeError):
        pass


def run_terminal_ui(result: ScanResult) -> None:
    """Open the interactive browser for a completed scan."""
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass

    app = TuiApp(TuiModel(result))
    try:
        curses.wrapper(app.run)
    except curses.error as exc:
        raise OSError(f"cannot start terminal UI: {exc}") from exc
