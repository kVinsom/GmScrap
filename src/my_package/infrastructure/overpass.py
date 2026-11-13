"""HTTP adapter for the place-source port."""

import requests

from my_package.domain.errors import OverpassError
from my_package.domain.models import Coordinates, Place, SearchRequest
from my_package.infrastructure.osm import build_query, parse_response


class OverpassPlaceSource:
    def __init__(
        self,
        endpoint: str = "https://overpass-api.de/api/interpreter",
        user_agent: str = "GmScrap/0.1",
    ) -> None:
        self.endpoint = endpoint
        self.user_agent = user_agent

    def search(self, request: SearchRequest, center: Coordinates) -> list[Place]:
        try:
            response = requests.post(
                self.endpoint,
                data={"data": build_query(request, center)},
                headers={"User-Agent": self.user_agent},
                timeout=(10, 35),
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as error:
            raise OverpassError(f"Overpass request failed: {error}") from error
        return parse_response(payload)
