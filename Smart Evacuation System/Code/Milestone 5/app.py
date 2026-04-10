#!/usr/bin/env python3
from __future__ import annotations

import runpy
import sys
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parent
    code_app = repo_root / "Code" / "app.py"
    code_dir = str(repo_root / "Code")
    if code_dir not in sys.path:
        sys.path.insert(0, code_dir)

    args = sys.argv[1:]
    if not args:
        args = ["--input-mode", "web"]

    sys.argv = [str(code_app), *args]
    runpy.run_path(str(code_app), run_name="__main__")


if __name__ == "__main__":
    main()
