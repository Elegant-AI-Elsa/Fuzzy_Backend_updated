# run_scraper.py
# (v2.0) This script now orchestrates the scraping AND embedding process.

import os
import sys
from dotenv import load_dotenv
import logging
import psycopg2
from psycopg2.extras import RealDictCursor, execute_batch
from website_scraper import SitemapScraper
from db_setup import create_database_tables, test_database_connection
from embedding_generator import process_and_embed_documents # (v2.0) Import the new function

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# (v2.0) The old insert_scraped_data is no longer used, as we will use a different method.
# (v2.0) The main insertion logic is now in embedding_generator.py

def run_scraper_with_url(sitemap_url: str):
    """Run the scraper for a specific sitemap URL, processes it, and saves to DB with embeddings."""
    logger.info(f"🚀 Starting website scraping for sitemap: {sitemap_url}")

    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        logger.error("❌ DATABASE_URL not found in environment variables!")
        logger.error("Please check your .env file.")
        return False

    try:
        # Step 1: Run the scraper to get all the data
        scraper = SitemapScraper(sitemap_url)
        scraped_data = scraper.run()

        if not scraped_data:
            logger.warning("No data was scraped. Exiting.")
            return True

        # (v2.0) Step 2: Process the scraped data, generate chunks and embeddings, and insert them
        logger.info("🧠 Processing scraped data and generating embeddings...")
        process_and_embed_documents(scraped_data)

        logger.info("✅ Scraping, embedding, and database update completed successfully!")
        return True
    except Exception as e:
        logger.error(f"❌ An error occurred: {str(e)}")
        return False

def main():
    """Main function to run the scraper based on user input."""
    default_sitemap_url = "https://fuzionest.com/sitemap.xml"
    run_scraper_with_url(default_sitemap_url)

if __name__ == "__main__":
    logger.info("🤖 Fuzionest AI Assistant - Website Scraper & Embedder")
    logger.info("=" * 50)
    # Check if the database is setup before running scraper
    if not test_database_connection():
      sys.exit(1)
    
    main()