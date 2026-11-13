# Search architecture

The search uses ports and adapters with a small application layer. It keeps
provider details out of search orchestration and keeps JSON at the public API
boundary. Search queries external data; the separate PDF storage feature uses
`repositories/scrap.py` for SQLite persistence.

```text
main (CLI)
  -> ScrapHandler (public handler, legacy validation)
    -> ScrapService (compatibility facade and default dependency composition)
      -> SearchPlaces (application use case)
        -> Geocoder port     <- NominatimGeocoder adapter
        -> PlaceSource port  <- OverpassPlaceSource adapter
                                 -> OSM query builder / response mapper
        -> ContactEnricher port <- WebsiteContactEnricher adapter

Domain models and errors are shared by the use case and adapters.
```

## Responsibilities

| Module | Responsibility |
| --- | --- |
| `domain/models.py` | Immutable `SearchRequest`, `Coordinates`, and `Place`; input validation and category mapping |
| `domain/errors.py` | Errors exposed at provider boundaries |
| `application/ports.py` | Structural protocols for geocoding, place lookup, and contact enrichment |
| `application/search.py` | Resolve center, filter names, enrich contacts, filter contact presence, compute Maps links and distance, sort |
| `infrastructure/geocoding.py` | Lazy Nominatim initialization, throttling, geopy error translation |
| `infrastructure/overpass.py` | HTTP requests, timeouts, status and JSON errors |
| `infrastructure/osm.py` | Pure query generation and validation/mapping of OSM responses |
| `infrastructure/website.py` | Bounded homepage/contact-page requests and static HTML extraction; preserve existing contacts |
| `export.py` | CSV serialization for CLI and HTTP results |
| `services/scrap.py` | Wire default adapters, expose the existing string API, serialize places to JSON |
| `handlers/scrap/scrap.py` | Delegate modern searches and retain the original handler's validation/error factory contract |
| `main.py` | Parse arguments, write stdout/stderr, select the process exit code |

## Dependency rules

The domain imports only the standard library and other domain modules.
The application depends on domain models and its own protocols, never concrete
network clients. Adapters depend on domain models and their external libraries.
The facade is the composition boundary that chooses the default implementations.
Protocols use structural typing, so adapters do not need to inherit from them.

`tests/test_architecture.py` checks these import boundaries. Unit tests exercise
the application through injected ports; adapter and CLI tests mock external
services. All checks run through `run_tests.py` or `make check`.

## Public API and extension points

`ScrapService.search(center, category, radius_m, name=None)` still returns JSON.
`scrape(geo, key_word, radius_in_km)` retains its kilometer conversion, and the
handler keeps its injectable `IErrorResponse` behavior. Shared coordinate range
validation lives in the `Coordinates` value object. `GeocodingError` and
`OverpassError` are still re-exported from `services.scrap` for existing callers.

For typed results, call `SearchPlaces.execute(SearchRequest(...))`; it returns
`list[Place]`. To use another provider or an in-memory test double, inject
`geocoder=` and/or `place_source=` into `ScrapService`, or pass both ports directly
to `SearchPlaces`. No service locator or global client state is involved.

Input validation completes before either port is called. Providers raise explicit
errors; an empty list means a successful search. The Overpass mapper validates the
entire response before name filtering so a malformed response cannot silently
become an empty success. Website enrichment fills only missing contacts and treats
website failures as best-effort; contacts still unavailable remain null.
Inject `contact_enricher=` into the service/use case to replace website extraction.
`enrich_website=False` disables this step. Contact filters use OR semantics and
distance sorting is stable, with missing coordinates last; distances are straight
line meters. The service returns enriched fields as JSON; the CLI and HTTP boundary
also offer CSV export.

The old `handlers/respon` and interface module paths remain in place for callers
that already import them. New domain and application modules use descriptive
names without requiring a breaking package rename.
