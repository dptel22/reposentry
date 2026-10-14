"""Outbound scrubbing: high-precision secret patterns are redacted before send."""

from __future__ import annotations

from typing import Any

from reposentry.observability.redact import scrub_text


def scrub_bundle(bundle: Any) -> Any:
    """Redact secret-looking literals in every string leaf before the data
    leaves the gateway boundary. Only high-precision value patterns are
    redacted (see observability.redact.SECRET_PATTERNS); ordinary code such as
    ``secret = os.environ["X"]`` has no literal value and passes through.
    """
    if isinstance(bundle, str):
        return scrub_text(bundle)
    if isinstance(bundle, dict):
        return {k: scrub_bundle(v) for k, v in bundle.items()}
    if isinstance(bundle, (list, tuple)):
        return [scrub_bundle(v) for v in bundle]
    return bundle
