import re
import requests
from bs4 import BeautifulSoup

def find_hls_streams(url):
    # Mimic a standard browser request using headers
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        html_content = response.text
        found_urls = set()

        # Method 1: Parse HTML tags (e.g., <source> or <video>)
        soup = BeautifulSoup(html_content, 'html.parser')
        for element in soup.find_all(['source', 'video', 'iframe']):
            src = element.get('src') or element.get('data-src')
            if src and '.m3u8' in src:
                found_urls.add(src)

        # Method 2: Use regular expressions to scan script blocks or raw text
        # This captures HLS URLs nested in JavaScript configurations
        regex_pattern = r'(https?://[^\s"\'\`]+\.m3u8(?:[^\s"\'\`]*)?)'
        matches = re.findall(regex_pattern, html_content)
        for match in matches:
            # Clean up escape characters sometimes found in JSON/JS variables
            clean_url = match.replace('\\/', '/')
            found_urls.add(clean_url)

        return list(found_urls)

    except requests.RequestException as e:
        print(f"HTTP request failed: {e}")
        return []

# Example usage with a placeholder URL
if __name__ == "__main__":
    target_url = "https://ajobtv.com/"
    streams = find_hls_streams(target_url)
    print("Detected Streams:")
    for stream in streams:
        print(stream)
