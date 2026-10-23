"""JSON serialization with deterministic identity and no private input fields."""

import hashlib
import json


def encode(value) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=_scalar) + "\n"
    ).encode()


def _scalar(value):
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


def digest(value) -> str:
    return hashlib.sha256(encode(value)).hexdigest()
