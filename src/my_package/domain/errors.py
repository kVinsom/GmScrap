"""Failures exposed by the search ports and handled at the CLI boundary."""


class OverpassError(RuntimeError):
    """The place provider failed, rather than returning an empty search."""


class GeocodingError(RuntimeError):
    """The city could not be resolved."""
