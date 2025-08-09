# website_scraper.py
# The SitemapScraper class is now solely focused on scraping and
# data extraction, without any direct database knowledge.

import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from tqdm import tqdm
import logging
import re

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SitemapScraper:
    """A class to scrape a website using its sitemap."""
    def __init__(self, sitemap_url: str):
        self.sitemap_url = sitemap_url
        self.domain = urlparse(sitemap_url).netloc
        self.scraped_data = []

    def clean_text(self, text: str) -> str:
        """Cleans and normalizes text content."""
        if not text:
            return ""
        # Remove extra whitespace and trim
        text = ' '.join(text.split()).strip()
        # Remove non-alphanumeric characters, keeping common punctuation
        text = re.sub(r'[^\w\s.,!?;:()\-]', '', text)
        return text

    def extract_content(self, soup: BeautifulSoup) -> tuple[str, str]:
        """Extracts title and main body content from a BeautifulSoup object."""
        try:
            # Decompose common non-content tags
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()

            title = soup.title.get_text() if soup.title else ""
            body = soup.find('body')
            content_text = body.get_text(separator=' ', strip=True) if body else ""

            return self.clean_text(title), self.clean_text(content_text)
        except Exception as e:
            logger.error(f"Error extracting content: {str(e)}")
            return "", ""

    def scrape_page(self, url: str) -> dict | None:
        """Fetches and scrapes a single URL, returning a dictionary of data."""
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            title, content = self.extract_content(soup)
            
            # Only return data for valid content
            if content and len(content.split()) > 20: # Ensure substantial content
                return {
                    "url": url,
                    "title": title,
                    "content": content,
                    "word_count": len(content.split())
                }
        except Exception as e:
            logger.warning(f"Failed to scrape {url}: {e}")
        return None

    def parse_sitemap(self) -> list[str]:
        """Parses the sitemap to get a list of URLs to scrape."""
        try:
            response = requests.get(self.sitemap_url, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'xml')
            urls = [loc.text for loc in soup.find_all('loc') if self.domain in loc.text]
            logger.info(f"✅ Found {len(urls)} URLs in sitemap.")
            return urls
        except Exception as e:
            logger.error(f"Error fetching sitemap: {e}")
            return []

    def run(self) -> list[dict]:
        """Runs the entire scraping process and returns the scraped data."""
        urls = self.parse_sitemap()
        for url in tqdm(urls, desc="Scraping pages"):
            page_data = self.scrape_page(url)
            if page_data:
                self.scraped_data.append(page_data)

        logger.info(f"✅ Scraped {len(self.scraped_data)} pages successfully.")
        return self.scraped_data

# -----------------------------------------------------------------------------
