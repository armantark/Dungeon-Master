from __future__ import annotations

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = (
    REPOSITORY_ROOT / "src",
    REPOSITORY_ROOT / "tests",
    REPOSITORY_ROOT / "scripts",
    REPOSITORY_ROOT / "web" / "src",
    REPOSITORY_ROOT / "web" / "src-tauri" / "src",
)
SOURCE_SUFFIXES = {".css", ".py", ".rs", ".svelte", ".ts"}
MAX_LINES = 999
PACKAGE_ROOT = REPOSITORY_ROOT / "src" / "dungeon_master"
ALLOWED_PACKAGE_ROOT_FILES = {"__init__.py", "py.typed"}


def source_files() -> list[Path]:
    files: set[Path] = set()
    for root in SOURCE_ROOTS:
        files.update(path for path in root.rglob("*") if path.suffix in SOURCE_SUFFIXES)
    return sorted(files)


def line_count(path: Path) -> int:
    with path.open("r", encoding="utf-8") as source:
        return sum(1 for _line in source)


def layout_errors() -> list[str]:
    errors: list[str] = []
    for path in source_files():
        lines = line_count(path)
        if lines > MAX_LINES:
            errors.append(
                f"{path.relative_to(REPOSITORY_ROOT)} has {lines} lines; maximum is {MAX_LINES}."
            )
    errors.extend(
        f"{path.relative_to(REPOSITORY_ROOT)} is not a conventional package-root file."
        for path in sorted(PACKAGE_ROOT.iterdir())
        if path.is_file() and path.name not in ALLOWED_PACKAGE_ROOT_FILES
    )
    return errors


def main() -> int:
    errors = layout_errors()
    if errors:
        sys.stdout.write(
            "Source layout check failed:\n" + "".join(f"- {error}\n" for error in errors)
        )
        return 1
    sys.stdout.write(f"Source layout check passed: all files are <= {MAX_LINES} lines.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
