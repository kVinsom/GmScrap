from my_package.domain.models import Coordinates
from my_package.handlers.respon.interface_respon import IErrorResponse
from my_package.handlers.respon.respon import ErrorResponse
from my_package.services.interface_scrap import IScrapService


class ScrapHandler:
    def __init__(
        self, service: IScrapService, error_response: IErrorResponse | None = None
    ) -> None:
        self.service = service
        self.error_response: IErrorResponse = (
            ErrorResponse() if error_response is None else error_response
        )

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
    ) -> str:
        return self.service.search(
            center,
            category,
            radius_m,
            name,
            contacts=contacts,
            sort_by_distance=sort_by_distance,
            enrich_website=enrich_website,
        )

    def scrape(self, geo: str, key_word: str, radius_in_km: int) -> str:
        if not isinstance(geo, str):
            raise self.error_response.geo_type_error()
        coordinates = geo.split(",")
        if len(coordinates) != 2:
            raise self.error_response.geo_format_error()
        try:
            latitude, longitude = (float(value.strip()) for value in coordinates)
        except ValueError as error:
            raise self.error_response.geo_coordinates_error() from error
        try:
            Coordinates(latitude, longitude)
        except ValueError as error:
            raise self.error_response.geo_range_error() from error

        if not isinstance(key_word, str):
            raise self.error_response.key_word_type_error()
        if any(not word.strip() for word in key_word.split(",")):
            raise self.error_response.key_word_empty_error()

        if isinstance(radius_in_km, bool) or not isinstance(radius_in_km, int):
            raise self.error_response.radius_type_error()
        if radius_in_km <= 0:
            raise self.error_response.radius_value_error()

        return self.service.scrape(geo, key_word, radius_in_km)

    def save_pdf(self, name: str, content: bytes) -> None:
        self.service.save_pdf(name, content)

    def delete_pdf(self, name: str) -> bool:
        return self.service.delete_pdf(name)

    def get_pdf(self, name: str) -> bytes | None:
        return self.service.get_pdf(name)

    def get_all_pdfs(self) -> dict[str, bytes]:
        return self.service.get_all_pdfs()
