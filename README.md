# GmScrap

## Install and run

Release **0.1.0** requires Python **3.14**. From an activated project environment:

```shell
python -m pip install .
gmscrap --version
gmscrap --center "49.8415, 24.0315" --category "coffee shop" --radius 5000
```

`python main.py` and `python -m my_package` accept the same arguments after
installation. For development, `make install` installs the pinned tools and an
editable checkout. Build validated wheel/source artifacts with `make release`
or `python scripts/release.py`. See [release instructions](docs/RELEASE.md).

## Architecture

The search is split into domain models, an application use case, and adapters for
Nominatim and Overpass. Dependencies can be injected through small protocols;
the existing `ScrapService` API continues to return JSON. See
[the architecture guide](docs/ARCHITECTURE.md) for responsibilities, dependency
rules, compatibility details, and extension points. Architecture checks run with
the regular test suite.

## Docker and Make

Use Docker with Linux containers, Docker Compose v2 or later, and GNU Make.
Docker Desktop must be running on Windows. The configuration was validated with
Docker Engine 29.7.2 and Compose 5.4.0; host tools are prerequisites, not installed
by the Makefile. Containers use Python **3.14.10** on Debian Bookworm slim, pinned
to a multi-platform SHA-256 digest. Runtime and test dependencies, including
transitive packages, are pinned to exact versions in `requirements*.txt`.

```shell
make all
make run
make run SEARCH_CENTER="Lviv, Ukraine" SEARCH_NAME="Lviv"
```

`make all` builds the production and test images, then runs the offline test
suite, lint, and formatting checks. `make run` uses the built production image
and makes a live search. The defaults are cafes within 5000 meters of
49.8415, 24.0315. To change them, set `SEARCH_CENTER`, `SEARCH_CATEGORY`,
`SEARCH_RADIUS` (meters), or `SEARCH_NAME` as Make variables or environment
variables. Search results go to stdout, errors go to stderr, and failures return
a nonzero exit code. After building, `make run > places.json` saves the JSON.

| Command | Action |
| --- | --- |
| `make build` | Build the production image |
| `make check` | Build the test image and run all checks |
| `make test` | Run tests only in the test image |
| `make lint` / `make format-check` | Check lint / formatting in the test image |
| `make config` | Validate Compose configuration |
| `make install` | Install pinned dependencies into an existing local `.venv` |
| `make check-local` | Run all checks with local Python |
| `make format` | Fix imports and format local Python files |
| `make down` | Remove this project's containers and networks |
| `make release` | Test, build, and validate wheel/source artifacts in `dist/` |

Override `PYTHON` for local commands if your interpreter is elsewhere. On Windows,
the default is `.venv/Scripts/python.exe`; on Linux/macOS it is `.venv/bin/python`.
GNU Make is not included with Windows. Without Make, use these equivalent
PowerShell commands:

```powershell
docker compose --profile tools build
docker compose --profile tools run --rm --no-deps -T tests
docker compose run --rm --no-deps -T gmscrap
# Or pass the CLI arguments directly:
docker compose run --rm --no-deps -T gmscrap --center "Lviv, Ukraine" --category "coffee shop" --radius 5000 --name "Lviv"
```

`Dockerfile` contains the dependency builder and production runtime;
`Dockerfile.test` provides the isolated test tools. Source and dependencies are
root-owned; both containers run as UID/GID 10001. Compose uses a read-only root
filesystem, a limited temporary filesystem, dropped capabilities, disabled
privilege escalation, process/memory/CPU limits, and bounded logs. The test
container has networking disabled. Builds still need access to the image
registry and package index; live searches need outbound HTTPS.

The production CLI container runs one search and exits. It has no listening port, persistent data,
restart loop, or HTTP health endpoint. No host directories are mounted into
the containers. `.dockerignore` limits build inputs to source, tests, dependency
files, build metadata, scripts, documentation, and the license. The production
image runs the installed wheel through the `gmscrap` console command.

