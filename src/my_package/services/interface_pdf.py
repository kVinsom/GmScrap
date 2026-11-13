"""Port for a PDF writer, independent of the scraping service."""

from pathlib import Path
from typing import Protocol


class IPdfService(Protocol):
    def generate(
        self, places: list[dict], output: Path, *, location: str | None = None
    ) -> Path: ...
