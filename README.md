# PyDisk Analyzer

A small, beginner-friendly, **read-only** disk usage analyzer for Linux. It
scans a directory tree, ranks the largest files and folders, filters files by
extension or size, browses results in a terminal UI, and exports JSON or
plain-text reports.

<<<<<<< HEAD

=======
>>>>>>> dc7c0bb (formatting and changes to the  README.md)
## Features

- Recursive directory scanning with `os.scandir`
- Total size, file count and folder count
- Largest files and largest folders (grouped by configurable depth)
- Filtering by name, extension, minimum size and maximum size
- Human-readable sizes (`B`, `KB`, `MB`, `GB`, `TB`)
- Percent-of-total columns in rankings
- File-type summary by extension
- JSON and plain-text reports, to a file or stdout
- Interactive curses terminal UI for browsing folders
- Quiet mode for scripting and exit-code checks
- Optional streaming SQLite index for very large scans
- Exclude patterns, `--exclude-from` files and `--one-file-system`
- Optional interactive progress display on stderr
- Control-character escaping for safe terminal and report output
- Hard-link deduplication (matching `du`)
- Apparent size or allocated disk-block usage
- Graceful handling of permission errors and vanished files
- No third-party runtime dependencies

## Requirements

- Linux
- Python 3.9 or newer
- Standard library only
- `curses` for `pydisk tui` (bundled with Python on Linux)

## Installation

### Run from a checkout

```bash
cd ~/Projects/modding/PyDisk
python3 main.py --version
python3 -m pydisk scan ~/Downloads
```

### Install the `pydisk` command

