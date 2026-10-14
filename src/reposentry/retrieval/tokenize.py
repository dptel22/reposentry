"""Identifier-aware tokenization for source code and natural-language queries."""

from __future__ import annotations

import re

_IDENTIFIER = re.compile(r"[A-Za-z0-9]+(?:_[A-Za-z0-9]+)*")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def identifier_tokens(text: str) -> tuple[str, ...]:
    """Keep full identifiers and normalized subtokens in deterministic order."""
    output: list[str] = []
    for identifier in _IDENTIFIER.findall(text):
        folded = identifier.casefold()
        if folded not in output:
            output.append(folded)
        for snake_part in identifier.split("_"):
            for camel_part in _CAMEL_BOUNDARY.sub(" ", snake_part).split():
                token = camel_part.casefold()
                if token and token not in output:
                    output.append(token)
    return tuple(output)
