"""Standalone JSON-to-PDF CLI; does not import or run the scraper."""

import argparse
import json
import sys
from pathlib import Path

from my_package.handlers.pdf.pdf import PdfHandler
from my_package.services.pdf import PdfService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export GmScrap JSON as a PDF list.")
    parser.add_argument("input", help="UTF-8 JSON file, or - for stdin")
    parser.add_argument("output", type=Path, help="Destination .pdf file")
    parser.add_argument(
        "--location", help="Fallback location label, e.g. Lviv, Ukraine"
    )
    parser.add_argument(
        "--font", type=Path, help="Path to a Unicode-capable TrueType font"
    )
    args = parser.parse_args(argv)
    try:
        payload = (
            sys.stdin.read().removeprefix("\ufeff")
            if args.input == "-"
            else Path(args.input).read_text(encoding="utf-8-sig")
        )
        output = PdfHandler(PdfService(font_path=args.font)).generate(
            payload, args.output, location=args.location
        )
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
