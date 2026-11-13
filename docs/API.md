# FastAPI HTTP API

Install and run from the project environment:

```console
pip install ".[api,pdf]"
uvicorn my_package.api:app --host 127.0.0.1 --port 8000
```

Interactive documentation: `http://127.0.0.1:8000/docs`.
OpenAPI schema: `http://127.0.0.1:8000/openapi.json`.
This live schema supersedes the older proposed Swagger adapter document.

| Method | Path | Input | Result |
| --- | --- | --- | --- |
| GET | `/search` | Query: `center`, `category`, `radius_m`; optional filters and format below | JSON array or CSV |
| POST | `/scrap` | JSON: `geo`, `key_word`, `radius_in_km` | Legacy search as a JSON array |
| POST | `/pdfs/generate` | JSON: `places` array, optional `location` | Generated `application/pdf` download |
| POST | `/pdfs?name=unique-name` | Raw bytes, `Content-Type: application/pdf` | 201 with saved name |
| GET | `/pdfs` | None | All files as `{name, content_base64}` objects |
| GET | `/pdfs/{name}` | URL-encoded unique name | `application/pdf` download |
| DELETE | `/pdfs/{name}` | URL-encoded unique name | 204, empty body |

`/search` also accepts `name`, repeated `has_contact` values (`email`, `instagram`,
`facebook`, `website`, `phone`) with OR matching, `sort=distance|source`,
`enrich_website=true|false`, and `format=json|csv`. Defaults are distance sorting,
website enrichment enabled, and JSON output.

Example legacy search body:

```json
{"geo": "49.8419,24.0315", "key_word": "cafe", "radius_in_km": 2}
```

Pass the search result array as `places` to `/pdfs/generate`. Generation returns
the PDF without storing it. To save it, upload its bytes to `POST /pdfs` with a
unique name. The PDF upload uses raw bytes, so multipart dependencies are not
needed. Get-all returns every file's bytes as Base64, so response size grows with
the stored collection. URL names can contain Unicode or slashes and are never
used as filesystem paths.

Errors return JSON with `detail`: 400 for handler validation, 422 for request
schema validation, 404 for missing PDFs, 409 for duplicate names, 502 for search
provider failures, and 503 for unavailable SQLite storage or PDF renderer.
Unexpected errors use the server's normal 500 response.

Set `GMSCRAP_DATABASE` to change the default `pdfs.sqlite3` location; its parent
directory must exist. Set `GMSCRAP_PDF_FONT` to a Unicode-capable TrueType font
if needed. See `PDF.md` for font setup. `create_app(database=...)` supports an
isolated storage path in tests or embedded deployments. Handler dependencies
can be replaced with FastAPI's dependency overrides.

The API is optional: the existing CLI, handlers, services, and repository keep
their behavior. Install just `.[api]` if PDF generation is not needed. No database
is created at import time. Blocking handler operations run in FastAPI's worker
threads. The default launch binds to localhost and has no authentication layer.

Use a single worker with public Nominatim, or coordinate request throttling
across workers. Website and search timing limits are documented in the README.

For offline checks install `requirements-dev.txt`, then run `python run_tests.py`.
The runner requires all API/PDF test dependencies; direct unittest discovery
can skip API tests when FastAPI or HTTPX is absent.
