#!/usr/bin/env python3
"""
Razorpay Subscription Integration for ₹499 Premium Plan
"""

import os
import razorpay
from datetime import datetime, timedelta
from db import get_conn, upgrade_user_subscription

# Initialize Razorpay client
razorpay_client = razorpay.Client(auth=(os.getenv("RAZORPAY_KEY_ID"), os.getenv("RAZORPAY_KEY_SECRET")))

def create_subscription_plan():
    """Create ₹499 monthly subscription plan"""
    try:
        plan_data = {
            "period": "monthly",
            "interval": 1,
            "item": {
                "name": "MinA Premium Plan",
                "amount": 49900,  # ₹499 in paise
                "currency": "INR",
                "description": "Unlimited voice transcription, OCR, and location tracking"
            }
        }
        plan = razorpay_client.plan.create(plan_data)
        return plan['id']
    except Exception as e:
        print(f"Error creating plan: {e}")
        return None

def create_subscription_link(phone, plan="premium"):
    """Create subscription payment link for user"""
    try:
        # Plan configurations
        plans = {
            "basic": {
                "amount": 29900,  # ₹299
                "description": "MinA Basic Subscription - ₹299/month",
                "plan_id": "plan_basic_299"
            },
            "premium": {
                "amount": 49900,  # ₹499
                "description": "MinA Premium Subscription - ₹499/month",
                "plan_id": "plan_premium_499"
            }
        }
        
        plan_config = plans.get(plan, plans["premium"])
        
        # Create payment link with UPI enabled
        payment_link_data = {
            "amount": plan_config["amount"],
            "currency": "INR",
            "description": plan_config["description"],
            "customer": {
                "contact": phone.replace("whatsapp:", "").replace("+", "")
            },
            "notify": {
                "sms": True,
                "whatsapp": True
            },
            "reminder_enable": True,
            "options": {
                "checkout": {
                    "method": {
                        "upi": True,
                        "card": True,
                        "netbanking": True,
                        "wallet": True
                    }
                }
            },
            "notes": {
                "phone": phone,
                "plan": plan
            },
            "callback_url": f"{os.getenv('BASE_URL', 'https://your-app.com')}/subscription-success",
            "callback_method": "get"
        }
        
        payment_link = razorpay_client.payment_link.create(payment_link_data)
        return payment_link['short_url']
        
    except Exception as e:
        print(f"Error creating subscription: {e}")
        return None

def handle_subscription_webhook(event_data):
    """Handle subscription webhook events"""
    try:
        event_type = event_data.get('event')
        subscription = event_data.get('payload', {}).get('subscription', {}).get('entity', {})
        
        if event_type == 'subscription.activated':
            phone = subscription.get('notes', {}).get('phone')
            if phone:
                upgrade_user_subscription(phone, 'premium', 30)
                return {"status": "subscription_activated", "phone": phone}
                
        elif event_type == 'subscription.cancelled':
            phone = subscription.get('notes', {}).get('phone')
            if phone:
                # Downgrade to free tier
                with get_conn() as conn, conn.cursor() as cur:
                    cur.execute("""
                        UPDATE users SET 
                            subscription_tier = 'free',
                            subscription_active = FALSE,
                            subscription_expiry = NULL
                        WHERE phone = %s
                    """, (phone,))
                    conn.commit()
                return {"status": "subscription_cancelled", "phone": phone}
        
        return {"status": "ignored"}
        
    except Exception as e:
        print(f"Error handling subscription webhook: {e}")
        return {"status": "error", "message": str(e)}