Using [pipx](https://pipx.pypa.io/) (recommended on Fedora):

```bash
cd ~/Projects/modding/PyDisk
pipx install .
pydisk scan ~/Downloads
```

Or inside a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install .
pydisk scan ~/Downloads
```

Fedora's system Python is externally managed, so avoid `pip install` outside a
virtual environment or pipx.

## Quick start

```bash
# Scan a directory
pydisk scan ~/Downloads

# Show the 20 largest files and folders
pydisk scan ~/Downloads --top 20

# Show live progress during a long scan
pydisk scan ~/ --progress

# Find large video files
pydisk find ~/Downloads --extension .mp4 --min-size 100MB

# Find reports between 1 MB and 20 MB
pydisk find ~/Documents --name 'report-*.pdf' --min-size 1MB --max-size 20MB

# Save a JSON report and a text report
pydisk report ~/Downloads --format json
pydisk report ~/Downloads --format txt

# Print JSON directly to stdout
pydisk report ~/Downloads --stdout > report.json

# Run quietly and use only the exit code
pydisk scan ~/Downloads --quiet

# Browse the results interactively
pydisk tui ~/Downloads

# Stream a huge scan into a SQLite index
pydisk index ~/ --database ~/pydisk-index.db
```

## Commands

### `scan`

```bash
pydisk scan PATH [--top N] [--depth N] [scan options]
```

Prints totals, largest files, largest folders and a file-type summary. Each row
shows the size and its share of the scanned total. `--depth 2` groups folder
totals by two directory levels instead of just the immediate children.

### `find`

```bash
pydisk find PATH [--extension EXT] [--name GLOB] [--min-size SIZE]
                 [--max-size SIZE] [--top N] [--all] [scan options]
```

At least one of `--extension`, `--name`, `--min-size` or `--max-size` is
required. Results are sorted from largest to smallest, and the output states
how many matches are shown out of the total.

- Extensions are case-insensitive: `mp4`, `.MP4` and `*.mp4` are equivalent.
- Compound suffixes such as `.tar.gz` work.
- `--name` is a case-insensitive shell-style pattern matched against the
  filename, such as `report-*.pdf`.
- Minimum and maximum sizes are inclusive. Combining them creates a size range.

Examples:

```bash
pydisk find ~/Downloads --extension .mp4
pydisk find ~/Downloads --min-size 100MB
pydisk find ~/Documents --name 'report-*.pdf'
pydisk find ~/Downloads --extension .mp4 --min-size 100MB --max-size 2GB --all
```

### `tui`

```bash
pydisk tui PATH [scan options]
```

Opens a read-only terminal browser. The scan runs first, then the UI shows the
current directory's files and subdirectories, their sizes and their share of
the directory total. Scan progress is shown on stderr when available. The TUI
requires an interactive terminal.

| Key | Action |
| --- | --- |
| `Up`, `Down`, `k`, `j` | Move the selection |
| `PageUp`, `PageDown` | Move one page |
| `Home`, `End`, `g`, `G` | Jump to the first or last item |
| `Enter`, `Right`, `l` | Open the selected directory |
| `Left`, `Backspace`, `h` | Go to the parent directory |
| `s` | Cycle sorting by size, name or type |
| `/` | Filter the current directory by name |
| `c` | Clear the filter |
| `?` | Show help |
| `q` | Quit |

The TUI does not open or execute files. Pressing Enter on a file does nothing.

### `index`

```bash
pydisk index PATH --database FILE [scan options]
```

`index` uses the same scanner but streams each file into a new SQLite
database instead of keeping the full file list in memory. It is intended for
very large trees where a normal scan would use too much RAM. Choose a database
path outside the tree being scanned so the database file itself is not included
in the results.

The database is never overwritten. If a scan fails, the partially written
database is removed. Tables:

- `scan` — totals, options, timestamp and issue summaries
- `files` — one row per counted file
- `skipped` — recorded skipped paths
- `errors` — recorded errors

Example queries:

```bash
sqlite3 ~/pydisk-index.db \
  "SELECT path, size_bytes FROM files ORDER BY size_bytes DESC LIMIT 10;"
sqlite3 ~/pydisk-index.db \
  "SELECT file_count, total_size_bytes FROM scan;"
```

### `report`

```bash
pydisk report PATH [--format json|txt|text] [--top N] [--depth N]
                   [--output FILE | --stdout] [scan options]
```

`text` is an alias for `txt`. Reports are written to `./reports/` in the
current working directory by default, with a timestamped filename. Use
`--output` to choose a path, or `--stdout` to print the report instead of
creating a file. `--output -` is an alias for `--stdout`.

When `--stdout` is used, only the report is written to stdout, so JSON output
can be piped directly into tools such as `jq`.

Reports include:

- Scan location and timestamp
- Tool version and JSON schema version
- Total size, file count and folder count
- Largest files and folders, with percentage of total
- File-type summary by extension
- Scan options (excludes, size metric, hard-link handling, folder depth)
- Per-reason skipped-item summary and recorded skipped paths
- Per-reason error summary and recorded errors

Existing files are **never overwritten**; the command refuses and asks you to
choose another path.

### Shared scan options

| Option | Meaning |
| --- | --- |
| `-x`, `--exclude PATTERN` | Skip names or relative paths matching a glob. Repeatable. |
| `--exclude-from FILE` | Read exclude patterns from a file, one per line. Repeatable. Blank lines and lines starting with `#` are ignored. |
| `--progress` | Show live scan progress on stderr when stderr is an interactive terminal. |
| `--quiet` | Suppress normal result output. Exit codes still report incomplete scans, and a concise warning is printed to stderr when errors occurred. |
| `--one-file-system` | Do not descend into other mounted filesystems. |
| `--count-hardlinks` | Count each hard link separately instead of once. |
| `--disk-usage` | Measure allocated blocks instead of apparent file size. |
| `--max-skipped N` | Keep details for at most `N` skipped paths (default: 1000). Counts and summaries always include every path. |
| `--max-errors N` | Keep details for at most `N` errors (default: 1000). Counts and summaries always include every error. |

Examples:

```bash
pydisk scan ~/Downloads --exclude .git --exclude node_modules --exclude '*.cache'
pydisk scan ~/Downloads --exclude-from ~/.config/pydisk-excludes.txt
pydisk scan ~/ --one-file-system --top 20
pydisk scan ~/Downloads --disk-usage
pydisk scan ~/ --progress
pydisk scan ~/Downloads --quiet
```

## Scripting

JSON reports can go straight to stdout:

```bash
pydisk report ~/Downloads --stdout > report.json
pydisk report ~/Downloads --stdout --quiet | jq '.largest_files[0]'
```

`--quiet` suppresses human-readable results while preserving exit codes. If a
quiet scan encounters filesystem errors, it prints a short warning to stderr
and exits with code `1`.

Example exit-code check:

```bash
if pydisk scan ~/Downloads --quiet; then
    echo "scan completed"
else
    echo "scan was incomplete"
fi
```

Example `~/.config/pydisk-excludes.txt`:

```text
# Version-control and build output
.git
node_modules
*.cache
build/*.o
```

## How sizes are measured

- Default: **apparent size** (`st_size`), like `ls -l`.
- `--disk-usage`: **allocated blocks** (`st_blocks * 512`), like `du`.

This matters for sparse files, compression, and block allocation. You may see
different totals from `du` even with `--disk-usage`, because `du` and PyDisk
may treat hard links and filesystem boundaries differently.

Size units use powers of 1024: `1 KB = 1024 B`, `1 MB = 1024 KB`, and so on.

## Symlinks, hard links and mount points

- Symbolic links are **never followed**, so link loops cannot happen.
- Hard links are counted once by default, matching `du`.
- `--one-file-system` prevents crossing into bind mounts or network mounts.
- Skipped items are reported, not silently ignored.

The scanned root itself is resolved to its real path. The root directory is not
included in the folder count; only subdirectories are counted.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Scan completed without filesystem errors |
| `1` | Scan completed, but some paths could not be read |
| `2` | Invalid arguments or a fatal filesystem error |
| `130` | Interrupted with Ctrl+C |

The `tui` command returns the same scan-based exit code after you quit.

## Safety

PyDisk Analyzer is read-only with respect to scanned files:

- It never deletes, renames, moves, or modifies scanned files.
- It never executes files or requires root.
- It never follows symbolic links.
- The terminal UI only reads keyboard input and draws to the terminal.
- Report and index creation are the only filesystem write operations.
  Existing report or index files are never overwritten; choose a new output
  path instead.

## Project layout

```
pydisk/
├── pydisk/
│   ├── __init__.py
│   ├── __main__.py
│   ├── scanner.py
│   ├── analyzer.py
│   ├── formatter.py
│   ├── reporter.py
│   ├── indexer.py
│   ├── tui.py
│   └── cli.py
├── tests/
│   ├── test_scanner.py
│   ├── test_formatter.py
│   ├── test_analyzer.py
│   ├── test_reporter.py
│   ├── test_indexer.py
│   ├── test_tui.py
│   └── test_cli.py
├── .github/workflows/tests.yml
├── reports/
├── main.py
├── pyproject.toml
├── requirements.txt
├── LICENSE
├── PROMPT.md
└── README.md
```

## Running the tests

```bash
cd ~/Projects/modding/PyDisk
python3 -m unittest discover -s tests -v
```

Tests use `tempfile.TemporaryDirectory`, so real user files are never touched.
They cover empty and nested directories, unusual filenames, symlinks, hard
links, unreadable directories, size parsing/formatting, folder depth, file-type
summaries, name/size filters, exclude files, progress callbacks, streaming
SQLite indexes, TUI navigation and rendering, stdout and quiet output, reports,
and CLI behaviour.

The GitHub Actions workflow in `.github/workflows/tests.yml` runs the suite on
Python 3.9 through 3.15.

Optional development tools:

```bash
python3 -m pip install -e '.[dev]'
ruff check .
mypy pydisk
```

## License

MIT. See [LICENSE](LICENSE).

## Limitations and future ideas

- `scan`, `find`, `report` and `tui` hold files in memory. For enormous trees,
  use `pydisk index`, which streams files into SQLite instead.
- `index` still scans every entry and creates a database proportional to the
  number of files, but it avoids holding the full file list in RAM.
- The TUI omits empty directories because the scanner records files and
  directory counts, not a separate list of directory names.
- Following symlinks is deliberately not supported.
- Possible future work: a query command for saved indexes, mouse support in
  the TUI, and a graphical interface.
