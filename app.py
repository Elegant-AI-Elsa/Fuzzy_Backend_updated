from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import os
import google.generativeai as genai
import psycopg2
from psycopg2.extras import RealDictCursor
import logging
from dotenv import load_dotenv

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

# Database connection
def get_db_connection():
    """
    Establishes and returns a connection to the PostgreSQL database.
    """
    return psycopg2.connect(
        os.getenv('DATABASE_URL'),
        cursor_factory=RealDictCursor
    )

# New function to perform a semantic search to find relevant documents.
# This function generates the embedding and calls the database's SQL function.
def match_documents(query: str, match_threshold: float = 0.5, match_count: int = 5) -> list[dict]:
    """
    Performs a semantic search on the database to find documents relevant to the query.
    
    Args:
        query (str): The user's query string.
        match_threshold (float): The minimum similarity score.
        match_count (int): The number of top-matching documents to retrieve.

    Returns:
        list[dict]: A list of dictionaries containing the relevant document chunks.
    """
    try:
        # Generate embedding for the user's query using the Gemini API
        query_embedding_response = genai.embed_content(
            model=embedding_model,
            content=query
        )
        query_embedding = query_embedding_response['embedding']
        
    except Exception as e:
        logger.error(f"❌ Error generating embedding for query: {e}")
        return []

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Call the PostgreSQL function you created in Supabase.
        # This function handles the actual vector similarity search.
        cur.execute(
            """
            SELECT url, title, content
            FROM match_documents(%s, %s, %s) as docs;
            """,
            (str(query_embedding), match_threshold, match_count)
        )
        
        matches = cur.fetchall()
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

# Common questions for the assistant
COMMON_QUESTIONS = [
    "What services does Fuzionest offer?",
    "How can I contact Fuzionest?",
    "What makes Fuzionest different?",
    "How can Fuzionest help my business?"
]

# System prompt for the AI assistant

SYSTEM_PROMPT = """

You are Fuzzy, the friendly AI assistant for Fuzionest company. You are here to help visitors learn about Fuzionest's services and provide assistance.

Key behaviors:

- Always be polite, friendly, and professional
- Greet users warmly and introduce yourself as Fuzzy from Fuzionest **(only once during the first interaction and also when they greet you)**
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

** Formated instructions **

please format the fina

Always stay focused on Fuzionest-related queries and be the best company representative possible!

"""

FORMATED_SYSTEM_PROMPT = """

**Response Format Instructions:**

- Present the information in a clear, easy-to-read paragraph.
- Use bold text for key terms or headings (e.g., "**Services:**", "**Contact:**") to make the response scannable.
- Do not use numbered lists or bullet points unless absolutely necessary.

"""
@app.route('/api/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json()
        user_message = data.get('message', '').strip()
        
        if not user_message:
            return jsonify({'error': 'Message is required'}), 400
        
        # Get relevant documents using the new match_documents function
        relevant_docs = match_documents(user_message)

        #print("vjjjj--------------------------------------------------------------------", relevant_docs)

        # Build context from the retrieved documents
        context_string = ""
        if relevant_docs:
            for doc in relevant_docs:
                context_string += f"URL: {doc['url']}\nTitle: {doc['title']}\nContent: {doc['content']}\n\n"
        else:
            context_string = "No relevant information found."

        # print("its-me----------", context_string)
        
        # Create the full prompt
        full_prompt = f"{SYSTEM_PROMPT}{FORMATED_SYSTEM_PROMPT}\n\nCompany Information:\n{context_string}\n\nUser Question: {user_message}\n\nResponse:"
        
        # Generate response using Gemini
        response = model.generate_content(full_prompt)
        bot_response = response.text
        
        # Store in chat history
        store_chat_history(user_message, bot_response)
        
        return jsonify({
            'response': bot_response,
            'common_questions': COMMON_QUESTIONS
        })
        
    except Exception as e:
        logger.error(f"Chat error: {str(e)}")
        return jsonify({'error': 'Sorry, I encountered an issue. Please try again.'}), 500

@app.route('/api/common-questions')
def get_common_questions():
    return jsonify({'questions': COMMON_QUESTIONS})

def store_chat_history(user_message, bot_response):
    """Store chat interaction in database"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute(
            "INSERT INTO chat_history (user_message, bot_response) VALUES (%s, %s)",
            (user_message, bot_response)
        )
        
        conn.commit()
        cur.close()
        conn.close()
        
    except Exception as e:
        logger.error(f"Error storing chat history: {str(e)}")

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

if __name__ == '__main__':
    app.run(debug=True, port=5000)
