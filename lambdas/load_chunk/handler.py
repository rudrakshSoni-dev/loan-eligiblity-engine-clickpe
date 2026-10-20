"""Lambda entry point; replaced by the real handler in a later task."""

from typing import Any

NOT_IMPLEMENTED = 501


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    """Return 501 until the function is implemented."""
    return {"statusCode": NOT_IMPLEMENTED, "body": "not implemented"}
