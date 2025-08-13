from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import os
import google.generativeai as genai
import psycopg2
from psycopg2.extras import RealDictCursor
import logging
from dotenv import load_dotenv
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import json
import uuid
import re

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configure Gemini AI
genai.configure(api_key=os.getenv('GOOGLE_API_KEY'))
model = genai.GenerativeModel('gemini-2.5-flash-lite')
embedding_model = 'models/text-embedding-004'

# Global session storage for appointment tracking
appointment_sessions = {}

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

def store_appointment_and_send_emails(name, email, phone, timing):
    """Store appointment in database and send confirmation emails"""
    try:
        # Store in database
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute(
            "INSERT INTO appointment_bookings (name, email, phone, appointment_time) VALUES (%s, %s, %s, %s)",
            (name, email, phone, timing)
        )
        
        conn.commit()
        cur.close()
        conn.close()
        
        logger.info(f"✅ Appointment stored for {name}")
        
        # Send confirmation emails
        email_success = send_appointment_emails(name, email, phone, timing)
        
        if email_success:
            return True, "Confirmation email sent successfully! Our team will contact you soon to finalize the scheduling."
        else:
            return True, "Appointment booked successfully! Our team will contact you soon to confirm the details."
        
    except Exception as e:
        logger.error(f"❌ Appointment storage error: {str(e)}")
        return False, "There was an issue processing your appointment. Please try contacting us directly."

def send_appointment_emails(name, email, phone, timing):
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
        logger.info("✅ Appointment emails sent successfully")
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
You are Fuzzy, the friendly AI assistant for Fuzionest company. You are here to help visitors learn about Fuzionest's services and provide assistance.

Key behaviors:
- Always be polite, friendly, and professional
- Answer questions strictly based on the company information provided
- Keep responses concise but informative
- Never mention sources or where you got the information
- Be helpful and encouraging about Fuzionest's services
- **Important:** Do not start your responses with a greeting unless the user's message is a greeting (e.g., "Hi," "Hello," "Hey").
- Your primary goal is to answer the user's question directly and clearly.
"""

FORMATED_SYSTEM_PROMPT = """
**Response Format Instructions:**
- Present the information in a clear, easy-to-read paragraph.
- Use bold text for key terms or headings (e.g., "**Services:**", "**Contact:**") to make the response scannable.
- Do not use numbered lists or bullet points unless absolutely necessary.
"""

APPOINTMENT_AI_PROMPT_ADDITION = """
**AI Decision-Making and Response Rules (Strict Appointment Booking Flow with Proactive Offer):**

1. **Crucial Rule:** If the current conversation is in the middle of collecting booking details (i.e., you have already asked for name, email, phone, or timing), you must **completely ignore** any general company information retrieved from the database. Stay focused on the booking flow only.
2. If the user's query is explicitly about booking, scheduling, or meeting with a team member, **immediately** start the appointment booking mode.
3. If the user's query is about a topic where **relevant company information is available**, answer their question directly using only that information. After providing the answer, you may then offer to connect them with a team member: "Would you like me to connect you with our team for more personalised help?"
4. If the question is unrelated to the company (and relevant company info is NOT available), politely state that you can only help with company-related queries. Then, ask if they would like to connect with the team.
5. In appointment booking mode:
    - Politely explain that an expert can assist further and you’ll need a few details to schedule the appointment.
    - **Always collect details in this exact order**:
      1. Name
      2. Email
      3. Phone number
      4. Preferred timing
    - **Important Rule for Preferred Timing:** Our working days are Monday through Saturday, from 9 a.m. to 8 p.m. If the user requests a time on a Sunday, or outside of these hours, you must politely inform them that we are unavailable then and ask them to choose an appointment within our working hours.
    - **Important Rule for Email Validation:** You should recognize a valid email address as a string that contains an "@" symbol. Once you have a string with an "@" symbol, accept it as the user's email and move on to asking for the next detail.
    - Only ask for **one missing detail at a time**. If a user skips or ignores a detail, politely insist on getting it before moving on.
    - Never skip the "Preferred timing" question — ensure it is always asked and answered before completing the booking.
6. If the user changes the subject or declines to provide details, politely end the booking flow and switch back to normal company chat mode.
7. Once all four details are collected, confirm the booking with a friendly message and **append** this tag at the very end (do not mention this tag to the user): 
    `BOOKING_COMPLETE:{"name":"<name>","email":"<email>","phone":"<phone>","timing":"<timing>"}`
