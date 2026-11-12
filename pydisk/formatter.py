"""Human-readable size formatting and parsing."""

from __future__ import annotations

import re

# Sizes use powers of 1024, the same convention as `du -h` and `ls -h`.
UNITS = ("B", "KB", "MB", "GB", "TB", "PB")
BYTES_PER_UNIT = 1024

_SIZE_PATTERN = re.compile(
    r"^(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>[kmgtp]?b?)$",
    re.IGNORECASE,
)
_MULTIPLIERS = {
    "": 1,
    "b": 1,
    "kb": BYTES_PER_UNIT,
    "mb": BYTES_PER_UNIT**2,
    "gb": BYTES_PER_UNIT**3,
    "tb": BYTES_PER_UNIT**4,
    "pb": BYTES_PER_UNIT**5,
}

_SIMPLE_ESCAPES = {
    "\\": "\\\\",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}


def escape_control_characters(text: str) -> str:
    """Escape control characters so filenames cannot break terminal output.

    Newlines, tabs, carriage returns and backslashes are escaped, and other
    C0/C1 control characters (including ANSI escape sequences) become ``\\xNN``.
    """
    escaped: list[str] = []
    for character in text:
        if character in _SIMPLE_ESCAPES:
            escaped.append(_SIMPLE_ESCAPES[character])
            continue

        code = ord(character)
        if code < 32 or 127 <= code <= 159:
            escaped.append(f"\\x{code:02x}")
        else:
            escaped.append(character)
    return "".join(escaped)


def human_readable_size(size: int, precision: int = 1) -> str:
    """Convert a byte count into a short readable string.

    Examples: ``0`` -> ``"0 B"``, ``1536`` -> ``"1.5 KB"``.
    """
    if size < 0:
        raise ValueError("size cannot be negative")
    if precision < 0:
        raise ValueError("precision must be zero or greater")

    if size < BYTES_PER_UNIT:
        return f"{size} B"

    value = float(size)
    for unit in UNITS[1:]:
        value /= BYTES_PER_UNIT
        if value < BYTES_PER_UNIT or unit == UNITS[-1]:
            return f"{value:.{precision}f} {unit}"

    # The loop always returns, but this keeps type checkers satisfied.
    return f"{size} B"


def parse_size(text: str) -> int:
    """Parse a size like ``512``, ``100MB`` or ``1.5 GB`` into bytes."""
    match = _SIZE_PATTERN.match(text.strip())
    if match is None:
        raise ValueError(
            f"invalid size {text!r}; try a value like '100MB' or '1.5 GB'"
        )

    number = float(match.group("number"))
    unit = match.group("unit").lower()

    # Accept short forms such as "1K" and "1.5G" as well as "1KB"/"1.5GB".
    if unit and not unit.endswith("b"):
        unit += "b"

    return int(number * _MULTIPLIERS[unit])
