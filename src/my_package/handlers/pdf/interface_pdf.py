from pathlib import Path
from typing import Protocol


class IPdfHandler(Protocol):
    def generate(
        self, payload: str, output: str | Path, *, location: str | None = None
    ) -> Path: ...
