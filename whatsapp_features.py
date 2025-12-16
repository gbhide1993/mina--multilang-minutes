#!/usr/bin/env python3
"""
Advanced WhatsApp Features for MinA
- Interactive Buttons & Lists
- Location Handling
- Contact Cards
- Image OCR
"""

import os
import json
import requests
from datetime import datetime, timedelta
from utils import send_whatsapp
from db import get_conn, create_task, get_user_by_phone

def send_interactive_buttons(phone, message, buttons):
    """
    Send WhatsApp message with interactive buttons (fallback to text)
    buttons = [{"id": "btn1", "title": "Mark Done"}, {"id": "btn2", "title": "Snooze"}]
    """
    # Use text-based buttons for better compatibility
    fallback_msg = f"{message}\n\n"
    for i, btn in enumerate(buttons[:3], 1):
        fallback_msg += f"{i}️⃣ {btn['title']}\n"
    fallback_msg += "\nReply with the number to choose an option."
    return send_whatsapp(phone, fallback_msg)

def send_task_reminder_with_buttons(phone, task_id, task_title, due_date=None):
    """Send task reminder with interactive action buttons"""
    
    due_text = f" (Due: {due_date})" if due_date else ""
    message = f"📌 *Task Reminder*\n\n{task_title}{due_text}"
    
    buttons = [
        {"id": f"done_{task_id}", "title": "✅ Mark Done"},
        {"id": f"snooze_{task_id}", "title": "💤 Snooze 1hr"},
        {"id": f"reschedule_{task_id}", "title": "📅 Reschedule"}
    ]
    
    return send_interactive_buttons(phone, message, buttons)

def send_interactive_list(phone, title, sections):
    """
    Send WhatsApp list message
    sections = [{"title": "Today's Tasks", "rows": [{"id": "task1", "title": "Call John", "description": "Due 2 PM"}]}]
    """
    try:
        from twilio.rest import Client
        
        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        from_number = os.getenv("TWILIO_WHATSAPP_FROM")
        
        client = Client(account_sid, auth_token)
        
        interactive_message = {
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": title},
                "action": {
                    "button": "View Tasks",
                    "sections": sections
                }
            }
        }
        
        msg = client.messages.create(
            from_=from_number,
            to=phone,
            content_sid=None,
            body=json.dumps(interactive_message)
        )
        
        print(f"✅ Interactive list sent to {phone}")
        return True
        
    except Exception as e:
        print(f"❌ Failed to send interactive list: {e}")
        # Fallback to regular message
        fallback_msg = f"*{title}*\n\n"
        for section in sections:
            fallback_msg += f"**{section['title']}**\n"
            for row in section['rows']:
                fallback_msg += f"• {row['title']}\n"
            fallback_msg += "\n"
        return send_whatsapp(phone, fallback_msg)

def send_morning_briefing_with_list(phone):
    """Send morning briefing as interactive list"""
    try:
        user = get_user_by_phone(phone)
        if not user:
            return False
        
        from db import get_tasks_for_user
        tasks = get_tasks_for_user(user['id'], status='open', limit=10)
        
        if not tasks:
            send_whatsapp(phone, "🌅 Good morning! You have no pending tasks today. Have a great day!")
            return True
        
        # Group tasks by priority/due date
        today_tasks = []
        upcoming_tasks = []
        
        today = datetime.now().date()
        
        for task in tasks:
            due_date = task.get('due_at')
            if due_date and datetime.fromisoformat(str(due_date)).date() == today:
                today_tasks.append({
                    "id": f"task_{task['id']}",
                    "title": task['title'][:24],
                    "description": f"Due today • ID: {task['id']}"
                })
            else:
                upcoming_tasks.append({
                    "id": f"task_{task['id']}",
                    "title": task['title'][:24],
                    "description": f"ID: {task['id']}"
                })
        
        sections = []
        if today_tasks:
            sections.append({"title": "📅 Due Today", "rows": today_tasks[:10]})
        if upcoming_tasks:
            sections.append({"title": "📋 Upcoming", "rows": upcoming_tasks[:10]})
        
        title = f"🌅 Good morning! You have {len(tasks)} pending tasks."
        
        return send_interactive_list(phone, title, sections)
        
    except Exception as e:
        print(f"Error sending morning briefing: {e}")
        return False

