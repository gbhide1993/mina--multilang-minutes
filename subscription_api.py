#!/usr/bin/env python3
"""
API endpoints for subscription management
"""

from flask import request, jsonify
from razorpay_subscription import create_subscription_link, create_subscription_plan

def add_subscription_routes(app):
    
    @app.route("/api/subscription/create", methods=["POST"])
    def api_create_subscription():
        """Create subscription link for user"""
        try:
            data = request.get_json()
            phone = data.get("phone")
            plan = data.get("plan", "premium")
            if not phone:
                return jsonify({"error": "phone required"}), 400
            
            link = create_subscription_link(phone, plan)
            if link:
                return jsonify({"subscription_url": link}), 200
            else:
                return jsonify({"error": "failed to create subscription"}), 500
                
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    @app.route("/subscription-success", methods=["GET"])
    def subscription_success():
        """Subscription success page"""
        return """
        <!DOCTYPE html>
        <html><head><title>Subscription Successful</title></head>
        <body style="font-family: Arial; text-align: center; padding: 50px;">
        <h1>🎉 Welcome to MinA Premium!</h1>
        <p>Your subscription is now active. Enjoy unlimited features!</p>
        <a href="https://wa.me/12545365395?text=Hi%20MinA" style="background: #25D366; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px;">Continue on WhatsApp</a>
        </body></html>
        """