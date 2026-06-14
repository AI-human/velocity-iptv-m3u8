import requests
import re
import json

def test_live():
    print("Fetching fresh playlist to get active T-Sports token...")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }
    
    url = ""
    try:
        # Try local api first if running
        r = requests.get("http://localhost:5000/api/channels", timeout=3)
        channels = r.json()
        tsports = next((c for c in channels if "t_sports" in c["id"]), None)
        url = tsports["url"]
    except Exception:
        # Fallback to direct scraping
        try:
            r = requests.get("https://ajobtv.com/", headers=headers, timeout=10)
            match = re.search(r'(?:const|var|let)\s+channels\s*=\s*(\[[\s\S]*?\]);', r.text)
            if match:
                data = json.loads(match.group(1))
                tsports = next((c for c in data if "T-Sports" in c.get("name", "") or "T Sports" in c.get("name", "")), None)
                if tsports:
                    url = tsports.get("play_url", "")
                    if url and "remote=" not in url:
                        sep = "&" if "?" in url else "?"
                        url += f"{sep}remote=no_check_ip"
        except Exception as e:
            print("Failed to scrape direct:", e)

    if not url:
        print("T-Sports URL not found or could not be scraped!")
        return

    print(f"Using live URL: {url}")
    
    # 1. Fetch index playlist
    print("Fetching index playlist...")
    r = requests.get(url, headers=headers)
    print("Index status:", r.status_code)
    print(r.text)
    
    # Extract sub-playlist URI (e.g. tracks-v1a1/mono.m3u8?token=...)
    sub_match = re.search(r'(tracks-v1a1/mono.m3u8[^\s]+)', r.text)
    if not sub_match:
        print("Sub-playlist not found!")
        return
        
    sub_uri = sub_match.group(1)
    sub_url = f"https://hd.ctghub.com/T-SPORTS-HD/{sub_uri}"
    print(f"Fetching sub-playlist from {sub_url}...")
    
    # 2. Fetch sub-playlist
    r2 = requests.get(sub_url, headers=headers)
    print("Sub-playlist status:", r2.status_code)
    print(r2.text)
    
    # Extract the last segment (latest)
    segments = re.findall(r'(\d{4}/\d{2}/\d{2}/\d{2}/\d{2}/\d{2}-\d+\.ts[^\s]+)', r2.text)
    if not segments:
        print("No segments found!")
        return
        
    latest_segment = segments[-1]
    segment_url = f"https://hd.ctghub.com/T-SPORTS-HD/{latest_segment}"
    print(f"Fetching latest segment: {segment_url}...")
    
    # 3. Fetch latest segment
    r3 = requests.get(segment_url, headers=headers)
    print("Segment response status:", r3.status_code)
    print("Segment length:", len(r3.content))

if __name__ == "__main__":
    test_live()
