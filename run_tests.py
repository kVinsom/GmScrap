"""Run offline tests and style checks with the current Python interpreter."""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    missing = [
        name
        for name in ("fastapi", "httpx", "reportlab", "pypdf")
        if importlib.util.find_spec(name) is None
    ]
    if missing:
        print(
            "Missing test dependencies: "
            + ", ".join(missing)
            + ". Install requirements-dev.txt.",
            file=sys.stderr,
        )
        return 1
    root = Path(__file__).resolve().parent
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(None, (str(root / "src"), environment.get("PYTHONPATH")))
    )
    checks = (
        ("Tests", ["unittest", "discover", "-s", "tests", "-v"]),
        ("Lint", ["ruff", "check", "."]),
        ("Formatting", ["ruff", "format", "--check", "."]),
    )
    failed = []
    for name, arguments in checks:
        print(f"\n{name}", flush=True)
        result = subprocess.run(
            [sys.executable, "-m", *arguments],
            cwd=root,
            env=environment,
            check=False,
        )
        if result.returncode != 0:
            failed.append(name)
    if failed:
        print(f"\nFailed: {', '.join(failed)}", file=sys.stderr)
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
