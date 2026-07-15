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

def update_gist_via_git(m3u_data, channels_data):
    import subprocess
    import shutil
    print("\nAttempting to update Gist via Git + SSH...")
    if not GIST_ID:
        print("GIST_ID is not set in environment or .env file. Cannot update via Git.")
        return False
        
    base_dir = os.path.dirname(os.path.abspath(__file__))
    temp_dir = os.path.join(base_dir, f"temp_gist_{int(time.time())}")
    
    try:
        # Clone Gist repo using SSH with HostKeyChecking bypassed and BatchMode enabled
        clone_cmd = ["git", "clone", f"git@gist.github.com:{GIST_ID}.git", temp_dir]
        env = os.environ.copy()
        env["GIT_SSH_COMMAND"] = "ssh -o StrictHostKeyChecking=no -o BatchMode=yes"
        env["GIT_TERMINAL_PROMPT"] = "0"
        
        result = subprocess.run(clone_cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            print(f"Failed to clone Gist repository: {result.stderr}")
            return False
            
        # Write files
        with open(os.path.join(temp_dir, "playlist.m3u"), "w", encoding="utf-8") as f:
            f.write(m3u_data)
        with open(os.path.join(temp_dir, "playlist.m3u8"), "w", encoding="utf-8") as f:
            f.write(m3u_data)
        with open(os.path.join(temp_dir, "channels.json"), "w", encoding="utf-8") as f:
            json.dump(channels_data, f, indent=2)
            
        # Commit & Push
        subprocess.run(["git", "config", "user.name", "Velocity IPTV Scraper"], cwd=temp_dir)
        subprocess.run(["git", "config", "user.email", "scraper@velocity.local"], cwd=temp_dir)
        
        subprocess.run(["git", "add", "playlist.m3u", "playlist.m3u8", "channels.json"], cwd=temp_dir)
        
        status_res = subprocess.run(["git", "status", "--porcelain"], cwd=temp_dir, stdout=subprocess.PIPE, text=True)
        if not status_res.stdout.strip():
            print("No changes to push. Gist is already up to date.")
            return True
            
        subprocess.run(["git", "commit", "-m", "Auto-update playlist & channel JSON data"], cwd=temp_dir)
        
        push_res = subprocess.run(["git", "push", "origin", "HEAD"], cwd=temp_dir, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if push_res.returncode != 0:
            print(f"Failed to push to Gist: {push_res.stderr}")
            return False
            
        print("\nSUCCESS! Gist updated successfully via Git + SSH.")
        return True
    except Exception as e:
        print(f"Error updating Gist via Git: {e}")
        return False
    finally:
        if os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass

def update_gist(m3u_data, channels_data):
    if not GITHUB_TOKEN or not GIST_ID:
        print("\nWARNING: GITHUB_TOKEN or GITHUB_GIST_ID not set. Trying Git+SSH fallback...")
        return update_gist_via_git(m3u_data, channels_data)
        
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
    
    print(f"Updating Gist {GIST_ID} with playlist and channel JSON data via API...")
    try:
        response = requests.patch(url, headers=headers, json=payload)
        if response.status_code == 200:
            data = response.json()
            print("\nSUCCESS! Gist updated successfully via API.")
            print(f"Your raw Playlist URLs for VLC/TV:")
            print("-" * 60)
            for filename in GIST_FILENAMES:
                raw_url = data["files"][filename]["raw_url"]
                clean_url = re.sub(r'/raw/[a-f0-9]+/', '/raw/', raw_url)
                print(f"{filename}: {clean_url}")
            print("-" * 60)
            return True
        else:
            print(f"Failed to update Gist via API: HTTP {response.status_code}")
            print(response.text)
            print("Trying Git+SSH fallback...")
            return update_gist_via_git(m3u_data, channels_data)
    except Exception as e:
        print(f"API network error updating Gist: {e}")
        print("Trying Git+SSH fallback...")
        return update_gist_via_git(m3u_data, channels_data)

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
    
    # Save files locally
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(base_dir, "playlist.m3u"), "w", encoding="utf-8") as f:
            f.write(m3u_content)
        with open(os.path.join(base_dir, "playlist.m3u8"), "w", encoding="utf-8") as f:
            f.write(m3u_content)
        with open(os.path.join(base_dir, "channels.json"), "w", encoding="utf-8") as f:
            json.dump(channels, f, indent=2)
        print("\nSUCCESS: Saved 'playlist.m3u', 'playlist.m3u8', and 'channels.json' locally in root directory.")
    except Exception as e:
        print(f"Warning: Failed to save files locally: {e}")
        
    update_gist(m3u_content, channels)

if __name__ == "__main__":
    main()
