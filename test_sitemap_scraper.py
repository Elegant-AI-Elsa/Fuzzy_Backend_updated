import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

def fetch_urls_from_sitemap(sitemap_url):
    try:
        response = requests.get(sitemap_url)
        soup = BeautifulSoup(response.content, 'xml')
        urls = [loc.text for loc in soup.find_all('loc')]
        print(f"✅ Found {len(urls)} URLs in sitemap.")
        return urls
    except Exception as e:
        print(f"❌ Error fetching sitemap: {e}")
        return []

def scrape_pages(urls):
    results = []
    for url in tqdm(urls, desc="Scraping pages"):
        try:
            res = requests.get(url, timeout=10)
            soup = BeautifulSoup(res.content, 'html.parser')
            text = soup.get_text(separator=' ', strip=True)
            if text:
                results.append({'url': url, 'content': text})
        except Exception as e:
            print(f"⚠️ Error scraping {url}: {e}")
    return results

if __name__ == "__main__":
    sitemap_url = "https://fuzionest.com/sitemap.xml"  # ⬅️ Replace with your actual sitemap URL
    urls = fetch_urls_from_sitemap(sitemap_url)

    if urls:
        scraped_data = scrape_pages(urls)
        print(f"\n✅ Scraped {len(scraped_data)} pages successfully.")
        # You can print a sample
        for doc in scraped_data[:3]:
            print(f"\nURL: {doc['url']}\nContent Snippet: {doc['content'][:300]}...\n")
    else:
        print("❌ No URLs found in sitemap.")
