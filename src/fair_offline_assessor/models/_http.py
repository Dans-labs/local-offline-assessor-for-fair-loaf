import re
from typing import Annotated
from urllib.parse import urljoin, urlsplit

from pydantic import AfterValidator, AnyHttpUrl


def _uri_reference(value: str) -> str:
    """Reject characters that URL parsers would silently strip or rewrite."""
    if re.search(r"[\x00-\x20\x7f\\]", value):
        raise ValueError("URL contains whitespace, control characters or backslashes")
    return value


def http_url(value: str) -> str:
    """Validate an absolute HTTP(S) URL without changing its spelling."""
    parts = urlsplit(_uri_reference(value))
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("Expected an absolute HTTP(S) URL")
    AnyHttpUrl(value)
    return value


CaptureUrl = Annotated[str, AfterValidator(http_url)]


def request_url(value: str) -> str:
    """Compare HTTP URLs without fragments, retaining the query string."""
    base, separator, query = value.partition("#")[0].partition("?")
    return str(AnyHttpUrl(base)) + separator + query


def redirect_url(base: str, location: str) -> str:
    """Resolve a supplied Location without fetching it."""
    location = _uri_reference(location.strip(" \t")).partition("#")[0]
    parts = urlsplit(location)
    if (parts.scheme or location.startswith("//")) and not parts.netloc:
        raise ValueError("Redirect URL has no host")
    resolved = urljoin(base, location)
    # urljoin inherits the old query for an explicitly empty query.
    if location.endswith("?"):
        resolved = resolved.partition("?")[0] + "?"
    return request_url(http_url(resolved))
