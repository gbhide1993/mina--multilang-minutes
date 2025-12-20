"""
Billing intent router
Routes billing intents to billing_plugin without affecting other flows
"""

from billing_plugin.intents import BILLING_INTENTS
from billing_plugin.handler import handle as billing_handle


def route_billing_intent(intent: str, entities: dict, context: dict):
    """
    Routes billing-related intents to billing_plugin.

    Safe no-op if intent is not billing-related.
    """
    if intent not in BILLING_INTENTS:
        return None

    return billing_handle(
        intent=intent,
        entities=entities or {},
        context=context or {},
    )
