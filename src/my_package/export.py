"""Tabular export shared by the CLI and HTTP boundary."""

import csv
import io
from dataclasses import fields

from my_package.domain.models import Place


def results_csv(places: list[dict]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=[field.name for field in fields(Place)])
    writer.writeheader()
    for place in places:
        # Keep published text from being interpreted as spreadsheet formulas.
        writer.writerow(
            {
                key: "'" + value
                if isinstance(value, str)
                and value.lstrip().startswith(("=", "+", "-", "@"))
                else value
                for key, value in place.items()
            }
        )
    return output.getvalue()