8. Do not repeat previously collected details unless confirming all four at the end.
9. Stay friendly, professional, and concise throughout the process.
"""

@app.route('/api/chat', methods=['POST'])
def chat():
    # ---- Fix applied: capture request data BEFORE starting the generator ----
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
        appointment_sessions[session_id] = {'history': []}
    session = appointment_sessions[session_id]

    def generate():
        try:
            relevant_docs = match_documents(user_message)
            context_string = ""
            # FIX: Only build context if the booking flow hasn't started.
            # This prevents the AI from getting confused with conflicting information.
            booking_in_progress = any("booking" in msg['bot'].lower() for msg in session['history'])
            if relevant_docs and not booking_in_progress:
                for doc in relevant_docs:
                    context_string += f"URL: {doc['url']}\nTitle: {doc['title']}\nContent: {doc['content']}\n\n"
            else:
                context_string = "No relevant information found."
            
            combined_system_prompt = f"{SYSTEM_PROMPT}\n\n{FORMATED_SYSTEM_PROMPT}\n\n{APPOINTMENT_AI_PROMPT_ADDITION}"
            
            history_string = "\n".join([f"User: {h['user']}\nBot: {h['bot']}" for h in session['history']])
            full_prompt = f"{combined_system_prompt}\n\nCompany Information:\n{context_string}\n\nConversation History:\n{history_string}\n\nUser's message: {user_message}\n\nResponse:"

            # Use stream=True to get a generator
            response_stream = model.generate_content(full_prompt, stream=True)
            bot_response_full = ""

            # Stream chunks of the response
            for chunk in response_stream:
                if chunk.text:
                    bot_response_full += chunk.text
                    
                    # Check if the chunk contains the booking tag and split it.
                    # This prevents the tag from being streamed to the frontend.
                    if "BOOKING_COMPLETE:" in chunk.text:
                        # Use a regex to find the JSON object. This is more resilient to extra text.
                        match = re.search(r'\{(.*?)\}', chunk.text)
                        if match:
                            booking_data_str = match.group(0)
                        else:
                            booking_data_str = "" # Fallback if no JSON is found
                        
                        partial_response = chunk.text.split("BOOKING_COMPLETE:")[0].strip()
                        if partial_response:
                            yield json.dumps({'response_chunk': partial_response}) + '\n'
                        break
                    
                    yield json.dumps({'response_chunk': chunk.text}) + '\n'

            # After streaming is complete, process the full response for special tags
            if "BOOKING_COMPLETE:" in bot_response_full:
                try:
                    # Use a regex to find the JSON object from the full response, just in case the split didn't catch it all
                    match = re.search(r'BOOKING_COMPLETE:({.*?})', bot_response_full, re.DOTALL)
                    if match:
                        booking_data_str = match.group(1)
                    else:
                        raise ValueError("Booking data not found after tag.")

                    booking_data = json.loads(booking_data_str)
                    success, message = store_appointment_and_send_emails(**booking_data)
                    bot_response_user = bot_response_full.split("BOOKING_COMPLETE:")[0].strip()
                    final_message = f"\n\n✅ **{message}**" if success else f"\n\n⚠️ **{message}**"
                    
                    # Yield the final confirmation message
                    yield json.dumps({'response_chunk': final_message, 'is_final': True, 'session_id': session_id}) + '\n'

                    # Clear session after successful booking
                    if success:
                        if session_id in appointment_sessions:
                            del appointment_sessions[session_id]

                except (json.JSONDecodeError, KeyError, ValueError) as e:
                    logger.error(f"Failed to parse booking data from AI response: {e}")
                    error_message = "I've collected your details, but there was a small issue. Please contact us directly to confirm."
                    yield json.dumps({'response_chunk': f"\n\n⚠️ **{error_message}**"}) + '\n'
            
            # This logic updates the session history with the full response, cleaned of the tag
            session['history'].append({'user': user_message, 'bot': bot_response_full.split("BOOKING_COMPLETE:")[0].strip()})
        
        except Exception as e:
            logger.error(f"Chat error: {str(e)}")
            yield json.dumps({'error': 'Sorry, I encountered an issue. Please try again.'}) + '\n'

    return Response(generate(), mimetype='application/json')

# Your existing routes for testing and scraping
@app.route('/api/common-questions')
def get_common_questions():
    return jsonify({'questions': COMMON_QUESTIONS})

@app.route('/api/scrape-trigger', methods=['POST'])
def trigger_scraping():
    """Endpoint to manually trigger scraping and embedding"""
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
    """Test SMTP connection"""
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
    """Debug endpoint to check active appointment sessions"""
    return jsonify({
        'active_appointment_sessions': len(appointment_sessions),
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000)