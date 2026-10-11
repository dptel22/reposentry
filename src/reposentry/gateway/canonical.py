from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(value: str | bytes) -> str:
    data = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(data).hexdigest()


def input_hash(bundle: Any) -> str:
    return sha256_hex(canonical_json(bundle))


def cache_key(*, model: str, prompt_version: str, bundle: Any) -> str:
    return sha256_hex(canonical_json({"model": model, "prompt_version": prompt_version, "input_hash": input_hash(bundle)}))
