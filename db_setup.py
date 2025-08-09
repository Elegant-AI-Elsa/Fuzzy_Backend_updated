import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_database_tables():
    """Create necessary database tables for Fuzionest AI Assistant"""
    try:
        # Connect to database
        conn = psycopg2.connect(
            os.getenv('DATABASE_URL'),
            cursor_factory=RealDictCursor
        )
        cur = conn.cursor()
        
        logger.info("Creating database tables...")
        
        # (v2.0) Enable the pgvector extension
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        
        # (v2.0) Create scraped_content table with a vector column
        cur.execute('''
            CREATE TABLE IF NOT EXISTS scraped_content (
                id SERIAL PRIMARY KEY,
                url TEXT NOT NULL,
                title TEXT,
                content TEXT NOT NULL,
                scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                word_count INTEGER DEFAULT 0,
                embedding vector(768), -- (v2.0) The embedding column for vector storage
                UNIQUE (url, content) -- (v2.0) Ensure unique content from a URL
            );
        ''')
        
        # ✅ Create separate index
        cur.execute('''
            CREATE INDEX IF NOT EXISTS idx_scraped_url ON scraped_content(url);
        ''')

        # (v2.0) Create a HNSW index for fast similarity search
        cur.execute('''
            CREATE INDEX IF NOT EXISTS idx_scraped_embedding ON scraped_content USING hnsw (embedding vector_cosine_ops);
        ''')

        # Create chat_history table
        cur.execute('''
            CREATE TABLE IF NOT EXISTS chat_history (
                id SERIAL PRIMARY KEY,
                session_id TEXT,
                user_message TEXT NOT NULL,
                bot_response TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                user_ip TEXT,
                response_time FLOAT
            );
        ''')
        
        # Create feedback table for improving responses
        cur.execute('''
            CREATE TABLE IF NOT EXISTS chat_feedback (
                id SERIAL PRIMARY KEY,
                chat_history_id INTEGER REFERENCES chat_history(id),
                rating INTEGER CHECK (rating >= 1 AND rating <= 5),
                feedback_text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')
        
        # Create analytics table
        cur.execute('''
            CREATE TABLE IF NOT EXISTS chat_analytics (
                id SERIAL PRIMARY KEY,
                date DATE DEFAULT CURRENT_DATE,
                total_messages INTEGER DEFAULT 0,
                unique_users INTEGER DEFAULT 0,
                avg_response_time FLOAT DEFAULT 0,
                most_asked_question TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')
        
        # Add indexes for better performance
        cur.execute('''
            CREATE INDEX IF NOT EXISTS idx_scraped_content_scraped_at 
            ON scraped_content(scraped_at DESC);
        ''')
        
        cur.execute('''
            CREATE INDEX IF NOT EXISTS idx_chat_history_created_at 
            ON chat_history(created_at DESC);
        ''')
        
        cur.execute('''
            CREATE INDEX IF NOT EXISTS idx_chat_history_session 
            ON chat_history(session_id);
        ''')
        
        conn.commit()
        logger.info("Database tables created successfully!")
        
        # (v2.0) Removed sample data insertion. This is now handled by the scraping script.
        
        cur.close()
        conn.close()
        
        return True
        
    except Exception as e:
        logger.error(f"Error creating database tables: {str(e)}")
        return False

def test_database_connection():
    """Test the database connection"""
    try:
        conn = psycopg2.connect(
            os.getenv('DATABASE_URL'),
            cursor_factory=RealDictCursor
        )
        cur = conn.cursor()
        cur.execute("SELECT version();")
        version = cur.fetchone()
        logger.info(f"Database connection successful! PostgreSQL version: {version['version']}")
        
        cur.close()
        conn.close()
        return True
        
    except Exception as e:
        logger.error(f"Database connection failed: {str(e)}")
        return False

if __name__ == "__main__":
    logger.info("Setting up Fuzionest AI Assistant Database...")
    
    # Test connection first
    if test_database_connection():
        # Create tables
        if create_database_tables():
            logger.info("Database setup completed successfully! 🎉")
            logger.info("You can now run the Flask application with: python app.py")
        else:
            logger.error("Failed to create database tables")
    else:
        logger.error("Please check your DATABASE_URL in the .env file")