When upgrading, update the exact dependency pins together, verify `pip check`,
update both Dockerfiles to the same Python version and registry digest, then run
`make all`. Pins make versions repeatable; upgrades and security fixes still need
deliberate review. Docker references:
[image pinning](https://docs.docker.com/build/building/best-practices/#pin-base-image-versions)
and [Compose services](https://docs.docker.com/reference/compose-file/services/).

## OpenStreetMap place search

Install runtime dependencies and run from the project root in PowerShell:

```powershell
python -m pip install -r requirements.txt
$env:PYTHONPATH = "src"
python -m my_package.main --center "49.8415, 24.0315" --category "coffee shop" --radius 5000
```

City search uses geopy with Nominatim. Add an optional literal, case-insensitive
name fragment to narrow the results:

```powershell
python -m my_package.main --center "Lviv, Ukraine" --category "coffee shop" --radius 5000 --name "Lviv"
```

Supported categories: `coffee shop` / `cafe`, `restaurant`, `bar`, `pharmacy`,
and `supermarket`. Comma-separated categories are also supported. Radius is a
positive integer in **meters**. Coordinates use latitude first, longitude second.

For a conservative cafe contact list, check saved results against their original
OSM tags and require at least one website, email, phone or supported social profile:

```shell
python scripts/filter_businesses.py places.json osm-source.json businesses.json --audit exclusions.json
```

The filter excludes streets, geographical features, inactive cafes, unnamed
records, ambiguous landmark objects and records with no valid contacts. A cafe
mapped on a building outline remains eligible. This is source-tag screening,
rather than independent confirmation that a business is currently trading.
Addresses and generated Maps links do not count as contact information.
`phone` is included in JSON, CSV and PDF output and supports `--has-contact phone`.
Use `--reviews contact-review.json` to apply documented rejected-contact entries
before filtering. Each entry under `rejected_contacts` supplies `osm_id`, `field`
and the normalized `value`, with optional evidence and a reason. Rejected
contacts cannot be restored by fallback tags from the source response.
The input must be an array of records with unique OSM identities; reviews must
identify a supported contact field and valid value. Input, output and audit
paths must be distinct. Invalid input and file errors return a JSON error on
stderr with exit code 1. Both output files are staged before replacement, and
completed replacements are restored if a later replacement fails.
Numeric-leading centers are interpreted as coordinates; other text is geocoded.
The original `ScrapHandler.scrape(geo, key_word, radius_in_km)` entry point still
accepts kilometers and comma-separated categories.

Successful searches write a JSON array to stdout and exit with code 0, including
`[]` when no places match. Validation, geocoding, HTTP, invalid JSON, and Overpass
runtime failures write an `{"error": "..."}` object to stderr and exit with code 1.
Command-line syntax errors (such as missing options or a noninteger radius) use
argparse's usage message on stderr and exit with code 2.
Each place includes `osm_id`, `name`, `latitude`, `longitude`, `website`,
`instagram`, `facebook`, `email`, `phone`, `address`, `google_maps_url`, and `distance_m`.
Missing fields are `null`; `contact:*` tags take precedence over their unprefixed
equivalents. Addresses use `addr:full` when available, otherwise street/house
number, city, postcode, and country tags. Outline coordinates come from
Overpass's `center` output. Google Maps links search for the business name,
address and coordinates. Existing direct Google business links are preserved;
unnamed places fall back to their address or coordinates. A name search depends
on Google's matching and cannot guarantee a specific listing without a Place ID.

Contact fields are checked before enrichment and contact filtering. Mislabelled
Facebook, Instagram, email, business website and Google Maps links move to their
correct fields. Valid dedicated fields take priority over relocated links.
Malformed URLs, social sharing/login links, and unsupported social platforms
are excluded from contact fields. The same checks apply to PDF input.

Results are sorted nearest first using straight-line distance from the resolved
search center, in meters. Places without coordinates appear last. Use
`--sort source` to preserve Overpass order. Repeated `--has-contact` options
require **any** selected field (OR), after website enrichment and name filtering:

```shell
gmscrap --center "Lviv, Ukraine" --category "coffee shop" --radius 5000 --has-contact email --has-contact instagram
gmscrap --center "49.8415,24.0315" --category cafe --radius 5000 --has-contact email --format csv > places.csv
```

`--format csv` exports one venue per row, with the same fields as JSON and a
header even for empty results. CSV uses standard quoting for commas and newlines;
text starting with spreadsheet formula characters is prefixed with an apostrophe.
When redirecting on Windows, use UTF-8 output encoding to preserve venue names.

Website enrichment is enabled by default. For venues with a website and missing
contacts, it reads the homepage and at most one linked Contact page on the same
host, recognizing English contact labels. It extracts
`mailto:` links, visible email addresses, and Instagram/Facebook profile links,
while preserving existing OSM contacts. Requests use 3-second connection and
5-second read timeouts, a 1 MB decoded response limit, and at most three redirects
per page. Non-HTML responses, failed requests, and invalid links are skipped;
private/local destinations are rejected before each request. This uses static
HTML, so JavaScript-only and obfuscated contacts may remain missing. Enrichment
adds sequential website requests; use `--no-enrich-website` for OSM-only searches.
Each page and its redirects have a 10-second network budget. The search stops
starting new venue enrichments after 30 seconds, keeping the remaining OSM
results. An in-progress venue may finish after that threshold; operating-system
DNS lookup time is outside the socket deadline. Identical website/contact
combinations reuse enrichment within the same search. HTTP charset declarations
take precedence over HTML meta declarations, with UTF-8 as the fallback.
Connections use validated public IPs while retaining the website hostname for
TLS verification and HTTP routing; environment HTTP proxies are not used for
enrichment.

The coordinate example sends this query, which can also be run in
[Overpass Turbo](https://overpass-turbo.eu/):

```overpassql
[out:json][timeout:25];
nwr["amenity"="cafe"](around:5000,49.8415,24.0315);
out center;
```

Python API: `ScrapHandler(ScrapService()).search(center, category, radius_m, name=None)`
returns a JSON string. `ScrapService` accepts a custom Overpass `endpoint` and
`user_agent`. City lookups use a 10-second timeout and are spaced at least one
second apart within a service instance; reuse the instance for repeated lookups.
The HTTP API shares one geocoder and limiter per app process. Run a single API
worker when using the public Nominatim service, or coordinate throttling across
workers externally.
Overpass requests use a 10-second connection timeout and a 35-second read timeout.

The Python search method also accepts keyword-only `contacts=("email", "instagram")`,
`sort_by_distance=True`, and `enrich_website=True`. The HTTP `GET /search` endpoint
accepts repeated `has_contact=email&has_contact=instagram`, `sort=distance|source`,
`enrich_website=true|false`, and `format=json|csv` query parameters.

References: [Overpass QL](https://wiki.openstreetmap.org/wiki/Overpass_API/Overpass_QL),
[geopy / Nominatim](https://geopy.readthedocs.io/en/stable/),
[OSM contact tags](https://wiki.openstreetmap.org/wiki/Key:contact).

## Python style and tests

Shared rules live in `pyproject.toml` and `.editorconfig`: four-space indentation,
88-character lines, double quotes, and sorted imports. Use `snake_case` for
modules, functions and variables, `PascalCase` for classes, and type annotations
for method signatures. Protocol methods use `...` bodies.

Install development tools in the project virtual environment:

```shell
python -m pip install -r requirements-dev.txt
```

Apply import and formatting corrections:

```shell
python -m ruff check --fix .
python -m ruff format .
```

Run tests, lint and formatting checks from PowerShell:

```powershell
.\.venv\Scripts\python.exe run_tests.py
```

The runner adds `src` to the import path, uses the current interpreter, and runs
every check even if an earlier one fails. Exit code 0 means all checks passed;
1 means at least one failed. It does not modify files. An absolute path to
`run_tests.py` also works from another directory.

Tests replace public Overpass and Nominatim calls with controlled responses.
They cover validation, categories, contacts, name filtering, geocoding, network
failures, malformed JSON, CLI behavior and runner exit codes. Transport tests
use local HTTP and HTTPS servers; external service availability is not tested.

Run tests only:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

## Optional PDF export

Export the JSON results with the separate PDF handler, service, and CLI. See [PDF export](docs/PDF.md) for installation, usage, font setup, and the Python API.

## Optional HTTP API and PDF storage

Install `.[api,pdf]` to serve search, PDF generation, and SQLite PDF storage:

```shell
python -m pip install ".[api,pdf]"
uvicorn my_package.api:app --host 127.0.0.1 --port 8000
```

See [API setup](docs/API.md) for endpoints and deployment settings, and
[PDF storage](docs/PDF_STORAGE.md) for persistence behavior. The API has no
built-in authentication; the default command binds to localhost.
