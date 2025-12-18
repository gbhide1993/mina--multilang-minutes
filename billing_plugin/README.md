# Billing Plugin (MinA)

This plugin will handle all billing-related workflows, including:

- Invoice OCR
- Expense extraction
- Bill classification
- Payment reminders
- GST / tax summaries (India-focused)

## Current State
Scaffold only. No business logic implemented.

## Entry Point
`billing_plugin.handler.handle(intent, entities, context)`

## Design Goals
- WhatsApp-first
- OCR-driven
- Database-backed
- Subscription-aware
- India MSME friendly
