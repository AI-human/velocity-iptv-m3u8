import requests
import re
import time

def test_live():
    url = "https://hd.ctghub.com/T-SPORTS-HD/index.m3u8?token=160442ee76b6b9dba1e54ffc6c4495dd28edda60-9845d8805b3da0009f4ac335cdf688cd-1781201475-1781190675&remote=no_check_ip"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }
    
    # 1. Fetch index playlist
    print("Fetching index playlist...")
    r = requests.get(url, headers=headers)
    print(r.status_code)
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
    print(r2.status_code)
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
