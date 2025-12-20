# router.py

def route_intent(intent: str, persona: str | None):
    """
    Decide which handler should process the intent.

    Returns:
        'billing'
        'task'
        'clarify'
    """

    persona = persona or "UNKNOWN"

    # Billing intent
    if intent == "create_invoice":
        if persona == "SHOPKEEPER":
            return "billing"

        if persona == "PROFESSIONAL":
            return "task"

        return "clarify"

    # Default task intent
    if intent in ("create_task", "add_task"):
        return "task"

    # Safe fallback
    return "task"
