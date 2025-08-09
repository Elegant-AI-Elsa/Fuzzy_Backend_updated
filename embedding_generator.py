# embedding_generator.py
# (v2.0) New file for handling text chunking and embedding generation.

import os
import google.generativeai as genai
import psycopg2
from psycopg2.extras import execute_batch, RealDictCursor
import logging
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configure Gemini AI for embeddings
genai.configure(api_key=os.getenv('GOOGLE_API_KEY'))
embedding_model = 'models/text-embedding-004'

def get_db_connection():
    return psycopg2.connect(
        os.getenv('DATABASE_URL'),
        cursor_factory=RealDictCursor
    )

def chunk_text(content: str, chunk_size: int = 1000):
    """Splits a long text into smaller chunks."""
    # (v2.0) Simple chunking for demonstration. For production, consider a more advanced splitter.
    chunks = [content[i:i + chunk_size] for i in range(0, len(content), chunk_size)]
    return chunks

def process_and_embed_documents(scraped_data: list[dict]):
    """Chunks documents, generates embeddings, and inserts them into the database."""
    if not scraped_data:
        logger.info("No documents to process.")
        return

    all_chunks_with_embeddings = []

    for doc in scraped_data:
        content = doc.get('content')
        url = doc.get('url')
        title = doc.get('title')
        
        # (v2.0) Chunk the content
        chunks = chunk_text(content)

        # (v2.0) Generate embeddings for all chunks in one batch API call
        # This is more efficient than one call per chunk
        try:
            embeddings_response = genai.embed_content(
                model=embedding_model,
                content=chunks
            )
            embeddings = embeddings_response['embedding']
            
            for i, chunk in enumerate(chunks):
                # (v2.1) Calculate word_count for the chunk
                word_count = len(chunk.split())
                all_chunks_with_embeddings.append({
                    'url': url,
                    'title': title,
                    'content': chunk,
                    'word_count': word_count,  # (v2.1) Add word_count to the dictionary
                    'embedding': embeddings[i]
                })

        except Exception as e:
            logger.error(f"Error generating embeddings for {url}: {e}")
            continue

    if not all_chunks_with_embeddings:
        logger.warning("No embeddings were generated. Skipping database insertion.")
        return

    # (v2.0) Insert all chunks and embeddings into the database
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # (v2.1) Update the list of columns to be inserted
        records_to_insert = [
            (item['url'], item['title'], item['content'], item['word_count'], item['embedding'])
            for item in all_chunks_with_embeddings
        ]

        # (v2.1) Update the SQL query to include the word_count column
        execute_batch(
            cur,
            """
            INSERT INTO scraped_content (url, title, content, word_count, embedding)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (url, content) DO NOTHING;
            """,
            records_to_insert
        )

        conn.commit()
        cur.close()
        conn.close()
        logger.info(f"✅ Successfully inserted {len(records_to_insert)} chunks with embeddings into the database.")
    
    except Exception as e:
        logger.error(f"❌ Database batch insertion error for embeddings: {e}")