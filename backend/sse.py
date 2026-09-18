import json
from typing import Any


def encode_event(
    event: str,
    data: Any,
    *,
    default: Any = None,
    ensure_ascii: bool = False,
) -> str:
    """Encode one server-sent event using the legacy wire format."""
    options = {"ensure_ascii": ensure_ascii}
    if default is not None:
        options["default"] = default
    return f"event: {event}\ndata: {json.dumps(data, **options)}\n\n"
