#!/usr/bin/env python3
"""
Fuzionest AI Assistant Setup Script
This script sets up everything needed to run the AI assistant
"""

import os
import sys
import subprocess
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def check_python_version():
    if sys.version_info < (3, 8):
        logger.error("❌ Python 3.8 or higher is required!")
        logger.error(f"Current version: {sys.version}")
        return False
    logger.info(f"✅ Python version: {sys.version}")
    return True

def create_directory_structure():
    directories = ['templates', 'static', 'logs']
    for directory in directories:
        Path(directory).mkdir(exist_ok=True)
        logger.info(f"✅ Created directory: {directory}")

def install_requirements():
    logger.info("📦 Installing Python requirements...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        logger.info("✅ All requirements installed successfully!")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Failed to install requirements: {e}")
        return False
    except FileNotFoundError:
        logger.error("❌ pip not found! Please install pip first.")
        return False

def setup_environment():
    env_template_path = Path('.env.template')
    env_path = Path('.env')

    if not env_path.exists():
        if env_template_path.exists():
            with open(env_template_path, 'r') as template:
                with open(env_path, 'w') as env_file:
                    env_file.write(template.read())
            logger.info("✅ Created .env file from template")
        else:
            with open(env_path, 'w') as env_file:
                env_file.write("# Fuzionest AI Assistant Environment Variables\n")
                env_file.write("GOOGLE_API_KEY=your_google_gemini_api_key_here\n")
                env_file.write("DATABASE_URL=your_supabase_postgresql_connection_string\n")
            logger.info("✅ Created basic .env file")

        logger.warning("⚠️  Please edit the .env file and add your API keys!")
    else:
        logger.info("✅ .env file already exists")

def check_env_variables():
    from dotenv import load_dotenv
    load_dotenv()
    required_vars = ['GOOGLE_API_KEY', 'DATABASE_URL']
    missing_vars = [var for var in required_vars if not os.getenv(var) or os.getenv(var).startswith('your_')]
    if missing_vars:
        logger.warning("⚠️  Missing environment variables:")
        for var in missing_vars:
            logger.warning(f"   - {var}")
        return False
    logger.info("✅ All environment variables are set!")
    return True

def setup_database():
    logger.info("🗄️  Setting up database...")
    try:
        from db_setup import create_database_tables, test_database_connection
        if test_database_connection():
            if create_database_tables():
                logger.info("✅ Database setup completed!")
                return True
            else:
                logger.error("❌ Failed to create database tables")
                return False
        else:
            logger.error("❌ Database connection failed")
            return False
    except ImportError as e:
        logger.error(f"❌ Import error: {e}")
        return False

def run_initial_scraping():
    logger.info("🔍 Initial website scraping setup...")
    print("\nWould you like to run the initial website scraping now?")
    print("This will collect information from your Fuzionest website.")
    print("You can also run this later using: python run_scraper.py")

    choice = input("Run scraping now? (y/n): ").lower().strip()

    if choice in ['y', 'yes']:
        sitemap_url = input("Enter sitemap URL (e.g., https://fuzionest.com/sitemap.xml): ").strip()
        if sitemap_url:
            try:
                from website_scraper import SitemapScraper
                logger.info(f"🔍 Scraping sitemap: {sitemap_url}...")
                scraper = SitemapScraper(sitemap_url)
                scraper.run()
                return True
            except Exception as e:
                logger.error(f"❌ Scraping failed: {e}")
                return False
        else:
            logger.info("Skipping scraping - no URL provided")
    else:
        logger.info("Skipping initial scraping")

    return True

def main():
    print("🤖 Fuzionest AI Assistant Setup")
    print("=" * 50)

    if not check_python_version():
        return False

    create_directory_structure()

    if not install_requirements():
        return False

    setup_environment()

    if not check_env_variables():
        logger.warning("⚠️  Please configure your .env file first, then run this script again")
        return False

    if not setup_database():
        return False

    run_initial_scraping()

    print("\n🎉 Setup Complete!")
    print("=" * 50)
    print("Your Fuzionest AI Assistant is ready to use!")
    print("\nNext steps:")
    print("1. Run the application: python app.py")
    print("2. Open http://localhost:5000 in your browser")
    print("3. Start chatting with Fuzzy!")
    print("\nOptional commands:")
    print("- Run scraper: python run_scraper.py")
    print("- Setup database: python db_setup.py")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⏹️  Setup interrupted by user")
    except Exception as e:
        logger.error(f"❌ Setup failed: {str(e)}")
