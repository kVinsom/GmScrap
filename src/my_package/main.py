"""CLI boundary shared by the console script and Python entry points."""

import argparse
import json
import sys

from my_package import __version__
from my_package.domain.errors import GeocodingError, OverpassError
from my_package.export import results_csv
from my_package.handlers.scrap.scrap import ScrapHandler
from my_package.services.scrap import ScrapService


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gmscrap", description="Find OSM places and mapped contacts."
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument("--center", required=True, help='"lat, lon" or "Lviv, Ukraine"')
    parser.add_argument("--category", required=True, help='For example, "coffee shop"')
    parser.add_argument("--radius", required=True, type=int, help="Radius in meters")
    parser.add_argument(
        "--name", help="Optional case-insensitive literal name fragment"
    )
    parser.add_argument(
        "--has-contact",
        action="append",
        default=[],
        choices=("email", "instagram", "facebook", "website", "phone"),
        help="Require any selected contact field; repeat for OR matching",
    )
    parser.add_argument("--sort", choices=("distance", "source"), default="distance")
    parser.add_argument(
        "--no-enrich-website", action="store_true", help="Use only OSM contacts"
    )
    parser.add_argument("--format", choices=("json", "csv"), default="json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = create_parser().parse_args(argv)
    try:
        result = ScrapHandler(ScrapService()).search(
            args.center,
            args.category,
            args.radius,
            args.name,
            contacts=tuple(args.has_contact),
            sort_by_distance=args.sort == "distance",
            enrich_website=not args.no_enrich_website,
        )
    except (TypeError, ValueError, GeocodingError, OverpassError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(json.dumps({"error": "Search interrupted."}), file=sys.stderr)
        return 130
    if args.format == "csv":
        sys.stdout.write(results_csv(json.loads(result)))
    else:
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
