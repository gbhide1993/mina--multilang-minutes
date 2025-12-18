"""
Context helpers for billing plugin
"""

def build_context(raw_context: dict) -> dict:
    """
    Normalize incoming execution context.

    Args:
        raw_context (dict): raw context from webhook / worker

    Returns:
        dict: sanitized context
    """

    # TODO: normalize phone
    # TODO: attach user_id if available
    # TODO: attach subscription tier
    # TODO: attach locale / timezone

    return raw_context
