"""Support python -m my_package."""

from my_package.main import main

if __name__ == "__main__":
    raise SystemExit(main())
