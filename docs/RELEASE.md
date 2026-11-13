# Release 0.1.0

This is the first packaged release. It includes:

- OSM place search by coordinates or city, categories, radius, and name fragment.
- JSON/CSV export with phone, email, social profiles, addresses, Maps links, and distance.
- Bounded website contact enrichment with verified HTTPS and public-IP validation.
- Optional offline PDF export with English labels and clickable contact links.
- Optional FastAPI endpoints for search, PDF generation, and SQLite PDF storage.
- The Python API and original kilometer-based handler for compatibility.
- Source-tag screening for named, contactable cafe businesses, with documented
  contact-review exclusions and a separate audit file.

Release checks also cover the issues found during manual validation: unusable
contact values are rejected, protocol-relative contacts remain clickable in
PDFs, and the business filter validates its input and reviews. Filter outputs
must use distinct paths, are staged before replacement, and are restored if a
later file replacement fails. Invalid input returns a JSON error without
overwriting existing results.

## Supported runtime and entry points

Python 3.14 is required (`>=3.14,<3.15`); the container and CI target 3.14.10.
Install the wheel or checkout before using the console script or root launcher:

```shell
python -m pip install .
gmscrap --version
gmscrap --center "49.8415, 24.0315" --category cafe --radius 5000
python -m my_package --help
python main.py --help
```

The source package name `my_package` remains for API compatibility; the installed
distribution and console command are named `gmscrap`. All entry points share
`my_package.main.main`. Exit codes are 0 for success/help/version, 1 for search
errors, 2 for CLI syntax errors, and 130 for an interrupted search.

## Build and validate locally

Install the pinned development/build requirements in your project environment,
then run one release command:

```shell
python -m pip install -r requirements-dev.txt
python scripts/release.py
```

With the existing Makefile, `make install` followed by `make release` is equivalent.
The release command runs all tests, lint and formatting checks, checks installed
dependency consistency, builds an sdist, builds its wheel from that sdist, and
installs the wheel in a temporary clean environment. It verifies both console
commands and a controlled search away from the source directory without
`PYTHONPATH`. It then installs the API/PDF extras and pinned test dependencies,
checks Uvicorn, and runs the source archive's complete test suite against the
installed wheel. Missing test files or TLS fixtures fail release validation.
PDF checks need Arial on Windows/macOS or DejaVu Sans/Liberation Sans on Linux;
install `fonts-dejavu-core` on minimal Linux hosts. CI installs that font explicitly.
Network access is needed to install dependencies; smoke searches use a mocked
provider. Only validated artifacts are copied to `dist/`:

- `gmscrap-0.1.0-py3-none-any.whl`
- `gmscrap-0.1.0.tar.gz`
- `SHA256SUMS` for this build's wheel and source archive

Unrelated existing files in `dist/` are preserved. The script does not publish,
create tags, or modify Git history. Artifact hashes describe the generated files;
archive timestamps may differ between builds.

`make all` additionally verifies production and test containers. The production
container installs the built wheel and starts its console command. CI repeats
package validation on Windows and Linux, runs the container checks, and retains
the artifacts for download. CI actions and packaging dependencies are pinned;
hosted runner OS labels receive upstream updates.

## Release procedure

1. Set the version in `src/my_package/_version.py`. Keep the Compose image tags
   and these release notes aligned. Package metadata and `--version` derive from
   that single Python version value.
2. Run `make release` and `make all`, and review the generated artifacts and CI.
3. Review and commit the intended source changes. Create the matching release tag
   and upload the validated artifacts to the chosen release destination when
   publishing is authorized.

Live searches depend on Overpass/Nominatim availability and OSM data completeness.
Website enrichment reads static HTML and can be disabled with `--no-enrich-website`.
Its DNS and timing limits are documented in the README. The shipped container
runs the search CLI; API and PDF deployment instructions are in [API.md](API.md)
and [PDF.md](PDF.md). The API binds to localhost by default and has no built-in
authentication. Use one worker with public Nominatim, or coordinate throttling
externally. SQLite PDF storage requires a writable database directory.
