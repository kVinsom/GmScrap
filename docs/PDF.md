# PDF export

PDF export is a separate, offline consumer of the scraper's JSON. It does not
modify the search CLI, scraping services, domain models, or network adapters.

Install the optional renderer (ReportLab and its Pillow dependency):

```console
pip install ".[pdf]"
```

Export an existing UTF-8 JSON file:

```console
gmscrap-pdf places.json places.pdf --location "Lviv, Ukraine"
```

The equivalent module command also works without reinstalling the console script:

```console
python -m my_package.pdf_main places.json places.pdf --location "Lviv, Ukraine"
```

Use `-` as the input filename to read JSON from stdin. File input accepts a UTF-8
BOM, including files produced by PowerShell. Use UTF-8 when redirecting scraper
output to disk. The destination directory must already exist.

Each place gets a name, location, coordinates, Google Maps link, and a contact
table with phone, email, website, Facebook, and Instagram. Records are separated by a
horizontal rule and move onto the next A4 page when needed. Long text wraps.
Missing values appear as `Not provided`; missing names appear as `Unnamed place`.

Input is the existing top-level JSON array with `name`, `latitude`, `longitude`,
`website`, `facebook`, `instagram`, `email`, `phone`, and `address`. An optional string
field `location` can also be supplied. Optional `google_maps_url` and
`google_place_id` fields preserve direct business links or identify a Google
listing. Otherwise, "Show on Google Maps" searches by business name, address and
coordinates; Google's matching determines which listing opens. An unnamed
record can only fall back to its address or coordinates.

Contact URLs are classified independently of their input field. Misplaced links
move to the correct contact row; invalid URLs and social sharing/login links
are removed. Address takes priority over per-record location,
then `--location`. No reverse geocoding or contact discovery is performed.

Unicode text uses an embedded TrueType font. The exporter automatically finds
Arial on Windows/macOS or DejaVu Sans/Liberation Sans on Linux. On minimal Linux
systems install `fonts-dejavu-core`, or pass `--font /path/to/DejaVuSans.ttf`.
Custom fonts must support the text's characters. Fonts are not redistributed in
this package. Containers using the base application's image need the optional
PDF extra and a Unicode font installed separately.

Python API (the handler accepts the string returned by `ScrapHandler.search`):

```python
from my_package.handlers.pdf.pdf import PdfHandler
from my_package.services.pdf import PdfService

PdfHandler(PdfService()).generate(result_json, "places.pdf", location="Lviv, Ukraine")
```

`IPdfHandler` and `IPdfService` define injectable boundaries. ReportLab is loaded
only when generating a PDF; the base application has no new mandatory dependency.
Export runs synchronously, with no browser, server, workers, or network requests.
JSON and document layout are held in memory, so memory grows with the input list.
The destination is replaced atomically after successful rendering.

Install `requirements-dev.txt`, then run `python run_tests.py` for all checks.
The runner fails if API/PDF test dependencies are missing. Direct unittest
discovery can skip optional integration tests when their dependencies are absent.
PDF inspection tools are development-only.
