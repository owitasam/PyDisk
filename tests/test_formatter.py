"""Tests for size formatting and parsing."""

from __future__ import annotations

import unittest

from pydisk.formatter import (
    escape_control_characters,
    human_readable_size,
    parse_size,
)


class HumanReadableSizeTests(unittest.TestCase):
    """Bytes should become short, predictable strings."""

    def test_bytes(self) -> None:
        self.assertEqual(human_readable_size(0), "0 B")
        self.assertEqual(human_readable_size(1), "1 B")
        self.assertEqual(human_readable_size(1023), "1023 B")

    def test_kilobytes(self) -> None:
        self.assertEqual(human_readable_size(1024), "1.0 KB")
        self.assertEqual(human_readable_size(1536), "1.5 KB")

    def test_megabytes_gigabytes_and_terabytes(self) -> None:
        self.assertEqual(human_readable_size(1024**2), "1.0 MB")
        self.assertEqual(human_readable_size(500 * 1024**2), "500.0 MB")
        self.assertEqual(human_readable_size(1024**3), "1.0 GB")
        self.assertEqual(human_readable_size(1024**4), "1.0 TB")

    def test_precision(self) -> None:
        self.assertEqual(human_readable_size(1536, precision=0), "2 KB")
        self.assertEqual(human_readable_size(1536, precision=2), "1.50 KB")

    def test_invalid_values(self) -> None:
        with self.assertRaises(ValueError):
            human_readable_size(-1)
        with self.assertRaises(ValueError):
            human_readable_size(1024, precision=-1)


class ParseSizeTests(unittest.TestCase):
    """User-supplied sizes should be forgiving but strict about garbage."""

    def test_plain_bytes(self) -> None:
        self.assertEqual(parse_size("0"), 0)
        self.assertEqual(parse_size("512"), 512)

    def test_units(self) -> None:
        self.assertEqual(parse_size("2KB"), 2048)
        self.assertEqual(parse_size("100MB"), 104857600)
        self.assertEqual(parse_size("1.5GB"), 1610612736)
        self.assertEqual(parse_size("1TB"), 1024**4)

    def test_spaces_and_case(self) -> None:
        self.assertEqual(parse_size(" 100 mb "), 104857600)
        self.assertEqual(parse_size("1.5 GB"), 1610612736)

    def test_short_unit_aliases(self) -> None:
        self.assertEqual(parse_size("1K"), 1024)
        self.assertEqual(parse_size("1M"), 1024**2)
        self.assertEqual(parse_size("1G"), 1024**3)
        self.assertEqual(parse_size("1T"), 1024**4)
        self.assertEqual(parse_size("1P"), 1024**5)
        self.assertEqual(parse_size("1.5G"), 1610612736)

    def test_invalid_sizes(self) -> None:
        for text in ["", "abc", "12XB", "-5MB", "MB", "1.2.3GB"]:
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_size(text)


class EscapeControlCharactersTests(unittest.TestCase):
    def test_common_escapes(self) -> None:
        self.assertEqual(
            escape_control_characters("line\nbreak\ttab\rreturn"),
            "line\\nbreak\\ttab\\rreturn",
        )

    def test_backslashes_are_escaped(self) -> None:
        self.assertEqual(
            escape_control_characters("back\\slash"),
            "back\\\\slash",
        )

    def test_ansi_and_other_control_characters(self) -> None:
        self.assertEqual(
            escape_control_characters("\x1b[31mred\x7f"),
            "\\x1b[31mred\\x7f",
        )

    def test_printable_unicode_is_preserved(self) -> None:
        self.assertEqual(
            escape_control_characters("üñïçødé-📁.bin"),
            "üñïçødé-📁.bin",
        )


if __name__ == "__main__":
    unittest.main()