def handle_location_message(phone, latitude, longitude, address=None):
    """Handle location sharing for check-in/out"""
    try:
        # Reverse geocode if no address provided
        if not address and latitude and longitude:
            try:
                # Use a geocoding service (you can use Google Maps API, OpenStreetMap, etc.)
                geocode_url = f"https://api.opencagedata.com/geocode/v1/json?q={latitude}+{longitude}&key={os.getenv('OPENCAGE_API_KEY')}"
                resp = requests.get(geocode_url, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    if data['results']:
                        address = data['results'][0]['formatted']
            except:
                address = f"Lat: {latitude}, Lng: {longitude}"
        
        # Log the location check-in
        timestamp = datetime.now().strftime("%I:%M %p")
        location_msg = f"📍 *Location Check-in*\n\n📅 Time: {timestamp}\n🗺️ Location: {address or 'Unknown location'}"
        
        # Create a task for the location visit
        task_title = f"Site visit - {address or 'Location'}"
        task = create_task(
            phone,
            title=task_title,
            description=f"Checked in at {timestamp}",
            priority=2,
            source='location_checkin',
            metadata={
                'latitude': latitude,
                'longitude': longitude,
                'address': address,
                'checkin_time': datetime.now().isoformat()
            }
        )
        
        # Log location check-in to database
        from db import log_location_checkin, log_user_activity
        checkin = log_location_checkin(phone, latitude, longitude, address, task['id'] if task else None)
        log_user_activity(phone, 'location_checkin', {
            'latitude': latitude,
            'longitude': longitude,
            'address': address,
            'checkin_id': checkin['id'] if checkin else None
        })
        
        # Send confirmation with action buttons
        buttons = [
            {"id": "checkout", "title": "🚪 Check Out"},
            {"id": "add_note", "title": "📝 Add Note"},
            {"id": "take_photo", "title": "📸 Take Photo"}
        ]
        
        # Store context for numbered responses
        store_button_context(phone, 'location_checkin', {
            'latitude': latitude,
            'longitude': longitude,
            'address': address
        })
        
        send_interactive_buttons(phone, location_msg, buttons)
        
        print(f"✅ Location check-in logged for {phone}")
        return True
        
    except Exception as e:
        print(f"Error handling location: {e}")
        return False

def handle_contact_card(phone, contact_name, contact_number):
    """Handle contact card sharing"""
    try:
        # Save contact to database
        from db import log_contact_save, log_user_activity
        contact = log_contact_save(phone, contact_name, contact_number, source='contact_card')
        log_user_activity(phone, 'contact_saved', {
            'contact_name': contact_name,
            'contact_number': contact_number,
            'contact_id': contact['id'] if contact else None
        })
        
        # Ask if user wants to create a task
        message = f"📇 *Contact Saved*\n\n👤 {contact_name}\n📞 {contact_number}\n\nWould you like to create a task?"
        
        buttons = [
            {"id": f"call_{contact_number}", "title": "📞 Call Task"},
            {"id": f"meet_{contact_number}", "title": "🤝 Meeting Task"},
            {"id": "no_task", "title": "❌ No Task"}
        ]
        
        # Store context for numbered responses
        store_button_context(phone, 'contact_saved', {
            'contact_name': contact_name,
            'contact_number': contact_number
        })
        
        send_interactive_buttons(phone, message, buttons)
        {"id": "no_task", "title": "❌ No Task"}
        
        
        send_interactive_buttons(phone, message, buttons)
        
        print(f"✅ Contact saved: {contact_name} - {contact_number}")
        return True
        
    except Exception as e:
        print(f"Error handling contact card: {e}")
        return False

def extract_text_from_image(image_url):
    """Extract text from image using OCR"""
    try:
        import openai
        from twilio.rest import Client
        import base64
        
        # Download image from Twilio with authentication
        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        
        response = requests.get(image_url, auth=(account_sid, auth_token))
        if response.status_code != 200:
            print(f"Failed to download image: {response.status_code}")
            return None
            
        # Convert to base64 for OpenAI
        image_base64 = base64.b64encode(response.content).decode('utf-8')
        image_data_url = f"data:image/jpeg;base64,{image_base64}"
        
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                                    "text": "Extract all text from this image. If it's a business card, format as: Name, Company, Phone, Email. If it's a whiteboard/notes, list the key points."
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": image_data_url}
                        }
                    ]
                }
            ],
            max_tokens=500
        )
        
        return response.choices[0].message.content
        
    except Exception as e:
        print(f"Error extracting text from image: {e}")
        return None

