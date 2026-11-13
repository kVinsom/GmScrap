"""Optional local PDF renderer. ReportLab is loaded only during export."""

import hashlib
import os
import tempfile
from pathlib import Path
from urllib.parse import quote, urlsplit
from xml.sax.saxutils import escape, quoteattr

from my_package.domain.links import (
    CONTACT_FIELDS,
    business_maps_url,
    normalize_contacts,
)

MISSING = "Not provided"


def _link(value: str, kind: str) -> str | None:
    """Allow only web/mail links, never executable or local-file schemes."""
    value = value.strip()
    if not value:
        return None
    if kind == "email":
        return "mailto:" + quote(value, safe="@.+")
    if kind == "phone":
        return "tel:" + quote(value, safe="+")
    if value.startswith("//"):
        value = "https:" + value
    elif ":" not in value:
        if (
            kind in {"facebook", "instagram"}
            and "/" not in value
            and not value.endswith(".com")
        ):
            value = f"{kind}.com/{value.lstrip('@')}"
        elif kind == "instagram" and value.startswith("@"):
            value = f"instagram.com/{value[1:]}"
        value = "https://" + value
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if parts.scheme.lower() not in {"https", "http"} or not parts.netloc:
        return None
    return quote(value, safe=":/?&=#%@+;,~!$()*[]")


def _font_path(explicit: Path | None) -> Path:
    if explicit is not None:
        if not explicit.is_file():
            raise ValueError(f"Font file does not exist: {explicit}")
        return explicit
    candidates = (
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/arial.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    )
    for path in candidates:
        if path.is_file():
            return path
    raise RuntimeError("No Unicode font found. Pass --font /path/to/DejaVuSans.ttf.")


class PdfService:
    def __init__(self, *, font_path: str | Path | None = None) -> None:
        self.font_path = Path(font_path) if font_path is not None else None

    def generate(
        self, places: list[dict], output: Path, *, location: str | None = None
    ) -> Path:
        try:
            from reportlab.lib import colors
            from reportlab.lib.enums import TA_LEFT
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import ParagraphStyle
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFError, TTFont
            from reportlab.platypus import (
                HRFlowable,
                KeepTogether,
                Paragraph,
                SimpleDocTemplate,
                Spacer,
                Table,
                TableStyle,
            )
        except ImportError as error:
            raise RuntimeError(
                'Install PDF support with: pip install ".[pdf]"'
            ) from error

        path = _font_path(self.font_path)
        font = (
            "GmScrap-" + hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:16]
        )
        if font not in pdfmetrics.getRegisteredFontNames():
            try:
                pdfmetrics.registerFont(TTFont(font, str(path)))
            except (TTFError, OSError) as error:
                raise ValueError(f"Cannot load TrueType font: {path}") from error
        body = ParagraphStyle(
            "body",
            fontName=font,
            fontSize=10,
            leading=15,
            alignment=TA_LEFT,
            splitLongWords=True,
        )
        title = ParagraphStyle(
            "title", parent=body, fontSize=15, leading=20, spaceAfter=9
        )
        heading = ParagraphStyle("heading", parent=body, fontSize=11, spaceAfter=5)

        def paragraph(value: str, style=body, target: str | None = None):
            # Scraped strings are text, never ReportLab's XML-like markup.
            text = escape(value).replace("\n", "<br/>")
            if target:
                text = f'<link href={quoteattr(target)} color="#245b88">{text}</link>'
            return Paragraph(text, style)

        story = []
        for place in places:
            place = dict(
                place,
                **normalize_contacts((key, place.get(key)) for key in CONTACT_FIELDS),
            )
            block = [
                HRFlowable(
                    width="100%", thickness=0.6, color=colors.HexColor("#aaaaaa")
                ),
                Spacer(1, 13),
                paragraph(place.get("name") or "Unnamed place", title),
                paragraph("Location", heading),
                paragraph(
                    place.get("address") or place.get("location") or location or MISSING
                ),
            ]
            lat, lon = place.get("latitude"), place.get("longitude")
            if lat is not None and lon is not None:
                block.append(paragraph(f"Coordinates {lat}, {lon}"))
            else:
                block.append(paragraph(f"Coordinates: {MISSING}"))
            maps_url = business_maps_url(
                place.get("name"),
                lat,
                lon,
                place.get("address") or place.get("location") or location,
                existing=place.get("google_maps_url"),
                place_id=place.get("google_place_id"),
            )
            if maps_url:
                block.append(paragraph("Show on Google Maps", target=maps_url))
            block.extend([Spacer(1, 12), paragraph("Contacts", heading)])
            rows = []
            for label, key in (
                ("Phone", "phone"),
                ("Email", "email"),
                ("Website", "website"),
                ("Facebook", "facebook"),
                ("Instagram", "instagram"),
            ):
                value = place.get(key) or MISSING
                rows.append(
                    [
                        paragraph(label),
                        paragraph(
                            value,
                            target=_link(value, key) if value != MISSING else None,
                        ),
                    ]
                )
            table = Table(
                rows, colWidths=[125, A4[0] - 221], hAlign="LEFT", splitInRow=1
            )
            table.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                        ("TOPPADDING", (0, 0), (-1, -1), 2),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                    ]
                )
            )
            block.extend([table, Spacer(1, 20)])
            story.append(KeepTogether(block))
        if places:
            story.append(
                HRFlowable(
                    width="100%", thickness=0.6, color=colors.HexColor("#aaaaaa")
                )
            )
        else:
            story.append(paragraph("No places found."))

        output = Path(output)
        # Build beside the destination and replace only after successful rendering.
        # A bad font, interrupted render or disk error preserves an existing PDF.
        with tempfile.NamedTemporaryFile(
            dir=output.parent, prefix=".gmscrap-", suffix=".pdf", delete=False
        ) as stream:
            temporary = Path(stream.name)
        try:
            document = SimpleDocTemplate(
                str(temporary),
                pagesize=A4,
                leftMargin=48,
                rightMargin=48,
                topMargin=40,
                bottomMargin=40,
                title="Places directory",
                author="GmScrap",
                pageCompression=1,
            )
            document.build(story)
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
        return output
