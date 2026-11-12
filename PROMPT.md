# AI CODING PROMPT — PYDISK ANALYZER

You are a senior Python developer and mentor helping me build a beginner-friendly Linux command-line application.

## Project

Build a Python application called **PyDisk Analyzer**.

It is a Linux disk usage analyzer that scans directories, identifies large files and folders, calculates storage consumption, and generates reports.

My primary operating system is Fedora Linux.

## Your responsibilities

1. Build the project using clean, readable Python code.
2. Follow the project structure defined in this README.
3. Prefer Python standard libraries over external dependencies.
4. Explain the code and important programming concepts as you implement them.
5. Keep the implementation beginner-friendly.
6. Avoid unnecessary abstractions, complicated frameworks and overengineering.
7. Write modular, reusable functions.
8. Include error handling and automated tests.
9. Never introduce destructive filesystem operations.

## Technology requirements

- Python 3
- pathlib
- os
- argparse
- json
- collections
- unittest

Optional:
- Rich for terminal formatting.

Do not install optional dependencies unless they are actually needed.

## Application requirements

### 1. Directory scanner

The application must:
- Accept a directory path from the user.
- Recursively scan files and folders.
- Collect file names, paths and sizes.
- Count the number of files and folders.
- Calculate the total size of scanned files.
- Handle inaccessible files and folders gracefully.
- Handle missing or invalid directories.
- Avoid following symbolic links by default.
- Avoid getting stuck in symbolic link loops.

### 2. Storage analyzer

Implement functionality to:
- Calculate total directory size.
- Find the largest files.
- Find the largest immediate subdirectories.
- Sort files by size.
- Display the top 10 largest files by default.
- Calculate file and folder counts.

### 3. File filtering

Allow users to:
- Search for files by extension.
- Find files larger than a specified size.
- Filter files by minimum size.
- View the results in descending size order.

### 4. Human-readable formatting

Convert bytes into readable formats:
- Bytes
- KB
- MB
- GB
- TB

Use sensible decimal precision.

### 5. Report generation

Support:
- JSON report export.
- Plain-text report export.

Include:
- Scan location.
- Scan timestamp.
- Total size.
- Number of files.
- Number of folders.
- Largest files.
- Largest folders.
- Scan errors and skipped items where appropriate.

### 6. Command-line interface

Use argparse to create a simple CLI.

Target usage:

python main.py scan ~/Downloads

python main.py scan ~/Downloads --top 20

python main.py find ~/Downloads --extension .mp4

python main.py find ~/Downloads --min-size 100MB

python main.py report ~/Downloads --format json

python main.py report ~/Downloads --format txt

Validate command arguments and provide helpful error messages.

### 7. Safety requirements

This is a read-only application.

- Never delete files.
- Never modify files.
- Never rename files.
- Never move files.
- Never execute files found during scanning.
- Never require sudo/root privileges.
- Do not follow symbolic links by default.
- Do not silently ignore filesystem errors.

## Project structure

Create the following structure:

pydisk-analyzer/
├── pydisk/
│   ├── __init__.py
│   ├── scanner.py
│   ├── analyzer.py
│   ├── formatter.py
│   └── reporter.py
├── tests/
│   ├── test_scanner.py
│   └── test_formatter.py
├── reports/
├── main.py
├── README.md
├── requirements.txt
└── .gitignore

## Development workflow

IMPORTANT: Do not implement the entire application in one response.

Build the project in phases.

Phase 1: Project setup and basic directory scanning.

Phase 2: File and folder size analysis.

Phase 3: File extension and minimum-size filtering.

Phase 4: JSON and TXT report generation.

Phase 5: Command-line improvements, error handling and automated testing.

For each phase:

1. Explain what we are building.
2. Identify the files that need to be created or modified.
3. Explain the important Python concepts.
4. Implement the functionality.
5. Show how to run it.
6. Provide test cases.
7. Wait for my feedback before moving to the next phase.

## Code quality

- Use meaningful variable and function names.
- Add type hints where appropriate.
- Use docstrings for important functions.
- Keep functions reasonably small.
- Avoid duplicated code.
- Follow PEP 8 conventions.
- Handle exceptions appropriately.
- Do not suppress errors silently.

## Testing

Use Python's unittest framework.

Test:
- Empty directories.
- Directories containing multiple files.
- Nested folders.
- Different file sizes.
- Missing directories.
- Inaccessible directories where practical.
- Files with unusual names.
- Human-readable size formatting.

Use temporary directories in tests so real user files are never modified.

## Final objective

Produce a working, reliable and beginner-friendly Linux disk analyzer.

At the end, explain:
- How to run the application.
- How to run its tests.
- How to install any optional dependencies.
- How to use its commands.
- How to improve it in future versions.

Start with Phase 1 only.

Before writing code, briefly explain the implementation plan and then begin setting up the project.