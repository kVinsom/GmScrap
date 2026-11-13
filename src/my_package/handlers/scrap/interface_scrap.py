from typing import Protocol


class IScrapHandler(Protocol):
    def save_pdf(self, name: str, content: bytes) -> None: ...

    def delete_pdf(self, name: str) -> bool: ...

    def get_pdf(self, name: str) -> bytes | None: ...

    def get_all_pdfs(self) -> dict[str, bytes]: ...

    def scrape(self, geo: str, key_word: str, radius_in_km: int) -> str: ...

    def search(
        self,
        center: str,
        category: str,
        radius_m: int,
        name: str | None = None,
        *,
        contacts: tuple[str, ...] = (),
        sort_by_distance: bool = True,
        enrich_website: bool = True,
    ) -> str: ...
