"""URL secret redaction.

Acquisition sends no authorization headers, cookies, or credentials of
its own — every request is an anonymous HTTPS GET — so there is nothing
of that kind to redact from headers. A document URL itself, however, may
legitimately carry a signed or pre-signed query parameter (an access
token, a signature) even for a nominally open-access item served through
a specific provider link. Every URL that reaches an error message or an
:class:`~strix.corpus.acquisition.models.AcquisitionRecord` goes through
:func:`redact_url` first; the *unredacted* URL is used only for the
actual request itself.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_SENSITIVE_QUERY_PARAM_PATTERN = re.compile(
    r"(signature|token|auth|key|credential|secret|sig|x-amz-)", re.IGNORECASE
)


def redact_url(url: str) -> str:
    """Mask likely-sensitive query parameter values in *url*.

    Preserves scheme, host, path, parameter *names*, and fragment-free
    structure so the URL remains informative for audit purposes; replaces
    only the values of parameters whose name looks like a signature,
    token, key, credential, or secret.
    """
    parsed = urlsplit(url)
    if not parsed.query:
        return url
    redacted_params = [
        (key, "REDACTED" if _SENSITIVE_QUERY_PARAM_PATTERN.search(key) else value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
    ]
    redacted_query = urlencode(redacted_params)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, redacted_query, parsed.fragment))
