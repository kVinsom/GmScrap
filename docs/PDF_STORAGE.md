# PDF storage

SQLite stores PDFs as BLOBs in a local database, with no additional dependencies.
The four methods are available on `ScrapHandler`, `ScrapService`, and
`ScrapRepository`. Existing scraping and PDF generation methods are unchanged.

```python
from pathlib import Path

from my_package.handlers.scrap.scrap import ScrapHandler
from my_package.repositories.scrap import ScrapRepository
from my_package.services.scrap import ScrapService

handler = ScrapHandler(ScrapService(repository=ScrapRepository("pdfs.sqlite3")))
handler.save_pdf("lviv-cafes", Path("places.pdf").read_bytes())
content = handler.get_pdf("lviv-cafes")
files = handler.get_all_pdfs()
deleted = handler.delete_pdf("lviv-cafes")
```

- `save_pdf(name, content)` inserts PDF bytes and returns `None`. Duplicate names
  raise `ValueError` and preserve the existing file.
- `get_pdf(name)` returns the bytes or `None` if absent.
- `get_all_pdfs()` returns a dictionary of names to PDF bytes, ordered by name.
- `delete_pdf(name)` returns whether a record was deleted.

Names are nonempty, case-sensitive strings and serve as the unique primary key;
they need not end in `.pdf`. Content must be bytes beginning with `%PDF-` (a header
check, not full PDF validation). SQL uses bound parameters.

By default, the database is `pdfs.sqlite3` in the working directory. A custom
database file can be injected as above; its parent directory must exist. The
database and table are created on the first storage operation, so searches alone
create no database. Connections are closed after each operation. Use a disk file,
not SQLite's `:memory:` database, to retain data between operations. Getting all
files loads all their contents into memory.
