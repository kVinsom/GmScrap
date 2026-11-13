# Release 0.1.0 validation

The release candidate was checked on Windows with the configured Python 3.14
environment and in the pinned Python 3.14.10 Linux container.

## Results

| Check | Result |
| --- | --- |
| Regression suite on Windows | 145 tests passed |
| Regression suite in Linux Docker | 145 tests passed |
| Lint and formatting on both platforms | Passed |
| Manual CLI and HTTP boundary session | 95 checks passed |
| Production image help and version | Passed; version 0.1.0 |
| Docker Compose configuration | Passed |

The manual session used actual CLI subprocesses and a real localhost Uvicorn
server. A temporary driver supplied controlled HTTP responses for Overpass,
geocoding and website enrichment. This made option results repeatable without
depending on external services. It was separate from the unittest suite.

The session exercised every search CLI option, all category aliases, combined
categories, coordinate and city centers, name filtering, contact filters and OR
matching, both sort modes, JSON/CSV, enrichment, and validation errors. PDF checks
covered files, stdin, empty results, location/font options, missing directories,
invalid input and clickable contacts. Business-filter checks covered reviews,
malformed input, output collisions and failed audit writes. Real HTTP checks
covered search options, strict request validation, PDF generation, upload,
retrieval, Base64 collection contents, duplicate names, deletion and missing
files, including Unicode names and names containing slashes.

## Failures resolved before packaging

Eight failed manual checks led to fixes for protocol-relative PDF links,
unusable contact values, malformed filter input, invalid contact reviews,
conflicting output paths and partial output writes. Regression tests cover
staging failures and rollback after a second file replacement fails.

Disabling input validation, review validation, safe file writes or PDF link
handling made their regressions fail. Existing tests retain real HTTP/HTTPS
socket coverage, TLS deadlines, certificate verification and IPv6 fallback.

## Packaging gate and limits

`python scripts/release.py` runs the suite and style checks, builds the wheel from
the source archive, validates archive contents, and tests the installed wheel in
a clean environment with API/PDF extras. It copies artifacts into `dist/` only
after validation and writes `SHA256SUMS` for those exact files.

The separate public-provider smoke search received an Overpass HTTP 502 error;
the CLI returned its documented structured error and nonzero exit status.
External Overpass/Nominatim availability and OSM data accuracy are not guaranteed
by the controlled checks. Business screening uses source tags and available
contacts, rather than independent confirmation of current trading status.
Google Maps selects a named search result unless a direct business identifier
is supplied. GNU Make was unavailable on the Windows host, so the equivalent
Python and Docker commands were used.

No Git tag, remote publication or release upload is performed by validation.