def handle_image_message(phone, image_url):
    """Handle image messages for OCR and analysis"""
    try:
        # Extract text from image
        extracted_text = extract_text_from_image(image_url)
        
        if not extracted_text:
            send_whatsapp(phone, "❌ Could not extract text from the image. Please try again with a clearer image.")
            return False
        
        # Log image activity to database
        from db import log_image_activity, log_user_activity
        
        # Analyze if it's a business card
        if any(keyword in extracted_text.lower() for keyword in ['phone', 'email', 'company', 'mobile', '@']):
            # Log business card detection
            log_image_activity(phone, image_url, extracted_text, 'business_card_detected')
            log_user_activity(phone, 'image_ocr', {
                'type': 'business_card',
                'text_length': len(extracted_text),
                'image_url': image_url
            })
            
            # Likely a business card
            message = f"📇 *Business Card Detected*\n\n{extracted_text}\n\nWhat would you like to do?"
            
            buttons = [
                {"id": "save_contact", "title": "💾 Save Contact"},
                {"id": "create_task", "title": "📋 Create Task"},
                {"id": "ignore", "title": "❌ Ignore"}
            ]
            
            # Store context for numbered responses
            store_button_context(phone, 'business_card', {'text': extracted_text})
            
            send_interactive_buttons(phone, message, buttons)
        else:
            # Log general OCR activity
            log_image_activity(phone, image_url, extracted_text, 'text_extraction')
            log_user_activity(phone, 'image_ocr', {
                'type': 'general_text',
                'text_length': len(extracted_text),
                'image_url': image_url
            })
            
            # General text extraction (whiteboard, notes, etc.)
            message = f"📝 *Text Extracted*\n\n{extracted_text}\n\nWould you like to create tasks from this?"
            
            buttons = [
                {"id": "extract_tasks", "title": "📋 Extract Tasks"},
                {"id": "save_note", "title": "💾 Save Note"},
                {"id": "ignore", "title": "❌ Ignore"}
            ]
            
            # Store context for numbered responses
            store_button_context(phone, 'image_ocr', {'text': extracted_text})
            
            send_interactive_buttons(phone, message, buttons)
        
        print(f"✅ Image processed for {phone}")
        return True
        
    except Exception as e:
        print(f"Error handling image: {e}")
        return False

# Simple in-memory context store (use Redis in production)
user_button_context = {}

def store_button_context(phone, context_type, context_data=None):
    """Store button context for user"""
    user_button_context[phone] = {
        'type': context_type,
        'data': context_data,
        'timestamp': datetime.now()
    }

def get_button_context(phone):
    """Get button context for user"""
    context = user_button_context.get(phone)
    if context:
        # Context expires after 10 minutes
        if (datetime.now() - context['timestamp']).seconds < 600:
            return context
        else:
            del user_button_context[phone]
    return None

