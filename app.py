from flask import Flask, render_template, request, jsonify
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
- Greet users warmly and introduce yourself as Fuzzy from Fuzionest (only once during the first interaction and also when they greet you)
- Answer questions strictly based on the company information provided
- If asked about topics not related to Fuzionest, politely redirect: "I'm here to help you with information about Fuzionest. How can I assist you with our services?"
- Keep responses concise but informative
- Never mention sources or where you got the information
- Be helpful and encouraging about Fuzionest's services

Your main purpose is to help visitors understand:
- What Fuzionest offers
- How they can get help or contact the company
- Why they should choose Fuzionest
- General company information

Always stay focused on Fuzionest-related queries and be the best company representative possible!
"""

FORMATED_SYSTEM_PROMPT = """
**Response Format Instructions:**
- Present the information in a clear, easy-to-read paragraph.
- Use bold text for key terms or headings (e.g., "**Services:**", "**Contact:**") to make the response scannable.
- Do not use numbered lists or bullet points unless absolutely necessary.
"""

APPOINTMENT_AI_PROMPT_ADDITION = """
**AI Decision-Making and Response Rules (Strict Appointment Booking Flow with Proactive Offer):**

1. Always start with this greeting when a new conversation begins:  
   "Hello! I'm Fuzzy, your friendly AI assistant from Fuzionest. 👋 I'm here to help you learn about our services or book a consultation with our expert team. Would you like me to connect you with our team for more personalised help?"

2. If the user replies positively to the greeting’s offer, **immediately** start the appointment booking mode — even if company information is available.

3. If the user’s query is about booking, scheduling, connecting with a team member, or meeting with someone at any point, **immediately** start the appointment booking mode.

4. For all other topics:
   - If relevant company information is available, answer using only that information.
   - If the question is unrelated to the company (and relevant company info is NOT available), politely answer it briefly.
   - After answering, again ask:  
     "Would you like me to connect you with our team for more personalised help?"  
     If the user responds positively, switch to booking mode.

5. In appointment booking mode:
   - Politely explain that an expert can assist further and you’ll need a few details to schedule the appointment.
   - **Always collect details in this exact order**:
     1. Name
     2. Email
     3. Phone number
     4. Preferred timing
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
    try:
        data = request.get_json()
        user_message = data.get('message', '').strip()
        session_id = request.headers.get('X-Session-ID', str(uuid.uuid4()))

        if not user_message:
            return jsonify({'error': 'Message is required'}), 400

        # Get or create a session tracker
        if session_id not in appointment_sessions:
            appointment_sessions[session_id] = {'history': []}
        session = appointment_sessions[session_id]

        # Get relevant documents using the match_documents function
        relevant_docs = match_documents(user_message)

        # Build context from the retrieved documents
        if relevant_docs:
            context_string = ""
            for doc in relevant_docs:
                context_string += f"URL: {doc['url']}\nTitle: {doc['title']}\nContent: {doc['content']}\n\n"
        else:
            context_string = "No relevant information found."

        # Combine all system prompts and context
        combined_system_prompt = f"{SYSTEM_PROMPT}\n\n{FORMATED_SYSTEM_PROMPT}\n\n{APPOINTMENT_AI_PROMPT_ADDITION}"

        # Get conversation history for the current session
        history_string = "\n".join([f"User: {h['user']}\nBot: {h['bot']}" for h in session['history']])

        # Create the full prompt
        full_prompt = f"{combined_system_prompt}\n\nCompany Information:\n{context_string}\n\nConversation History:\n{history_string}\n\nUser's message: {user_message}\n\nResponse:"

        # Generate response using Gemini
        response = model.generate_content(full_prompt)
        bot_response = response.text.strip()

        # Update the session history
        session['history'].append({'user': user_message, 'bot': bot_response})

        # Check for the special booking tag
        if "BOOKING_COMPLETE:" in bot_response:
            try:
                booking_data_str = bot_response.split("BOOKING_COMPLETE:", 1)[1].strip()
                booking_data = json.loads(booking_data_str)

                success, message = store_appointment_and_send_emails(**booking_data)

                # Clean the response for the user
                bot_response = bot_response.split("BOOKING_COMPLETE:")[0].strip()

                if success:
                    bot_response += f"\n\n✅ **{message}**"
                else:
                    bot_response += f"\n\n⚠️ **{message}**"

                # Clear the session after successful booking
                if session_id in appointment_sessions:
                    del appointment_sessions[session_id]

            except (json.JSONDecodeError, KeyError) as e:
                logger.error(f"Failed to parse booking data from AI response: {e}")
                bot_response = "I've collected your details, but there was a small issue. Please contact us directly to confirm."

        return jsonify({
            'response': bot_response,
            'common_questions': COMMON_QUESTIONS,
            'session_id': session_id
        })

    except Exception as e:
        logger.error(f"Chat error: {str(e)}")
        return jsonify({'error': 'Sorry, I encountered an issue. Please try again.'}), 500


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
