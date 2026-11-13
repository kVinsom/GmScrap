"""SQLite storage of named PDF files, using only the standard library."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path


class ScrapRepository:
    def __init__(self, database: str | Path = "pdfs.sqlite3") -> None:
        self.database = database

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.database)
        try:
            with connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS pdf_files ("
                    "name TEXT PRIMARY KEY NOT NULL, content BLOB NOT NULL)"
                )
                yield connection
        finally:
            connection.close()

    def save_pdf(self, name: str, content: bytes) -> None:
        with self._connection() as connection:
            try:
                connection.execute(
                    "INSERT INTO pdf_files (name, content) VALUES (?, ?)",
                    (name, content),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(f"A PDF named {name!r} already exists.") from error

    def delete_pdf(self, name: str) -> bool:
        with self._connection() as connection:
            return (
                connection.execute(
                    "DELETE FROM pdf_files WHERE name = ?", (name,)
                ).rowcount
                > 0
            )

    def get_pdf(self, name: str) -> bytes | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT content FROM pdf_files WHERE name = ?", (name,)
            ).fetchone()
        return None if row is None else row[0]

    def get_all_pdfs(self) -> dict[str, bytes]:
        with self._connection() as connection:
            return dict(
                connection.execute("SELECT name, content FROM pdf_files ORDER BY name")
            )
