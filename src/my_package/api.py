"""Optional FastAPI boundary for the existing handlers."""

import base64
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from my_package import __version__
from my_package.domain.errors import GeocodingError, OverpassError
from my_package.export import results_csv
from my_package.handlers.pdf.pdf import PdfHandler
from my_package.handlers.scrap.scrap import ScrapHandler
from my_package.infrastructure.geocoding import NominatimGeocoder
from my_package.repositories.scrap import ScrapRepository
from my_package.services.pdf import PdfService
from my_package.services.scrap import ScrapService


class ScrapRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    geo: str
    key_word: str
    radius_in_km: int = Field(gt=0)


class GeneratePdfRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    places: list[dict]
    location: str | None = None


class StoredPdf(BaseModel):
    name: str
    content_base64: str


class PdfResponse(Response):
    media_type = "application/pdf"


def get_scrap_handler(request: Request) -> ScrapHandler:
    return ScrapHandler(
        ScrapService(
            repository=ScrapRepository(request.app.state.database),
            geocoder=request.app.state.geocoder,
        )
    )


def get_pdf_handler() -> PdfHandler:
    return PdfHandler(PdfService(font_path=os.environ.get("GMSCRAP_PDF_FONT")))


ScrapDependency = Annotated[ScrapHandler, Depends(get_scrap_handler)]
PdfDependency = Annotated[PdfHandler, Depends(get_pdf_handler)]


def create_app(database: str | Path | None = None) -> FastAPI:
    app = FastAPI(title="GmScrap API", version=__version__)
    app.state.geocoder = NominatimGeocoder()
    app.state.database = (
        database
        if database is not None
        else os.environ.get("GMSCRAP_DATABASE", "pdfs.sqlite3")
    )

    @app.exception_handler(ValueError)
    @app.exception_handler(TypeError)
    async def invalid_input(request: Request, error: Exception):
        return JSONResponse(status_code=400, content={"detail": str(error)})

    @app.exception_handler(GeocodingError)
    @app.exception_handler(OverpassError)
    async def upstream_error(request: Request, error: Exception):
        return JSONResponse(status_code=502, content={"detail": str(error)})

    @app.exception_handler(sqlite3.Error)
    async def database_error(request: Request, error: Exception):
        return JSONResponse(
            status_code=503, content={"detail": "PDF storage unavailable."}
        )

    @app.get("/search", response_model=list[dict], tags=["Search"])
    def search(
        handler: ScrapDependency,
        center: str,
        category: str,
        radius_m: Annotated[int, Query(gt=0)],
        name: str | None = None,
        has_contact: Annotated[
            list[Literal["email", "instagram", "facebook", "website", "phone"]] | None,
            Query(),
        ] = None,
        sort: Literal["distance", "source"] = "distance",
        enrich_website: bool = True,
        format: Literal["json", "csv"] = "json",
    ):
        places = json.loads(
            handler.search(
                center,
                category,
                radius_m,
                name,
                contacts=tuple(has_contact or ()),
                sort_by_distance=sort == "distance",
                enrich_website=enrich_website,
            )
        )
        if format == "csv":
            return Response(
                results_csv(places),
                media_type="text/csv",
                headers={"Content-Disposition": 'attachment; filename="places.csv"'},
            )
        return places

    @app.post("/scrap", response_model=list[dict], tags=["Search"])
    def scrap(body: ScrapRequest, handler: ScrapDependency):
        return json.loads(handler.scrape(body.geo, body.key_word, body.radius_in_km))

    @app.post("/pdfs/generate", response_class=PdfResponse, tags=["PDF"])
    def generate_pdf(body: GeneratePdfRequest, handler: PdfDependency):
        with tempfile.TemporaryDirectory(prefix="gmscrap-pdf-") as directory:
            output = Path(directory) / "places.pdf"
            try:
                handler.generate(
                    json.dumps(body.places), output, location=body.location
                )
            except RuntimeError as error:
                raise HTTPException(status_code=503, detail=str(error)) from error
            content = output.read_bytes()
        return PdfResponse(
            content,
            headers={"Content-Disposition": 'attachment; filename="places.pdf"'},
        )

    @app.post("/pdfs", status_code=201, tags=["PDF"])
    def save_pdf(
        handler: ScrapDependency,
        name: Annotated[str, Query(min_length=1)],
        content: Annotated[bytes, Body(media_type="application/pdf")],
    ) -> dict[str, str]:
        try:
            handler.save_pdf(name, content)
        except ValueError as error:
            if isinstance(error.__cause__, sqlite3.IntegrityError):
                raise HTTPException(status_code=409, detail=str(error)) from error
            raise
        return {"name": name}

    @app.get("/pdfs", response_model=list[StoredPdf], tags=["PDF"])
    def get_all_pdfs(handler: ScrapDependency):
        return [
            StoredPdf(
                name=name, content_base64=base64.b64encode(content).decode("ascii")
            )
            for name, content in handler.get_all_pdfs().items()
        ]

    @app.get("/pdfs/{name:path}", response_class=PdfResponse, tags=["PDF"])
    def get_pdf(name: str, handler: ScrapDependency):
        content = handler.get_pdf(name)
        if content is None:
            raise HTTPException(status_code=404, detail="PDF not found.")
        return PdfResponse(
            content,
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name, safe='')}"
            },
        )

    @app.delete("/pdfs/{name:path}", status_code=204, tags=["PDF"])
    def delete_pdf(name: str, handler: ScrapDependency) -> Response:
        if not handler.delete_pdf(name):
            raise HTTPException(status_code=404, detail="PDF not found.")
        return Response(status_code=204)

    return app


app = create_app()