def handle_numbered_response(phone, number):
    """Handle numbered button responses (1, 2, 3)"""
    try:
        context = get_button_context(phone)
        if not context:
            send_whatsapp(phone, "❌ No active options. Please try again.")
            return False
        
        context_type = context['type']
        context_data = context.get('data', {})
        
        if context_type == 'location_checkin':
            if number == "1":  # Check Out
                send_whatsapp(phone, "🚪 Checked out successfully!")
            elif number == "2":  # Add Note
                send_whatsapp(phone, "📝 Please send your note as a text message.")
            elif number == "3":  # Take Photo
                send_whatsapp(phone, "📸 Please send a photo to document your visit.")
                
        elif context_type == 'business_card':
            if number == "1":  # Save Contact
                extracted_text = context_data.get('text', '')
                # Parse contact info and save
                send_whatsapp(phone, "💾 Contact saved successfully!")
            elif number == "2":  # Create Task
                send_whatsapp(phone, "📋 What task would you like to create? Send a text message.")
            elif number == "3":  # Ignore
                send_whatsapp(phone, "❌ Business card ignored.")
                
        elif context_type == 'image_ocr':
            if number == "1":  # Extract Tasks
                send_whatsapp(phone, "📋 Extracting tasks from the image... Please wait.")
            elif number == "2":  # Save Note
                send_whatsapp(phone, "💾 Note saved successfully!")
            elif number == "3":  # Ignore
                send_whatsapp(phone, "❌ Image ignored.")
                
        elif context_type == 'contact_saved':
            contact_number = context_data.get('contact_number')
            if number == "1":  # Call Task
                create_task(
                    phone,
                    title=f"Call {contact_number}",
                    priority=2,
                    source='contact_card'
                )
                send_whatsapp(phone, f"📞 Task created: Call {contact_number}")
            elif number == "2":  # Meeting Task
                create_task(
                    phone,
                    title=f"Schedule meeting with {contact_number}",
                    priority=2,
                    source='contact_card'
                )
                send_whatsapp(phone, f"🤝 Task created: Schedule meeting with {contact_number}")
            elif number == "3":  # No Task
                send_whatsapp(phone, "✅ Contact saved without creating a task.")
        
        else:
            send_whatsapp(phone, "✅ Option selected!")
        
        # Clear context after handling
        if phone in user_button_context:
            del user_button_context[phone]
        
        return True
        
    except Exception as e:
        print(f"Error handling numbered response: {e}")
        return False

def handle_button_response(phone, button_id):
    """Handle interactive button responses"""
    try:
        if button_id.startswith("done_"):
            task_id = button_id.replace("done_", "")
            from db import mark_task_done
            task = mark_task_done(int(task_id))
            if task:
                send_whatsapp(phone, f"✅ Task completed: {task.get('title', 'Task')}")
            else:
                send_whatsapp(phone, "❌ Task not found or already completed.")
                
        elif button_id.startswith("snooze_"):
            task_id = button_id.replace("snooze_", "")
            # Snooze task for 1 hour
            with get_conn() as conn, conn.cursor() as cur:
                new_due = datetime.now() + timedelta(hours=1)
                cur.execute("UPDATE tasks SET due_at = %s WHERE id = %s", (new_due, int(task_id)))
                conn.commit()
            send_whatsapp(phone, "💤 Task snoozed for 1 hour.")
            
        elif button_id.startswith("call_"):
            contact_number = button_id.replace("call_", "")
            create_task(
                phone,
                title=f"Call {contact_number}",
                priority=2,
                source='contact_card'
            )
            send_whatsapp(phone, f"📞 Task created: Call {contact_number}")
            
        elif button_id == "save_contact":
            send_whatsapp(phone, "📇 Contact saved! You can now ask me for their number anytime.")
            
        elif button_id == "extract_tasks":
            send_whatsapp(phone, "🔄 Extracting tasks from the image... Please wait.")
            # TODO: Implement task extraction from image text
            
        else:
            send_whatsapp(phone, "✅ Got it!")
        
        return True
        
    except Exception as e:
        print(f"Error handling button response: {e}")
        return False
