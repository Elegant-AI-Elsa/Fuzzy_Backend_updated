from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import os
import google.generativeai as genai
import psycopg2
from psycopg2.extras import RealDictCursor
import logging
from dotenv import load_dotenv
from datetime import datetime, timedelta
import json
import uuid
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import time
from zoneinfo import ZoneInfo


# Load environment variables
load_dotenv()

app = Flask(__name__)

# Replace "https://your-frontend-domain.com" with your actual frontend URL
# Adding localhost allows you to continue testing on your own computer
CORS(app, resources={r"/api/*": {"origins": ["https://fuzzy-frontend-updated.vercel.app", "http://localhost:3000"]}})
# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configure Gemini AI
genai.configure(api_key=os.getenv('GOOGLE_API_KEY'))
model = genai.GenerativeModel('gemini-1.5-flash')
embedding_model = 'models/text-embedding-004'

# Enhanced session storage for appointment tracking
appointment_sessions = {}

# Helper to generate time slots for the current day
def generate_time_slots():
    ist = ZoneInfo("Asia/Kolkata")
    now = datetime.now()
    slots = []
    
    # Define working hours
    start_hour = 9
    end_hour = 20  # 8 PM
    
    # If it's Sunday, show next Monday's slots
    if now.weekday() == 6:  # Sunday
        next_day = now + timedelta(days=1)
        day_name = "Monday"
        for hour in range(start_hour, min(start_hour + 6, end_hour)):  # Show first 6 hours
            slots.append(f"{day_name} {hour}:00")
            slots.append(f"{day_name} {hour}:30")
        return slots[:6]  # Limit to 6 slots
    
    # If it's too late today (after 6 PM), show tomorrow's slots
    if now.hour >= 18:  # After 6 PM
        next_day = now + timedelta(days=1)
        # Skip if tomorrow is Sunday
        if next_day.weekday() == 6:
            next_day = next_day + timedelta(days=1)  # Go to Monday
        
        day_name = next_day.strftime("%A")
        for hour in range(start_hour, min(start_hour + 6, end_hour)):
            slots.append(f"{day_name} {hour}:00")
            slots.append(f"{day_name} {hour}:30")
        return slots[:6]
    
    # Show today's remaining slots
    current_hour = now.hour
    today_name = "Today"
    
    for hour in range(max(current_hour + 1, start_hour), end_hour):
        slots.append(f"{today_name} {hour}:00")
        slots.append(f"{today_name} {hour}:30")
    
    # If we don't have enough slots for today, add tomorrow's slots
    if len(slots) < 4:
        next_day = now + timedelta(days=1)
        if next_day.weekday() != 6:  # Not Sunday
            day_name = next_day.strftime("%A")
            remaining_needed = 6 - len(slots)
            for hour in range(start_hour, min(start_hour + (remaining_needed // 2) + 1, end_hour)):
                if len(slots) >= 6:
                    break
                slots.append(f"{day_name} {hour}:00")
                if len(slots) >= 6:
                    break
                slots.append(f"{day_name} {hour}:30")
    
    return slots[:6]  # Always return max 6 slots for clean UI

# Database connection
def get_db_connection():
    """Establishes and returns a connection to the PostgreSQL database."""
    return psycopg2.connect(
        os.getenv('DATABASE_URL'),
        cursor_factory=RealDictCursor
    )

def match_documents(query: str, match_threshold: float = 0.3, match_count: int = 5) -> list[dict]:
    """Performs a semantic search on the database to find documents relevant to the query."""
    try:
        logger.info(f"🔍 Searching for query: '{query}'")
        
        query_embedding_response = genai.embed_content(
            model=embedding_model,
            content=query
        )
        query_embedding = query_embedding_response['embedding']
        logger.info(f"✅ Generated embedding for query (length: {len(query_embedding)})")
        
    except Exception as e:
        logger.error(f"❌ Error generating embedding for query: {e}")
        return []

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        logger.info(f"🔍 Searching database with threshold: {match_threshold}, count: {match_count}")

        cur.execute(
            """
            SELECT url, title, content
            FROM match_documents(%s, %s, %s) as docs;
            """,
            (str(query_embedding), match_threshold, match_count)
        )
        
        matches = cur.fetchall()
        
        logger.info(f"📊 Database returned {len(matches)} matches")
        
        cur.close()
        conn.close()
        return matches

    except psycopg2.OperationalError as e:
        logger.error(f"❌ Database connection error: {e}")
        if conn:
            conn.close()
        return []
    except Exception as e:
        logger.error(f"❌ An error occurred during document matching: {e}")
        if conn:
            conn.close()
        return []

def store_appointment_and_send_emails(name, email, phone, timing, is_update=False, old_timing=None):
    """Store appointment in database and send confirmation emails"""
    try:
        # Store in database
        conn = get_db_connection()
        cur = conn.cursor()
        
        if is_update:
            # Update existing appointment
            cur.execute(
                "UPDATE appointment_bookings SET appointment_time = %s, updated_at = CURRENT_TIMESTAMP WHERE email = %s AND name = %s",
                (timing, email, name)
            )
        else:
            # Insert new appointment
            cur.execute(
                "INSERT INTO appointment_bookings (name, email, phone, appointment_time) VALUES (%s, %s, %s, %s)",
                (name, email, phone, timing)
            )
        
        conn.commit()
        cur.close()
        conn.close()
        
        logger.info(f"✅ Appointment {'updated' if is_update else 'stored'} for {name}")
        
        # Send confirmation emails
        email_success = send_appointment_emails(name, email, phone, timing, is_update, old_timing)
        
        if email_success:
            if is_update:
                return True, "Appointment update confirmation email sent successfully! Our team will contact you to confirm the new timing."
            else:
                return True, "Confirmation email sent successfully! Our team will contact you soon to finalize the scheduling."
        else:
            if is_update:
                return True, "Appointment updated successfully! Our team will contact you soon to confirm the new timing."
            else:
                return True, "Appointment booked successfully! Our team will contact you soon to confirm the details."
        
    except Exception as e:
        logger.error(f"❌ Appointment {'update' if is_update else 'storage'} error: {str(e)}")
        return False, f"There was an issue processing your appointment {'update' if is_update else ''}. Please try contacting us directly."

def send_appointment_emails(name, email, phone, timing, is_update=False, old_timing=None):
    """Send appointment confirmation emails"""
    try:
        smtp_server = os.getenv('SMTP_HOST', 'smtp.gmail.com')
        smtp_port = int(os.getenv('SMTP_PORT', 587))
        smtp_user = os.getenv('SMTP_USER')
        smtp_pass = os.getenv('SMTP_PASS')
        
        if not smtp_user or not smtp_pass:
            logger.warning("SMTP credentials not configured - skipping email")
            return False
        
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        
        # Email to customer
        customer_msg = MIMEMultipart()
        customer_msg['From'] = smtp_user
        customer_msg['To'] = email
        
        if is_update:
            customer_msg['Subject'] = "⏰ Appointment Time Updated - Fuzionest"
            customer_body = f"""
Hello {name}!

Your appointment with Fuzionest has been successfully updated! 🔄

**Updated Appointment Details:**
👤 Name: {name}
📧 Email: {email}
📱 Phone: {phone}
⏰ New Preferred Time: {timing}
{f"🔄 Previous Time: {old_timing}" if old_timing else ""}
📅 Updated on: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}

**What happens next?**
Our expert team will contact you within 24 hours to confirm the new scheduling and discuss any changes to your requirements.

**About Fuzionest:**
We specialize in providing innovative solutions tailored to your business needs. Our team of experts is ready to discuss how we can help you succeed.

If you have any questions or need further changes, feel free to reach out to us anytime.

Best regards,
The Fuzionest Team 🌟

---
This is an automated confirmation. Please don't reply to this email.
            """
        else:
            customer_msg['Subject'] = "🎉 Appointment Confirmed with Fuzionest!"
            customer_body = f"""
Hello {name}!

Thank you for booking an appointment with Fuzionest! 🚀

**Your Appointment Request Details:**
👤 Name: {name}
📧 Email: {email}
📱 Phone: {phone}
⏰ Preferred Time: {timing}
📅 Requested on: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}

**What happens next?**
Our expert team will contact you within 24 hours to confirm the exact scheduling and discuss your specific requirements. We're excited to help you achieve your goals!

**About Fuzionest:**
We specialize in providing innovative solutions tailored to your business needs. Our team of experts is ready to discuss how we can help you succeed.

If you have any questions, feel free to reach out to us anytime.

Best regards,
The Fuzionest Team 🌟

---
This is an automated confirmation. Please don't reply to this email.
            """
        
        customer_msg.attach(MIMEText(customer_body, 'plain'))
        server.send_message(customer_msg)
        
        # Emails to office staff
        office_emails = [
            os.getenv('OFFICE_EMAIL_1'),
            os.getenv('OFFICE_EMAIL_2')
        ]
        
        for office_email in office_emails:
            if office_email and '@' in office_email:
                office_msg = MIMEMultipart()
                office_msg['From'] = smtp_user
                office_msg['To'] = office_email
                
                if is_update:
                    office_msg['Subject'] = f"🔄 Appointment Updated - {name}"
                    office_body = f"""
Appointment timing updated!

**Customer Details:**
👤 Name: {name}
📧 Email: {email}
📱 Phone: {phone}
⏰ New Preferred Time: {timing}
{f"🔄 Previous Time: {old_timing}" if old_timing else ""}

**Update Details:**
📅 Updated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}
💬 Source: AI Chat Assistant (Fuzzy) - Appointment Update

**Action Required:**
Please contact {name} at {phone} or {email} to confirm the new appointment scheduling.

**Next Steps:**
1. Call/email the customer within 24 hours
2. Confirm the new date/time that works for both parties
3. Update internal appointment calendar
4. Prepare for consultation based on their requirements

Best regards,
Fuzzy AI Assistant 🤖
                    """
                else:
                    office_msg['Subject'] = f"🔔 New Appointment Request - {name}"
                    office_body = f"""
New appointment booking received!

**Customer Details:**
👤 Name: {name}
📧 Email: {email}
📱 Phone: {phone}
⏰ Preferred Time: {timing}

**Booking Details:**
📅 Booked: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}
💬 Source: AI Chat Assistant (Fuzzy)

**Action Required:**
Please contact {name} at {phone} or {email} to confirm the appointment scheduling and discuss their requirements.

**Next Steps:**
1. Call/email the customer within 24 hours
2. Confirm specific date/time that works for both parties
3. Prepare for consultation based on their inquiry
4. Update internal appointment calendar

Best regards,
Fuzzy AI Assistant 🤖
                    """
                
                office_msg.attach(MIMEText(office_body, 'plain'))
                server.send_message(office_msg)
        
        server.quit()
        logger.info(f"✅ Appointment {'update' if is_update else ''} emails sent successfully")
        return True
        
    except Exception as e:
        logger.error(f"❌ Email sending error: {str(e)}")
        return False

# Common questions for the assistant
COMMON_QUESTIONS = [
    "What services does Fuzionest offer?",
    "How can I contact Fuzionest?",
    "What makes Fuzionest different?",
    "How can Fuzionest help my business?"
]



SYSTEM_PROMPT = """
You are Fuzzy, the friendly, warm, and helpful AI assistant for Fuzionest company. You are here to help visitors learn about Fuzionest's services and provide assistance.

Key behaviors:
- Always be polite, friendly, and professional with a positive and encouraging tone.
- Answer questions strictly based on the company information provided.
- Keep responses concise but informative.
- Never mention sources or where you got the information.
- Be helpful and encouraging about Fuzionest's services.
- **Important:** Do not start your responses with a greeting unless the user's message is a greeting (e.g., "Hi," "Hello," "Hey").
- If a user greets you (e.g, "Hi","Hello","Good morning","Hey")greet them back in a warm,Brief and welcome them like a friend.
- **Synthesize and Summarize:** For broad questions like "Tell me about your company," you MUST synthesize a helpful, multi-sentence summary from the provided `Company Information` context. Start with a general overview and then mention key services or unique aspects found in the text. Do not give a generic, unhelpful answer.
- Your primary goal is to answer the user's question directly and clearly.
"""

FORMATED_SYSTEM_PROMPT = """
**Response Format Instructions:**
- Use markdown for a clean, scannable format.
- Use bolding for key terms (e.g., "**Services:**") and important phrases.
- For long lists of services or bullet points, use markdown lists (`* ` or `- `).
- For longer paragraphs, use line breaks to improve readability.
- Do not use numbered lists.
"""

APPOINTMENT_AI_PROMPT_ADDITION = """
**AI Decision-Making and Response Rules (Enhanced Appointment Booking & Update Flow):**

0.  **Recall Existing Appointment:** If `STORED_USER_DETAILS` and `LAST_APPOINTMENT_TIMING` are present and the user asks about their appointment (e.g., 'what is my time', 'when is our meeting'), you MUST respond with the value from `LAST_APPOINTMENT_TIMING`. **Do not start a new booking.** For example: 'Your appointment is scheduled for [timing]. Let me know if you'd like to change it!'
    **Information Not Found Rule:** If the `Company Information` section says 'No relevant information found,' you must inform the user you couldn't find the specific detail and then immediately offer to connect them with the team for more help. For example: 'I couldn't find the specific details about that. Would you like me to connect you with our team for more personalised help?'
    **Out-of-Scope Rule:** If the user's query is completely unrelated to Fuzionest's business, services, or appointments, and no relevant information is found, respond with this exact phrase: 'I am Fuzzy, the AI assistant for Fuzionest. I can only provide information about our company and services. Is there anything related to Fuzionest I can help you with?'

1. **Crucial Rule:** If the current conversation is in the middle of collecting booking details (i.e., you have already asked for name, email, phone, or timing), you must **completely ignore** any general company information retrieved from the database. Stay focused on the booking flow only.

2. If the user asks an unrelated question while in booking mode, you must respond with this specific phrase to confirm their intent: `CONFIRM_SWITCH_MODE: It looks like you've changed the subject. Would you like to cancel the appointment booking and switch to a general chat, or continue with the booking?`

3. If the user responds positively to cancelling, politely end the booking flow and switch to general chat mode. If they want to continue, proceed with the booking.

4. **NEW: Appointment Update Detection** - If the user mentions wanting to "change," "update," "reschedule," or "modify" their appointment time, and you have their previous details stored, immediately enter UPDATE_MODE.

5. **UPDATE_MODE Rules:**
    - **First, check if the user's message ALREADY contains a new preferred time** (e.g., "I want to change my appointment to Thursday 7 p.m").
    - **If a new time IS provided:** Immediately use that time and respond with the `UPDATE_COMPLETE` JSON format. Do NOT ask for the time again.
    - **If a new time is NOT provided:** THEN you can ask for the new preferred timing. Use this format: "I can help you update your appointment timing. What would be your new preferred time?"
    - Show time slot buttons and allow manual input only when you are asking for the time.
    - Once the new timing is received (either from the initial message or a follow-up), respond with: `UPDATE_COMPLETE:{"name":"[stored_name]","email":"[stored_email]","phone":"[stored_phone]","new_timing":"[user_new_timing]","old_timing":"[stored_old_timing]"}`

6. **CRITICAL BOOKING TRIGGER:** If the user's query is explicitly about booking, scheduling, or meeting... **OR if the user gives a positive confirmation (like 'yes', 'yeah', or 'sure') immediately after you have asked if they want to connect with the team**, you must **immediately** start the appointment booking mode by asking for their name and email address.

7. **BOOKING PREVENTION FOR POST-BOOKING/UPDATE MESSAGES:** If a user has already completed a booking or appointment update (indicated by their details being stored in STORED_USER_DETAILS), and they send casual messages like "thank you", "thanks", "great", "ok", "perfect", "awesome", "no need", or similar acknowledgments immediately after a booking/update confirmation, do NOT trigger any booking or update flows. Instead, respond naturally to their message and offer general assistance.

8. If the user's query is about a topic where **relevant company information is available**, answer their question directly using only that information. After providing the answer, you may then offer to connect them with a team member: "Would you like me to connect you with our team for more personalised help?"

9. In appointment booking mode:
    - **Initial Step:** Politely explain that you need a few details. Ask for the **user's name and email address in a single request**.Be friendly and conversational
    - **Subsequent Steps:** After receiving the name and email, ask for the **phone number**.
    - **Phone Number Validation:** You must accept a message containing a string of at least 8 digits as a valid phone number.
    - **Timing Collection:** After the phone number, ask for the preferred timing.
    - **Working Hours Rule:** Our working days are Monday through Saturday, from 9 AM to 8 PM. Accept any time within these hours.
    - **Time Format Flexibility:** Accept ANY of these formats: "Friday 2 PM", "Tomorrow 10:00", "Thursday at 3:30", "Monday morning", "Next week Tuesday 11 AM", etc. Be flexible with time formats.
    - **Time Slot Buttons:** When asking for timing, show clickable buttons using: `TIME_SLOTS_DISPLAY:["slot1","slot2","slot3"]` but ALSO tell users they can type their preferred time manually.
    - **Email Validation:** Accept any string containing "@" as a valid email.
    - **CRITICAL BOOKING COMPLETION:** Once you have all details (name, email, phone, timing), respond with a confirmation message followed by EXACTLY this format:
    
    BOOKING_COMPLETE:{"name":"[user_name]","email":"[user_email]","phone":"[user_phone]","timing":"[user_timing]"}
    
    Replace [user_name], [user_email], [user_phone], and [user_timing] with the actual collected values. DO NOT add any text after this JSON format.

10. Stay friendly, professional, and concise throughout the process.
11. Never refuse valid appointment times within working hours.
12. **NEVER ask the same question twice in a row** - if you've already asked for a piece of information, wait for the user's response before proceeding.
"""

# IMPROVED BOOKING PARSING FUNCTION
def extract_booking_data(bot_response_full):
    """
    Enhanced function to extract booking data from AI response with multiple fallback methods
    """
    logger.info(f"🔧 Attempting to extract booking data from response length: {len(bot_response_full)}")
    
    try:
        # Method 1: Try the original regex pattern for new bookings
        match = re.search(r'BOOKING_COMPLETE:\s*({.*?})', bot_response_full, re.DOTALL)
        if match:
            booking_data_str = match.group(1)
            logger.info(f"✅ Method 1 successful (BOOKING_COMPLETE): {booking_data_str}")
            return json.loads(booking_data_str), "booking"
        
        # Method 2: Try the update pattern for appointment updates
        update_match = re.search(r'UPDATE_COMPLETE:\s*({.*?})', bot_response_full, re.DOTALL)
        if update_match:
            update_data_str = update_match.group(1)
            logger.info(f"✅ Method 2 successful (UPDATE_COMPLETE): {update_data_str}")
            return json.loads(update_data_str), "update"
        
        # Method 3: Try finding JSON after BOOKING_COMPLETE: (more flexible)
        booking_complete_index = bot_response_full.find('BOOKING_COMPLETE:')
        if booking_complete_index != -1:
            json_part = bot_response_full[booking_complete_index + len('BOOKING_COMPLETE:'):].strip()
            
            # Find the first { and matching }
            json_start = json_part.find('{')
            if json_start != -1:
                brace_count = 0
                json_end = -1
                
                for i, char in enumerate(json_part[json_start:], json_start):
                    if char == '{':
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            json_end = i + 1
                            break
                
                if json_end != -1:
                    potential_json = json_part[json_start:json_end]
                    logger.info(f"✅ Method 3 found potential JSON: {potential_json}")
                    return json.loads(potential_json), "booking"
        
        # Method 4: Try finding JSON after UPDATE_COMPLETE: (more flexible)
        update_complete_index = bot_response_full.find('UPDATE_COMPLETE:')
        if update_complete_index != -1:
            json_part = bot_response_full[update_complete_index + len('UPDATE_COMPLETE:'):].strip()
            
            json_start = json_part.find('{')
            if json_start != -1:
                brace_count = 0
                json_end = -1
                
                for i, char in enumerate(json_part[json_start:], json_start):
                    if char == '{':
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            json_end = i + 1
                            break
                
                if json_end != -1:
                    potential_json = json_part[json_start:json_end]
                    logger.info(f"✅ Method 4 found potential JSON: {potential_json}")
                    return json.loads(potential_json), "update"
        
        # Method 5: Look for any JSON-like structure in the entire response
        json_pattern = r'\{[^}]*"name"[^}]*"email"[^}]*"phone"[^}]*"timing"[^}]*\}'
        json_match = re.search(json_pattern, bot_response_full, re.DOTALL)
        if json_match:
            potential_json = json_match.group(0)
            logger.info(f"✅ Method 5 found potential JSON: {potential_json}")
            return json.loads(potential_json), "booking"
        
        logger.warning("❌ All extraction methods failed")
        return None, None
        
    except json.JSONDecodeError as e:
        logger.error(f"❌ JSON parsing error: {e}")
        return None, None
    except Exception as e:
        logger.error(f"❌ Unexpected error in booking data extraction: {e}")
        return None, None

@app.route('/api/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json()
        user_message = data.get('message', '').strip() if data else ''
        session_id = request.headers.get('X-Session-ID', str(uuid.uuid4()))
    except Exception as e:
        logger.error(f"Error reading request data: {e}")
        return jsonify({'error': 'Invalid request'}), 400

    if not user_message:
        return jsonify({'error': 'Message is required'}), 400

    if session_id not in appointment_sessions:
        appointment_sessions[session_id] = {
            'history': [],
            'user_details': None,  # Store user details after successful booking
            'last_appointment_timing': None
        }
    session = appointment_sessions[session_id]

    def generate():
        try:
            # --- START: MODIFIED BOOKING FLAG LOGIC ---
            booking_in_progress = False
            if session['history']:
                last_bot_message = session['history'][-1].get('bot', '').lower()
                # It's in progress if the last thing the bot did was ask for details.
                if ("name and email" in last_bot_message or
                    "phone number" in last_bot_message or
                    "preferred timing" in last_bot_message):
                    # And we must ensure it wasn't a completed/failed booking message
                    if "booking_complete" not in last_bot_message and \
                       "update_complete" not in last_bot_message and \
                       "almost there" not in last_bot_message:
                        booking_in_progress = True
            # --- END: MODIFIED BOOKING FLAG LOGIC ---
            
            relevant_docs = []
            context_string = "No relevant information found."
            
            should_search = True
            
            # NEW: Check if user has already completed a booking/update and is sending casual messages
            if session.get('user_details'):
                casual_messages = [
                    'thank you', 'thanks', 'great', 'ok', 'okay', 'perfect', 'awesome', 
                    'cool', 'nice', 'good', 'excellent', 'wonderful', 'amazing', 
                    'appreciate', 'got it', 'understood', 'alright', 'all right',
                    'no need', 'no problem', 'sounds good', 'no need thanks', 'no need thank you'
                ]
                user_msg_lower = user_message.lower().strip()
                
                # Check if the last bot message was a booking or update confirmation
                last_bot_message = session['history'][-1].get('bot', '').lower() if session['history'] else ''
                was_recent_booking = 'appointment request has been submitted successfully' in last_bot_message
                was_recent_update = 'appointment timing has been updated successfully' in last_bot_message
                
                # If it's a casual post-booking/update message, don't search and don't trigger any flows
                if (was_recent_booking or was_recent_update) and any(casual_msg in user_msg_lower for casual_msg in casual_messages):
                    should_search = False
                    logger.info("✅ User sent casual post-booking/update message, skipping document search and all booking triggers.")
            
            if session['history'] and should_search:
                last_bot_message = session['history'][-1].get('bot', '').lower()
                if "connect you with our team" in last_bot_message:
                    if user_message.lower().strip() in ['yes', 'yep', 'yeah', 'ok', 'okay', 'sure', 'go ahead', 'please do', 'yeah, go ahead']:
                        should_search = False
                        logger.info("✅ User is starting a booking, skipping document search.")

            if not booking_in_progress and should_search:
                relevant_docs = match_documents(user_message)
                if relevant_docs:
                    context_string = ""
                    for doc in relevant_docs:
                        context_string += f"URL: {doc['url']}\nTitle: {doc['title']}\nContent: {doc['content']}\n\n"
            
            time_slots = generate_time_slots()
            time_slots_str = f"TIME_SLOTS: {json.dumps(time_slots)}"
            
            user_details_str = ""
            if session['user_details']:
                user_details_str = f"\n\nSTORED_USER_DETAILS: {json.dumps(session['user_details'])}"
                if session['last_appointment_timing']:
                    user_details_str += f"\nLAST_APPOINTMENT_TIMING: {session['last_appointment_timing']}"
            
            combined_system_prompt = f"{SYSTEM_PROMPT}\n\n{FORMATED_SYSTEM_PROMPT}\n\n{APPOINTMENT_AI_PROMPT_ADDITION}\n\n{time_slots_str}{user_details_str}"
            
            history_string = "\n".join([f"User: {h['user']}\nBot: {h['bot']}" for h in session['history']])
            full_prompt = f"{combined_system_prompt}\n\nCompany Information:\n{context_string}\n\nConversation History:\n{history_string}\n\nUser's message: {user_message}\n\nResponse:"

            max_retries = 3
            bot_response_full = ""

            for attempt in range(max_retries):
                try:
                    response_stream = model.generate_content(full_prompt, stream=True)
                    bot_response_full = ""

                    for chunk in response_stream:
                        if hasattr(chunk, 'text') and chunk.text:
                            bot_response_full += chunk.text
                    
                    if "BOOKING_COMPLETE:" not in bot_response_full and "UPDATE_COMPLETE:" not in bot_response_full:
                        yield json.dumps({'response_chunk': bot_response_full}) + '\n'

                    if bot_response_full.strip():
                        break
                        
                except Exception as e:
                    logger.warning(f"Attempt {attempt + 1} failed: {e}")
                    if attempt == max_retries - 1:
                        fallback_response = "I apologize, but I'm having trouble processing your request right now. Could you please rephrase your message or try again?"
                        yield json.dumps({'response_chunk': fallback_response}) + '\n'
                        session['history'].append({'user': user_message, 'bot': fallback_response})
                        return
                    time.sleep(1)

            if "BOOKING_COMPLETE:" in bot_response_full or "UPDATE_COMPLETE:" in bot_response_full:
                try:
                    booking_data, operation_type = extract_booking_data(bot_response_full)
                    
                    if operation_type == "update" and booking_data:
                        required_keys = ['name', 'email', 'phone', 'new_timing']
                        if all(key in booking_data for key in required_keys):
                            logger.info(f"✅ Successfully parsed update data: {booking_data}")
                            
                            old_timing = booking_data.get('old_timing', session.get('last_appointment_timing', 'Previous timing'))
                            
                            success, message = store_appointment_and_send_emails(
                                booking_data['name'], booking_data['email'], booking_data['phone'],
                                booking_data['new_timing'], is_update=True, old_timing=old_timing
                            )
                            
                            session['last_appointment_timing'] = booking_data['new_timing']
                            bot_response_user_part = bot_response_full.split("UPDATE_COMPLETE:")[0].strip()
                            
                            if success:
                                confirmation_msg = f"""🔄 **Perfect! Your appointment timing has been updated successfully!**

**Updated Details:**
⏰ **New Time:** {booking_data['new_timing']}
{f"🔄 **Previous Time:** {old_timing}" if old_timing else ""}

**What happens next:**
✅ Update confirmation email sent to {booking_data['email']}
📞 Our team will contact you within 24 hours to confirm your new {booking_data['new_timing']} appointment
💼 We'll be ready to discuss your requirements at the new scheduled time

Thank you for updating your appointment, {booking_data['name']}! 🚀

*Need to change the timing again? Just let me know!*"""
                            else:
                                confirmation_msg = f"""⚠️ **Appointment timing updated!**
                        
Thank you {booking_data['name']}! We've updated your appointment to {booking_data['new_timing']}.

{message}"""
                            
                            yield json.dumps({'response_chunk': confirmation_msg, 'is_final': True, 'session_id': session_id}) + '\n'
                            session['history'].append({'user': user_message, 'bot': bot_response_user_part})
                            return
                        else:
                            raise ValueError("Incomplete update data")
                    
                    elif operation_type == "booking" and booking_data:
                        required_keys = ['name', 'email', 'phone', 'timing']
                        if all(key in booking_data for key in required_keys):
                            logger.info(f"✅ Successfully parsed booking data: {booking_data}")
                            
                            success, message = store_appointment_and_send_emails(
                                booking_data['name'], booking_data['email'],
                                booking_data['phone'], booking_data['timing']
                            )
                            
                            if success:
                                session['user_details'] = {'name': booking_data['name'], 'email': booking_data['email'], 'phone': booking_data['phone']}
                                session['last_appointment_timing'] = booking_data['timing']
                            
                            bot_response_user_part = bot_response_full.split("BOOKING_COMPLETE:")[0].strip()
                            
                            if success:
                                confirmation_msg = f"""🎉 **Perfect! Your appointment request has been submitted successfully!**

**What happens next:**
✅ Confirmation email sent to {booking_data['email']}
📞 Our team will contact you within 24 hours to confirm your {booking_data['timing']} appointment
💼 We'll discuss your specific requirements during the call

Thank you for choosing Fuzionest, {booking_data['name']}! We're excited to help you achieve your goals. 🚀

*Need to change the timing later? Just let me know and I can help you update it!*"""
                            else:
                                confirmation_msg = f"""⚠️ **Appointment details received!**
                        
Thank you {booking_data['name']}! We've recorded your appointment request for {booking_data['timing']}.

{message}"""
                            
                            yield json.dumps({'response_chunk': confirmation_msg, 'is_final': True, 'session_id': session_id}) + '\n'
                            session['history'].append({'user': user_message, 'bot': bot_response_user_part})
                            return
                        else:
                            raise ValueError("Incomplete booking data")
                    else:
                        raise ValueError("No valid operation data")
                        
                except Exception as e:      
                    logger.error(f"❌ Failed to process booking/update: {e}")
                    is_update_attempt = "UPDATE_COMPLETE:" in bot_response_full
                    bot_response_user_part = bot_response_full.split("UPDATE_COMPLETE:" if is_update_attempt else "BOOKING_COMPLETE:")[0].strip()
                    error_message = f"""⚠️ **Almost there!** I've collected your details, but there was a small technical issue. Please contact us directly to {'update' if is_update_attempt else 'book'} your appointment."""
                    final_error_message = f"{bot_response_user_part}\n\n{error_message}"
                    yield json.dumps({'response_chunk': final_error_message, 'is_final': True}) + '\n'
                    session['history'].append({'user': user_message, 'bot': bot_response_user_part})
                    return
            else:
                yield json.dumps({'response_chunk': '', 'is_final': True, 'session_id': session_id}) + '\n'
            
            session['history'].append({'user': user_message, 'bot': bot_response_full})
        
        except Exception as e:
            logger.error(f"Chat error: {str(e)}")
            yield json.dumps({'error': 'Sorry, I encountered an issue. Please try again.'}) + '\n'

    return Response(generate(), mimetype='application/json')

@app.route('/api/common-questions')
def get_common_questions():
    return jsonify({'questions': COMMON_QUESTIONS})

@app.route('/api/scrape-trigger', methods=['POST'])
def trigger_scraping():
    try:
        from run_scraper import run_scraper_with_url
        website_url = request.json.get('url', 'https://fuzionest.com')
        success = run_scraper_with_url(website_url)
        if success:
            return jsonify({'message': 'Scraping and embedding process started successfully.'})
        else:
            return jsonify({'error': 'Failed to trigger scraping and embedding.'}), 500
    except Exception as e:
        logger.error(f"Scraping trigger error: {str(e)}")
        return jsonify({'error': 'Failed to trigger scraping and embedding.'}), 500

@app.route('/api/test-email', methods=['POST'])
def test_email_endpoint():
    try:
        smtp_server = os.getenv('SMTP_HOST', 'smtp.gmail.com')
        smtp_port = int(os.getenv('SMTP_PORT', 587))
        smtp_user = os.getenv('SMTP_USER')
        smtp_pass = os.getenv('SMTP_PASS')
        if not smtp_user or not smtp_pass:
            return jsonify({'success': False, 'message': 'SMTP credentials not configured'})
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.quit()
        return jsonify({'success': True, 'message': 'SMTP connection successful'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'SMTP connection failed: {str(e)}'})

@app.route('/api/debug-sessions')
def debug_sessions():
    session_details = {}
    for session_id, session_data in appointment_sessions.items():
        session_details[session_id] = {
            'history_count': len(session_data['history']),
            'has_user_details': session_data['user_details'] is not None,
            'last_appointment_timing': session_data.get('last_appointment_timing'),
            'user_details': session_data['user_details'] if session_data['user_details'] else None
        }
    return jsonify({
        'active_appointment_sessions': len(appointment_sessions),
        'session_details': session_details
    })

@app.route('/api/clear-session', methods=['POST'])
def clear_session():
    try:
        data = request.get_json()
        session_id = data.get('session_id') if data else None
        if session_id:
            if session_id in appointment_sessions:
                del appointment_sessions[session_id]
                return jsonify({'success': True, 'message': f'Session {session_id} cleared'})
            else:
                return jsonify({'success': False, 'message': 'Session not found'})
        else:
            appointment_sessions.clear()
            return jsonify({'success': True, 'message': 'All sessions cleared'})
    except Exception as e:
        logger.error(f"Session clearing error: {str(e)}")
        return jsonify({'success': False, 'message': f'Error clearing session: {str(e)}'})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))