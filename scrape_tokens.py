#!/usr/bin/env python3
import os
import re
import json
import time
import requests
from dotenv import load_dotenv

# Load local environment variables from .env file
load_dotenv()

GIST_ID = os.getenv("GITHUB_GIST_ID")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
# We will write both files so both extensions work
GIST_FILENAMES = ["playlist.m3u", "playlist.m3u8", "channels.json"]

def scrape_channels():
    url = "https://ajobtv.com/"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    }
    
    print("Scraping ajobtv.com...")
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            print(f"Error: HTTP {response.status_code} from ajobtv.com")
            return []
        
        html_content = response.text
        channels = []
        
        # Try to find inline javascript channels array
        for pattern in [
            r'(?:const|var|let)\s+channels\s*=\s*(\[[\s\S]*?\]);',
            r'channels\s*:\s*(\[[\s\S]*?\])[,\s}]',
        ]:
            match = re.search(pattern, html_content)
            if match:
                try:
                    channels_data = json.loads(match.group(1))
                    for ch in channels_data:
                        play_url = ch.get("play_url", "")
                        name = ch.get("name", ch.get("channel_name", "Unknown")).strip()
                        logo = ch.get("logo", ch.get("channel_logo", "")).strip()
                        category = ch.get("category_name", "Live TV").strip()
                        
                        if play_url:
                            play_url = play_url.replace('\\/', '/')
                            if "token=" in play_url and "remote=" not in play_url:
                                sep = "&" if "?" in play_url else "?"
                                play_url += f"{sep}remote=no_check_ip"
                            
                            ch_id = re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')
                            channels.append({
                                "id": ch_id,
                                "name": name,
                                "logo": logo,
                                "url": play_url,
                                "category": category,
                                "scraped_at": int(time.time())
                            })
                    if channels:
                        print(f"Scraped {len(channels)} channels from JS array.")
                        return channels
                except Exception as ex:
                    print(f"JSON parsing warning: {ex}")
                    continue

        # Fallback raw regex scan
        regex_pattern = r'(https?://[^\s"\'\`]+\.m3u8(?:[^\s"\'\`]*)?)'
        matches = re.findall(regex_pattern, html_content)
        for i, match_url in enumerate(matches):
            clean_url = match_url.replace('\\/', '/')
            if "token=" in clean_url and "remote=" not in clean_url:
                sep = "&" if "?" in clean_url else "?"
                clean_url += f"{sep}remote=no_check_ip"
            
            path_match = re.search(r'ctghub\.com/([^/]+)/', clean_url)
            raw_name = path_match.group(1) if path_match else f"Channel {i+1}"
            name = raw_name.replace('.', ' ').replace('-', ' ').replace('_', ' ').title().strip()
            ch_id = re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')
            
            channels.append({
                "id": ch_id,
                "name": name,
                "logo": "",
                "url": clean_url,
                "category": "Live TV",
                "scraped_at": int(time.time())
            })
            
        print(f"Scraped {len(channels)} channels from raw regex fallback.")
        return channels
    except Exception as e:
        print(f"Scraping error: {e}")
        return []

DEFAULT_4K_CHANNELS = [
    {
        "id": "golive_4k",
        "name": "GoLive 4K",
        "logo": "https://img.icons8.com/color/144/4k-resolution.png",
        "url": "http://203.18.159.180/GoLIve/index.m3u8",
        "category": "4K",
        "scraped_at": int(time.time())
    },
    {
        "id": "hdr_4k",
        "name": "HDR 4K",
        "logo": "https://img.icons8.com/color/144/4k-resolution.png",
        "url": "https://go8knm.optikl.ink/OT/live/HDR/HDR/1950411.m3u8",
        "category": "4K",
        "scraped_at": int(time.time())
    }
]

def generate_m3u(channels):
    m3u_content = "#EXTM3U\n"
    for ch in channels:
        logo_url = ""
        logo_val = ch.get("logo", "")
        if logo_val:
            if logo_val.startswith("http"):
                logo_url = logo_val
            else:
                logo_url = f"https://ajobtv.com/assets/images/channels/{logo_val}"
            
        logo_part = f' tvg-logo="{logo_url}"' if logo_url else ''
        category = ch.get("category", "Live TV")
        stream_url = ch.get("url", "")
        
        m3u_content += (
            f'#EXTINF:-1 tvg-id="{ch["id"]}"{logo_part} '
            f'tvg-name="{ch["name"]}" group-title="{category}",{ch["name"]}\n'
            f'{stream_url}\n'
        )
    return m3u_content

def update_gist(m3u_data, channels_data):
    if not GITHUB_TOKEN or not GIST_ID:
        print("\nERROR: GITHUB_TOKEN or GITHUB_GIST_ID not set in environment or .env file.")
        print("Please configure them to upload directly to GitHub Gist.")
        return False
        
    url = f"https://api.github.com/gists/{GIST_ID}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    files_payload = {
        "playlist.m3u": {"content": m3u_data},
        "playlist.m3u8": {"content": m3u_data},
        "channels.json": {"content": json.dumps(channels_data, indent=2)}
    }
        
    payload = {
        "description": "Velocity IPTV Live M3U Playlist - Auto Updated",
        "files": files_payload
    }
    
    print(f"Updating Gist {GIST_ID} with playlist and channel JSON data...")
    try:
        response = requests.patch(url, headers=headers, json=payload)
        if response.status_code == 200:
            data = response.json()
            print("\nSUCCESS! Gist updated successfully.")
            print(f"Your raw Playlist URLs for VLC/TV:")
            print("-" * 60)
            for filename in GIST_FILENAMES:
                raw_url = data["files"][filename]["raw_url"]
                clean_url = re.sub(r'/raw/[a-f0-9]+/', '/raw/', raw_url)
                print(f"{filename}: {clean_url}")
            print("-" * 60)
            return True
        else:
            print(f"Failed to update Gist: HTTP {response.status_code}")
            print(response.text)
            return False
    except Exception as e:
        print(f"Network error updating Gist: {e}")
        return False

def main():
    channels = scrape_channels()
    if not channels:
        print("Failed to scrape channels. Aborting.")
        return
        
    # Merge default 4K channels dynamically
    existing_ids = {ch["id"] for ch in channels}
    for ch in DEFAULT_4K_CHANNELS:
        if ch["id"] not in existing_ids:
            channels.append(ch)
            
    m3u_content = generate_m3u(channels)
    update_gist(m3u_content, channels)

if __name__ == "__main__":
    main()
