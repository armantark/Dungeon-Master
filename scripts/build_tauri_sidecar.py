from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
TAURI_BIN_DIR = WEB_DIR / "src-tauri" / "binaries"
PYINSTALLER_ROOT = ROOT / ".tauri-sidecar"
DIST_DIR = PYINSTALLER_ROOT / "dist"
WORK_DIR = PYINSTALLER_ROOT / "work"
SPEC_DIR = PYINSTALLER_ROOT / "spec"
ENTRYPOINT = ROOT / "src" / "dungeon_master" / "cli.py"
APP_NAME = "dungeon-master-backend"

# Uvicorn discovers parts of its runtime dynamically; being explicit keeps the
# packaged sidecar predictable across platforms and matches the common
# FastAPI/PyInstaller workaround shape.
HIDDEN_IMPORTS = (
    "tiktoken_ext.openai_public",
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
)


def main() -> None:
    target_triple = resolve_target_triple()
    if not target_triple:
        message = "Unable to determine a Tauri target triple."
        raise RuntimeError(message)

    DIST_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    SPEC_DIR.mkdir(parents=True, exist_ok=True)
    TAURI_BIN_DIR.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        APP_NAME,
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(WORK_DIR),
        "--specpath",
        str(SPEC_DIR),
        "--collect-data",
        "litellm",
    ]
    for hidden_import in HIDDEN_IMPORTS:
        command.extend(["--hidden-import", hidden_import])
    command.append(str(ENTRYPOINT))

    subprocess.run(command, check=True, cwd=ROOT)  # noqa: S603

    extension = ".exe" if "windows" in target_triple else ""
    built_binary = DIST_DIR / f"{APP_NAME}{extension}"
    if not built_binary.exists():
        message = f"Expected PyInstaller output at {built_binary}"
        raise FileNotFoundError(message)

    packaged_binary = TAURI_BIN_DIR / f"{APP_NAME}-{target_triple}{extension}"
    if packaged_binary.exists():
        packaged_binary.unlink()
    shutil.copy2(built_binary, packaged_binary)


def resolve_target_triple() -> str:
    rustc = shutil.which("rustc")
    if rustc is None:
        return infer_target_triple()
    try:
        return (
            subprocess.run(  # noqa: S603
                [rustc, "--print", "host-tuple"],
                check=True,
                capture_output=True,
                text=True,
                cwd=ROOT,
            )
            .stdout.strip()
        )
    except subprocess.CalledProcessError as err:
        try:
            return infer_target_triple()
        except RuntimeError as fallback_error:
            raise fallback_error from err


def infer_target_triple() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = {
        "arm64": "aarch64",
        "aarch64": "aarch64",
        "x86_64": "x86_64",
        "amd64": "x86_64",
    }.get(machine, machine)
    if system == "darwin":
        return f"{arch}-apple-darwin"
    if system == "linux":
        return f"{arch}-unknown-linux-gnu"
    if system == "windows":
        return f"{arch}-pc-windows-msvc"
    message = "Unable to infer a Tauri target triple without rustc on PATH."
    raise RuntimeError(message)


if __name__ == "__main__":
    main()
