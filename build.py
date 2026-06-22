#!/usr/bin/env python3
"""Build a standalone JobBoards executable with PyInstaller."""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def ensure_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Installing build dependencies…")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements-build.txt")]
        )


def output_name() -> str:
    if sys.platform == "win32":
        return "JobBoards.exe"
    return "JobBoards"


def main() -> int:
    ensure_pyinstaller()
    print(f"Building JobBoards for {platform.system()} ({platform.machine()})…")
    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            str(ROOT / "JobBoards.spec"),
            "--noconfirm",
            "--clean",
        ],
        cwd=ROOT,
    )
    built = ROOT / "dist" / output_name()
    if built.is_file():
        print(f"\nDone: {built}")
        print("Run it directly — it opens your browser and stores data in your user data folder.")
        return 0
    print("Build finished but output file was not found in dist/.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
