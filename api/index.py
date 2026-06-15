import os
import re
import json
import time
import requests
from bs4 import BeautifulSoup
from flask import Flask, Response, jsonify, render_template_string, request, redirect

app = Flask(__name__)

# Cache tokens in memory for 5 minutes (300 seconds) - production deployment
CACHE_EXPIRY = 300  
cached_channels = None
last_cache_time = 0

STATIC_LOGOS_DIR = os.path.join(os.path.dirname(__file__), "static", "logos")
SEED_FILE_PATH = os.path.join(os.path.dirname(__file__), "..", "channels_seed.json")

def get_base_url():
    """Dynamically resolves the external scheme and host for Vercel/reverse proxies."""
    try:
        scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
        return f"{scheme}://{request.host}/"
    except Exception:
        return "/"

def get_local_logos():
    """Returns a dictionary of lowercase local logo filenames mapped to their actual case-sensitive name."""
    try:
        if os.path.exists(STATIC_LOGOS_DIR):
            return {f.lower(): f for f in os.listdir(STATIC_LOGOS_DIR) if os.path.isfile(os.path.join(STATIC_LOGOS_DIR, f))}
    except Exception as e:
        print(f"Error listing local logos: {e}")
    return {}

def scrape_all_channels():
    """Scrapes ajobtv.com and returns a complete list of channel dicts with fresh tokens."""
    url = "https://ajobtv.com/"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Referer': 'https://www.google.com/',
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            print(f"Failed to fetch ajobtv: HTTP {response.status_code}")
            return []
        
        html_content = response.text
        channels = []
        
        # Strategy A: Extract the channels array definition from the inline javascript script block
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
                        stream_source = ch.get("stream_source", "")
                        category = ch.get("category_name", "Live TV").strip()
                        
                        if play_url:
                            # Clean up escaping in URLs
                            play_url = play_url.replace('\\/', '/')
                            stream_source = stream_source.replace('\\/', '/')
                            
                            # Ensure remote=no_check_ip is added to bypass IP checks
                            if "token=" in play_url and "remote=" not in play_url:
                                sep = "&" if "?" in play_url else "?"
                                play_url += f"{sep}remote=no_check_ip"
                            
                            ch_id = re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')
                            channels.append({
                                "id": ch_id,
                                "name": name,
                                "logo": logo,
                                "url": play_url,
                                "stream_source": stream_source,
                                "category": category,
                                "scraped_at": int(time.time())
                            })
                    if channels:
                        return channels
                except Exception as ex:
                    print(f"JSON parsing error: {ex}")
                    continue

        # Strategy B: Fallback — scan the raw text for m3u8 URLs
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
                "stream_source": clean_url.split('?')[0],
                "category": "Live TV",
                "scraped_at": int(time.time())
            })
            
        return channels
    except Exception as e:
        print(f"Error scraping tokens: {e}")
        return []

def get_default_4k_channels():
    return [
        {
            "id": "golive_4k",
            "name": "GoLive 4K",
            "logo": "https://img.icons8.com/color/144/4k-resolution.png",
            "url": "http://203.18.159.180/GoLIve/index.m3u8",
            "stream_source": "http://203.18.159.180/GoLIve/index.m3u8",
            "category": "4K",
            "scraped_at": int(time.time())
        },
        {
            "id": "hdr_4k",
            "name": "HDR 4K",
            "logo": "https://img.icons8.com/color/144/4k-resolution.png",
            "url": "http://go8knm.optikl.ink/OT/live/HDR/HDR/1950411.m3u8",
            "stream_source": "http://go8knm.optikl.ink/OT/live/HDR/HDR/1950411.m3u8",
            "category": "4K",
            "scraped_at": int(time.time())
        }
    ]

def load_channels(force=False):
    global cached_channels, last_cache_time
    
    current_time = time.time()
    if not force and cached_channels and (current_time - last_cache_time < CACHE_EXPIRY):
        return cached_channels

    # Scrape fresh channels from ajobtv
    channels = scrape_all_channels()
    
    # If scraping fails (blocked on Vercel), load from the GitHub Gist
    if not channels:
        gist_url = "https://gist.githubusercontent.com/AI-human/0eec8e53de265b9ef6e9bb7edb30f6bb/raw/channels.json"
        print(f"Direct scrape failed or blocked. Fetching from Gist: {gist_url}")
        try:
            resp = requests.get(gist_url, timeout=10)
            if resp.status_code == 200:
                channels = resp.json()
                print(f"Successfully loaded {len(channels)} channels from Gist.")
            else:
                print(f"Failed to load from Gist: HTTP {resp.status_code}")
        except Exception as e:
            print(f"Error fetching from Gist: {e}")
    
    if channels:
        base_url = get_base_url()
        local_logos = get_local_logos()
        
        # Merge default 4K channels dynamically
        existing_ids = {ch["id"] for ch in channels}
        for ch in get_default_4k_channels():
            if ch["id"] not in existing_ids:
                channels.append(ch)
        
        for ch in channels:
            logo_val = ch.get("logo", "")
            # If the logo is already a full URL path and not from ajobtv, keep it
            if logo_val.startswith("http") and "ajobtv.com" not in logo_val:
                continue
                
            if logo_val.startswith("http"):
                logo_filename = os.path.basename(logo_val)
            else:
                logo_filename = logo_val
                
            logo_lower = logo_filename.lower()
            
            if logo_lower in local_logos:
                ch["logo"] = f"{base_url}static/logos/{local_logos[logo_lower]}"
            elif logo_filename:
                ch["logo"] = f"https://ajobtv.com/assets/images/channels/{logo_filename}"
            else:
                ch["logo"] = ""
                
        cached_channels = channels
        last_cache_time = current_time
        return cached_channels
        
    if cached_channels:
        print("WARNING: Scrape and Gist load failed. Serving stale in-memory cache.")
        return cached_channels
        
    seed_channels = []
    if os.path.exists(SEED_FILE_PATH):
        try:
            with open(SEED_FILE_PATH, 'r', encoding='utf-8') as f:
                seed_channels = json.load(f)
        except Exception as e:
            print(f"Error reading seed database: {e}")
            
    if seed_channels:
        base_url = get_base_url()
        local_logos = get_local_logos()
        
        # Merge default 4K channels dynamically
        existing_ids = {ch["id"] for ch in seed_channels}
        for ch in get_default_4k_channels():
            if ch["id"] not in existing_ids:
                seed_channels.append(ch)
                
        for ch in seed_channels:
            logo_val = ch.get("logo_file", os.path.basename(ch.get("logo", "")))
            logo_lower = logo_val.lower()
            if logo_val.startswith("http") and "ajobtv.com" not in logo_val:
                ch["logo"] = logo_val
            elif logo_lower in local_logos:
                ch["logo"] = f"{base_url}static/logos/{local_logos[logo_lower]}"
            else:
                ch["logo"] = ""
            if "url" not in ch:
                ch["url"] = ""
            if "category" not in ch:
                ch["category"] = "Live TV"
        cached_channels = seed_channels
        last_cache_time = current_time
        return cached_channels

    return []

# Prevent caching of all API responses, allow logo assets caching
@app.after_request
def add_header(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    
    if request.path.startswith('/static/'):
        response.headers['Cache-Control'] = 'public, max-age=31536000'
        response.headers.pop('Pragma', None)
        response.headers.pop('Expires', None)
        return response
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route("/api/debug")
def debug_scrape():
    test_urls = [
        ("Direct", "https://ajobtv.com/"),
        ("AllOrigins", "https://api.allorigins.win/raw?url=https://ajobtv.com/"),
        ("CorsProxyIO", "https://corsproxy.io/?https://ajobtv.com/")
    ]
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    results = []
    for name, url in test_urls:
        res = {"name": name, "url": url, "status_code": None, "length": 0, "error": None}
        try:
            r = requests.get(url, headers=headers, timeout=8)
            res["status_code"] = r.status_code
            res["length"] = len(r.text)
            if r.status_code == 200:
                res["snippet"] = r.text[:300]
        except Exception as e:
            res["error"] = str(e)
        results.append(res)
        
    return jsonify(results)

@app.route("/api/channels")
def get_channels():
    return jsonify(load_channels())

@app.route("/api/channels/refresh", methods=["GET", "POST"])
def refresh_channels():
    channels = load_channels(force=True)
    if not channels:
        return jsonify({
            "status": "error",
            "message": "Failed to scrape channels from ajobtv.com"
        }), 500
        
    return jsonify({
        "status": "success",
        "message": f"Successfully refreshed {len(channels)} channels from ajobtv",
        "channels": channels
    })

@app.route("/api/channels/update", methods=["POST"])
def update_channels_data():
    global cached_channels, last_cache_time
    try:
        data = request.json
        if not data or "channels" not in data:
            return jsonify({"status": "error", "message": "Invalid payload"}), 400
        
        channels = data["channels"]
        if not isinstance(channels, list) or len(channels) == 0:
            return jsonify({"status": "error", "message": "Channels list is empty"}), 400
            
        base_url = get_base_url()
        local_logos = get_local_logos()
        
        processed_channels = []
        for ch in channels:
            name = ch.get("name", "Unknown").strip()
            play_url = ch.get("url", "").strip()
            logo = ch.get("logo", "").strip()
            stream_source = ch.get("stream_source", "").strip()
            category = ch.get("category", "Live TV").strip()
            
            if play_url:
                if "token=" in play_url and "remote=" not in play_url:
                    sep = "&" if "?" in play_url else "?"
                    play_url += f"{sep}remote=no_check_ip"
                    
                ch_id = re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')
                
                logo_val = os.path.basename(logo)
                logo_lower = logo_val.lower()
                if logo_lower in local_logos:
                    logo_url = f"{base_url}static/logos/{local_logos[logo_lower]}"
                elif logo:
                    logo_url = f"https://ajobtv.com/assets/images/channels/{logo_val}"
                else:
                    logo_url = ""
                    
                processed_channels.append({
                    "id": ch_id,
                    "name": name,
                    "logo": logo_url,
                    "url": play_url,
                    "stream_source": stream_source or play_url.split('?')[0],
                    "category": category,
                    "scraped_at": int(time.time())
                })
                
        if processed_channels:
            cached_channels = processed_channels
            last_cache_time = time.time()
            print(f"Successfully updated {len(processed_channels)} channels via browser scraping.")
            # Return channels directly in response — avoids Vercel cold-start cache miss on subsequent GET
            return jsonify({"status": "success", "count": len(processed_channels), "channels": processed_channels})
    except Exception as e:
        print(f"Error updating channels from client: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
        
    return jsonify({"status": "error", "message": "No valid channels processed"}), 400

@app.route("/playlist.m3u")
@app.route("/playlist.m3u8")
@app.route("/playlist")
def get_m3u_playlist():
    path = request.path
    filename = "playlist.m3u8" if path.endswith(".m3u8") else "playlist.m3u"
    gist_url = f"https://gist.githubusercontent.com/AI-human/0eec8e53de265b9ef6e9bb7edb30f6bb/raw/{filename}"
    
    print(f"IPTV client requested playlist. Proxying from Gist raw file: {gist_url}")
    try:
        resp = requests.get(gist_url, timeout=10)
        if resp.status_code == 200:
            m3u_content = resp.text.strip()
            has_appended = False
            for channel in get_default_4k_channels():
                if channel["id"] not in m3u_content and channel["url"] not in m3u_content:
                    logo_part = f' tvg-logo="{channel.get("logo", "")}"' if channel.get("logo") else ''
                    category = channel.get("category", "4K")
                    stream_url = channel.get("url", "")
                    m3u_content += (
                        f'\n#EXTINF:-1 tvg-id="{channel["id"]}"{logo_part} '
                        f'tvg-name="{channel["name"]}" group-title="{category}",{channel["name"]}\n'
                        f'{stream_url}'
                    )
                    has_appended = True
            if has_appended:
                m3u_content += "\n"
                
            response = Response(m3u_content, mimetype="application/x-mpegurl; charset=utf-8")
            response.headers["Access-Control-Allow-Origin"] = "*"
            return response
        else:
            print(f"Gist raw request failed with status: {resp.status_code}")
    except Exception as e:
        print(f"Error fetching raw playlist from Gist: {e}")

    # Fallback: Generate it dynamically from cached/local seed channels if Gist fetch fails
    channels = load_channels()
    m3u_content = "#EXTM3U\n"
    for channel in channels:
        logo_part = f' tvg-logo="{channel.get("logo", "")}"' if channel.get("logo") else ''
        category = channel.get("category", "Live TV")
        stream_url = channel.get("url", "")
        
        m3u_content += (
            f'#EXTINF:-1 tvg-id="{channel["id"]}"{logo_part} '
            f'tvg-name="{channel["name"]}" group-title="{category}",{channel["name"]}\n'
            f'{stream_url}\n'
        )
        
    response = Response(m3u_content, mimetype="application/x-mpegurl; charset=utf-8")
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response

@app.route("/live-sub/<path:subpath>")
def live_sub(subpath):
    args = request.args
    target_url = f"https://hd.ctghub.com/{subpath}"
    if args:
        params = []
        for k, v in args.items():
            params.append(f"{k}={v}")
        target_url += "?" + "&".join(params)
        
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    try:
        r = requests.get(target_url, headers=headers, timeout=8, allow_redirects=True)
        if r.status_code == 200:
            final_url = r.url
            content = r.text
            
            from urllib.parse import urljoin
            lines = content.splitlines()
            new_lines = []
            for line in lines:
                line_stripped = line.strip()
                if not line_stripped:
                    continue
                if line_stripped.startswith('#'):
                    new_lines.append(line_stripped)
                else:
                    resolved = urljoin(final_url, line_stripped)
                    if "token=" in resolved and "remote=" not in resolved:
                        sep = "&" if "?" in resolved else "?"
                        resolved += f"{sep}remote=no_check_ip"
                    new_lines.append(resolved)
                    
            response = Response('\n'.join(new_lines), mimetype="application/vnd.apple.mpegurl")
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            return response
    except Exception as e:
        print(f"Sub-playlist proxy error for {subpath}: {e}")
        
    response = redirect(target_url, code=302)
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response

@app.route("/live/<channel_id>.m3u8")
def live_channel(channel_id):
    channels = load_channels()
    channel = next((c for c in channels if c["id"] == channel_id), None)
    if not channel:
        return "Channel not found", 404
        
    target_url = channel.get("url", "")
    if not target_url:
        return "Stream URL not available", 404
        
    if request.args.get("redirect") == "true":
        response = redirect(target_url, code=302)
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response

    result = _proxy_m3u8(target_url)
    
    if result is None:
        print(f"Upstream returned 403/error for {channel_id}. Re-scraping and retrying...")
        channels = load_channels(force=True)
        channel = next((c for c in channels if c["id"] == channel_id), None)
        if channel and channel.get("url"):
            target_url = channel["url"]
            result = _proxy_m3u8(target_url)
            
    if result:
        return result
        
    print(f"Proxying completely failed for {channel_id}. Redirecting to {target_url}")
    response = redirect(target_url, code=302)
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response

@app.route("/api/proxy")
def generic_proxy():
    target_url = request.args.get("url")
    if not target_url:
        return "Missing url parameter", 400
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        r = requests.get(target_url, headers=headers, timeout=10, allow_redirects=True, stream=True)
        if r.status_code != 200:
            return f"Upstream returned status {r.status_code}", r.status_code
            
        content_type = r.headers.get("Content-Type", "")
        is_m3u8 = "mpegurl" in content_type.lower() or "apple.mpegurl" in content_type.lower() or target_url.split('?')[0].endswith(".m3u8")
        
        if is_m3u8:
            content = r.text
            final_url = r.url
            base_url = get_base_url()
            
            from urllib.parse import urljoin, quote
            lines = content.splitlines()
            new_lines = []
            for line in lines:
                line_stripped = line.strip()
                if not line_stripped:
                    continue
                if line_stripped.startswith('#'):
                    def replace_uri(match):
                        uri = match.group(1)
                        resolved_uri = urljoin(final_url, uri)
                        if "token=" in resolved_uri and "remote=" not in resolved_uri:
                            separator = "&" if "?" in resolved_uri else "?"
                            resolved_uri += f"{separator}remote=no_check_ip"
                        
                        if "hd.ctghub.com" in resolved_uri:
                            resolved_uri = resolved_uri.replace("https://hd.ctghub.com/", f"{base_url}live-sub/")
                        else:
                            resolved_uri = f"{base_url}api/proxy?url={quote(resolved_uri)}"
                        return f'URI="{resolved_uri}"'
                    processed_line = re.sub(r'URI="([^"]+)"', replace_uri, line_stripped)
                    new_lines.append(processed_line)
                else:
                    resolved_line = urljoin(final_url, line_stripped)
                    if "token=" in resolved_line and "remote=" not in resolved_line:
                        separator = "&" if "?" in resolved_line else "?"
                        resolved_line += f"{separator}remote=no_check_ip"
                    
                    if "hd.ctghub.com" in resolved_line:
                        resolved_line = resolved_line.replace("https://hd.ctghub.com/", f"{base_url}live-sub/")
                    else:
                        resolved_line = f"{base_url}api/proxy?url={quote(resolved_line)}"
                    new_lines.append(resolved_line)
                    
            proxied_m3u8 = "\n".join(new_lines)
            response = Response(proxied_m3u8, mimetype="application/vnd.apple.mpegurl")
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            return response
        else:
            def generate():
                for chunk in r.iter_content(chunk_size=4096):
                    yield chunk
            response = Response(generate(), mimetype=content_type)
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Cache-Control"] = "public, max-age=10"
            return response
    except Exception as e:
        print(f"Generic proxy error for {target_url}: {e}")
        return str(e), 500

def _proxy_m3u8(target_url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    try:
        r = requests.get(target_url, headers=headers, timeout=8, allow_redirects=True)
        if r.status_code == 403:
            return None
        if r.status_code != 200:
            return None
            
        final_url = r.url
        content = r.text
        base_url = get_base_url()
        
        from urllib.parse import urljoin, quote
        lines = content.splitlines()
        new_lines = []
        for line in lines:
            line_stripped = line.strip()
            if not line_stripped:
                continue
            if line_stripped.startswith('#'):
                def replace_uri(match):
                    uri = match.group(1)
                    resolved_uri = urljoin(final_url, uri)
                    if "token=" in resolved_uri and "remote=" not in resolved_uri:
                        separator = "&" if "?" in resolved_uri else "?"
                        resolved_uri += f"{separator}remote=no_check_ip"
                    
                    if "hd.ctghub.com" in resolved_uri:
                        resolved_uri = resolved_uri.replace("https://hd.ctghub.com/", f"{base_url}live-sub/")
                    else:
                        resolved_uri = f"{base_url}api/proxy?url={quote(resolved_uri)}"
                    return f'URI="{resolved_uri}"'
                processed_line = re.sub(r'URI="([^"]+)"', replace_uri, line_stripped)
                new_lines.append(processed_line)
            else:
                resolved_line = urljoin(final_url, line_stripped)
                if "token=" in resolved_line and "remote=" not in resolved_line:
                    separator = "&" if "?" in resolved_line else "?"
                    resolved_line += f"{separator}remote=no_check_ip"
                
                if "hd.ctghub.com" in resolved_line:
                    resolved_line = resolved_line.replace("https://hd.ctghub.com/", f"{base_url}live-sub/")
                else:
                    resolved_line = f"{base_url}api/proxy?url={quote(resolved_line)}"
                new_lines.append(resolved_line)
                
        proxied_m3u8 = "\n".join(new_lines)
        response = Response(proxied_m3u8, mimetype="application/vnd.apple.mpegurl")
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return response
    except Exception as e:
        print(f"Error proxying stream from {target_url}: {e}")
        return None

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)

# HTML Template optimized for low footprint and multiple TV/Android Player integrations
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Velocity IPTV Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #060608;
            --container-bg: #0d0d12;
            --card-bg: #14141c;
            --card-hover: #1c1c28;
            --accent-color: #ff3b30;
            --accent-hover: #d32f2f;
            --accent-blue: #007aff;
            --accent-green: #34c759;
            --text-color: #f5f5f7;
            --text-muted: #8e8e93;
            --border-color: #222230;
            --glow-shadow: 0 0 20px rgba(255, 59, 48, 0.15);
        }
        
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: 'Outfit', sans-serif;
            background: var(--bg-color);
            color: var(--text-color);
            line-height: 1.6;
            padding: 20px;
            min-height: 100vh;
        }

        .container {
            max-width: 1280px;
            margin: 0 auto;
        }

        .header {
            text-align: center;
            margin: 20px 0 30px 0;
        }

        .header h1 {
            font-size: 2.5rem;
            font-weight: 700;
            letter-spacing: -1px;
            background: linear-gradient(135deg, #fff 30%, #a1a1aa 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 5px;
        }

        .header p {
            color: var(--text-muted);
            font-size: 1.1rem;
            font-weight: 300;
        }

        .main-layout {
            display: grid;
            grid-template-columns: 1fr;
            gap: 25px;
            margin-bottom: 30px;
        }

        @media(min-width: 992px) {
            .main-layout {
                grid-template-columns: 7fr 5fr;
            }
        }

        .player-card {
            background: var(--container-bg);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 10px 40px rgba(0,0,0,0.5);
            display: flex;
            flex-direction: column;
        }

        .player-wrapper {
            background: #000;
            aspect-ratio: 16/9;
            width: 100%;
            position: relative;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        video {
            width: 100%;
            height: 100%;
            display: block;
        }

        .player-placeholder {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: radial-gradient(circle, #181824 0%, #08080c 100%);
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            color: var(--text-muted);
            font-weight: 400;
            gap: 15px;
        }

        .player-placeholder svg {
            width: 64px;
            height: 64px;
            stroke: var(--text-muted);
        }

        .panel {
            background: var(--container-bg);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 25px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            gap: 20px;
        }

        .channel-info h2 {
            font-size: 1.8rem;
            font-weight: 600;
            margin-bottom: 5px;
            color: #fff;
        }

        .channel-info .category-badge {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 20px;
            background: rgba(255, 59, 48, 0.1);
            border: 1px solid rgba(255, 59, 48, 0.3);
            color: var(--accent-color);
            font-size: 0.8rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .action-group {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }

        .btn {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            padding: 14px 20px;
            border-radius: 10px;
            font-weight: 600;
            font-size: 0.95rem;
            text-decoration: none;
            color: #fff;
            border: none;
            cursor: pointer;
            transition: all 0.2s ease;
            text-align: center;
        }

        .btn-primary {
            background: var(--accent-color);
        }

        .btn-primary:hover {
            background: var(--accent-hover);
            transform: translateY(-2px);
        }

        .btn-secondary {
            background: #222230;
            border: 1px solid var(--border-color);
        }

        .btn-secondary:hover {
            background: #2c2c3e;
            transform: translateY(-2px);
        }

        .btn-green {
            background: var(--accent-green);
        }

        .btn-green:hover {
            opacity: 0.9;
            transform: translateY(-2px);
        }

        .btn-blue {
            background: var(--accent-blue);
        }

        .btn-blue:hover {
            opacity: 0.9;
            transform: translateY(-2px);
        }

        .search-filter-section {
            background: var(--container-bg);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 25px;
            display: flex;
            flex-direction: column;
            gap: 15px;
        }

        .search-bar {
            position: relative;
            width: 100%;
        }

        .search-bar input {
            width: 100%;
            padding: 14px 20px 14px 45px;
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 10px;
            color: #fff;
            font-family: inherit;
            font-size: 1rem;
            outline: none;
            transition: all 0.2s;
        }

        .search-bar input:focus {
            border-color: var(--accent-blue);
            box-shadow: 0 0 10px rgba(0, 122, 255, 0.15);
        }

        .search-bar svg {
            position: absolute;
            left: 15px;
            top: 50%;
            transform: translateY(-50%);
            width: 20px;
            height: 20px;
            stroke: var(--text-muted);
            fill: none;
        }

        .tab-container {
            display: flex;
            gap: 10px;
            overflow-x: auto;
            padding-bottom: 5px;
            scrollbar-width: none; /* Firefox */
        }

        .tab-container::-webkit-scrollbar {
            display: none; /* Chrome/Safari */
        }

        .tab {
            padding: 8px 18px;
            border-radius: 20px;
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            color: var(--text-muted);
            cursor: pointer;
            font-weight: 600;
            font-size: 0.9rem;
            white-space: nowrap;
            transition: all 0.2s;
        }

        .tab.active {
            background: var(--accent-blue);
            border-color: var(--accent-blue);
            color: #fff;
        }

        .tab.tab-4k {
            border-color: #ffd700;
            color: #ffd700;
            text-shadow: 0 0 5px rgba(255, 215, 0, 0.2);
        }

        .tab.tab-4k.active {
            background: linear-gradient(135deg, #ffd700 0%, #ff8c00 100%);
            border-color: #ffd700;
            color: #000;
            text-shadow: none;
            box-shadow: 0 0 15px rgba(255, 215, 0, 0.4);
        }

        /* Modal Styles */
        .modal-overlay {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.85);
            backdrop-filter: blur(8px);
            z-index: 10000;
            display: none;
            align-items: center;
            justify-content: center;
        }

        .modal-content {
            background: var(--container-bg);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 30px;
            width: 90%;
            max-width: 500px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.6);
            position: relative;
        }

        .modal-header {
            font-size: 1.5rem;
            font-weight: 600;
            margin-bottom: 20px;
            color: #fff;
            background: linear-gradient(135deg, #fff 40%, #ffd700 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .modal-close {
            position: absolute;
            top: 20px;
            right: 20px;
            color: var(--text-muted);
            cursor: pointer;
            font-size: 1.8rem;
            font-weight: 300;
            border: none;
            background: none;
            outline: none;
            line-height: 1;
        }

        .modal-close:hover {
            color: #fff;
        }

        .form-group {
            margin-bottom: 20px;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .form-group label {
            font-size: 0.9rem;
            color: var(--text-muted);
            font-weight: 500;
        }

        .form-group input {
            width: 100%;
            padding: 12px 16px;
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            color: #fff;
            font-family: inherit;
            font-size: 0.95rem;
            outline: none;
            transition: all 0.2s;
        }

        .form-group input:focus {
            border-color: var(--accent-blue);
            box-shadow: 0 0 10px rgba(0, 122, 255, 0.15);
        }

        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
            gap: 15px;
        }

        .card {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 15px;
            text-align: center;
            cursor: pointer;
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: space-between;
            height: 140px;
            position: relative;
        }

        .card:hover {
            transform: translateY(-5px);
            border-color: var(--accent-color);
            box-shadow: var(--glow-shadow);
        }

        .card.active {
            border-color: var(--accent-color);
            background: rgba(255, 59, 48, 0.05);
            box-shadow: var(--glow-shadow);
        }

        .delete-btn {
            position: absolute;
            top: 8px;
            right: 8px;
            background: rgba(255, 59, 48, 0.85);
            color: #fff;
            border: none;
            border-radius: 50%;
            width: 22px;
            height: 22px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            font-size: 14px;
            font-weight: bold;
            z-index: 10;
            opacity: 0;
            transition: all 0.2s ease;
        }

        .card:hover .delete-btn {
            opacity: 1;
        }

        .delete-btn:hover {
            background: #ff2d55;
            transform: scale(1.15);
        }

        .card img {
            width: 100%;
            height: 70px;
            object-fit: contain;
            margin-bottom: 10px;
            border-radius: 6px;
        }

        .card-name {
            font-size: 0.9rem;
            font-weight: 600;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            width: 100%;
        }

        .card-badge {
            position: absolute;
            top: 5px;
            right: 5px;
            font-size: 0.65rem;
            background: var(--accent-blue);
            padding: 2px 6px;
            border-radius: 8px;
            font-weight: 700;
            text-transform: uppercase;
        }

        .card-badge[data-category="4K"] {
            background: linear-gradient(135deg, #ffd700 0%, #ff8c00 100%);
            color: #000;
        }

        /* Toast notifications */
        .toast-container {
            position: fixed;
            bottom: 20px;
            right: 20px;
            z-index: 9999;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }

        .toast {
            background: #1c1c24;
            border: 1px solid var(--border-color);
            border-left: 4px solid var(--accent-blue);
            color: #fff;
            padding: 12px 24px;
            border-radius: 8px;
            font-weight: 600;
            font-size: 0.9rem;
            box-shadow: 0 5px 15px rgba(0,0,0,0.3);
            transform: translateY(100px);
            opacity: 0;
            transition: all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
        }

        .toast.show {
            transform: translateY(0);
            opacity: 1;
        }

        .toast.success { border-left-color: var(--accent-green); }
        .toast.warning { border-left-color: #ff9500; }
        .toast.error { border-left-color: var(--accent-color); }

        @media(max-width: 576px) {
            body { padding: 10px; }
            .grid {
                grid-template-columns: repeat(3, 1fr);
                gap: 8px;
            }
            .card {
                height: 110px;
                padding: 10px;
            }
            .card img {
                height: 50px;
            }
            .card-name {
                font-size: 0.75rem;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Velocity IPTV Dashboard</h1>
            <p>Live Scrape & Bypass Proxy Integration</p>
        </div>

        <div class="main-layout">
            <div class="player-card">
                <div class="player-wrapper" id="player-wrapper">
                    <video id="video" controls playsinline></video>
                    <div class="player-placeholder" id="player-placeholder">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                            <polygon points="5 3 19 12 5 21 5 3"></polygon>
                        </svg>
                        <span>Select a channel below to begin playback</span>
                    </div>
                </div>
            </div>

            <div class="panel">
                <div class="channel-info">
                    <span id="current-channel-badge" class="category-badge" style="display:none;">Live TV</span>
                    <h2 id="current-channel-title">No Channel Selected</h2>
                    <p style="color: var(--text-muted); font-size: 0.9rem; margin-top: 5px;">
                        Token Age: <span id="token-age-value">Never updated</span>
                    </p>
                </div>

                <div class="action-group">
                    <button id="play-browser-btn" class="btn btn-primary">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:4px;">
                            <polygon points="5 3 19 12 5 21 5 3"></polygon>
                        </svg>
                        Play in Browser
                    </button>
                    <a id="generic-intent-link" href="#" class="btn btn-secondary">Open in External Player (VLC)</a>
                    <a id="direct-stream-link" href="#" class="btn btn-green" target="_blank">Get Direct Stream Link</a>
                    <a href="/playlist.m3u" class="btn btn-secondary" target="_blank">Download M3U8 Playlist</a>
                    <button id="refresh-tokens-btn" class="btn btn-blue">Refresh Stream Tokens</button>
                    <button id="add-4k-btn" class="btn" style="background: linear-gradient(135deg, #ffd700 0%, #ff8c00 100%); color: #000; font-weight: 700; border: none; box-shadow: 0 0 10px rgba(255,215,0,0.2);">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:4px; stroke: #000;">
                            <line x1="12" y1="5" x2="12" y2="19"></line>
                            <line x1="5" y1="12" x2="19" y2="12"></line>
                        </svg>
                        Add 4K Playlist / Link
                    </button>
                </div>
            </div>
        </div>

        <div class="search-filter-section">
            <div class="search-bar">
                <svg viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                    <circle cx="11" cy="11" r="8"></circle>
                    <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
                </svg>
                <input type="text" id="search-input" placeholder="Search channels by name...">
            </div>
            <div class="tab-container" id="category-tabs">
                <button class="tab active" data-category="ALL">All Categories</button>
            </div>
        </div>

        <div class="grid" id="channels-grid"></div>
    </div>

    <!-- Modal for adding custom 4K channel/playlist -->
    <div class="modal-overlay" id="add-4k-modal">
        <div class="modal-content">
            <button class="modal-close" id="modal-close-btn">&times;</button>
            <div class="modal-header">Add 4K Playlist or Stream</div>
            <div class="form-group">
                <label for="input-4k-name">Channel or Playlist Name</label>
                <input type="text" id="input-4k-name" placeholder="e.g. Ultra HD Sports or My 4K Playlist">
            </div>
            <div class="form-group">
                <label for="input-4k-url">M3U8 Stream URL or M3U Playlist URL</label>
                <input type="text" id="input-4k-url" placeholder="http://example.com/stream.m3u8">
            </div>
            <div style="color: var(--text-muted); font-size: 0.8rem; margin-bottom: 20px; line-height: 1.4;">
                * If a single stream URL is provided, it will be added as one channel.<br>
                * If an M3U playlist link is provided, all channels inside it will be imported.
            </div>
            <div style="display: flex; gap: 10px;">
                <button class="btn btn-primary" id="save-4k-btn" style="flex: 1;">Save to 4K Grid</button>
                <button class="btn btn-secondary" id="cancel-4k-btn">Cancel</button>
            </div>
        </div>
    </div>

    <div class="toast-container" id="toast-container"></div>

    <script>
        var video = document.getElementById('video');
        var playerWrapper = document.getElementById('player-wrapper');
        var playerPlaceholder = document.getElementById('player-placeholder');
        var playBrowserBtn = document.getElementById('play-browser-btn');
        var refreshBtn = document.getElementById('refresh-tokens-btn');
        var searchInput = document.getElementById('search-input');
        
        var add4kBtn = document.getElementById('add-4k-btn');
        var add4kModal = document.getElementById('add-4k-modal');
        var cancel4kBtn = document.getElementById('cancel-4k-btn');
        var modalCloseBtn = document.getElementById('modal-close-btn');
        var save4kBtn = document.getElementById('save-4k-btn');
        var inputName = document.getElementById('input-4k-name');
        var inputUrl = document.getElementById('input-4k-url');
        
        var hls = null;
        var activeCard = null;
        var currentUrl = "";
        var currentName = "";
        var currentChannelId = "";
        var isPlayerLoaded = false;
        var allChannels = [];
        var activeCategory = "ALL";

        var storage = {
            getItem: function(key) {
                try { return localStorage.getItem(key); } catch (e) { return null; }
            },
            setItem: function(key, value) {
                try { localStorage.setItem(key, value); } catch (e) {}
            }
        };

        function showToast(message, type) {
            var container = document.getElementById('toast-container');
            var toast = document.createElement('div');
            toast.className = 'toast ' + (type || '');
            toast.innerText = message;
            container.appendChild(toast);
            
            setTimeout(function() { toast.classList.add('show'); }, 50);
            
            setTimeout(function() {
                toast.classList.remove('show');
                setTimeout(function() { toast.remove(); }, 300);
            }, 3500);
        }

        function selectChannel(ch, cardElement) {
            if (!ch || !ch.url) return;
            currentUrl = ch.url;
            currentName = ch.name;
            currentChannelId = ch.id;
            
            document.getElementById('current-channel-title').innerText = ch.name;
            var badge = document.getElementById('current-channel-badge');
            badge.innerText = ch.category || 'Live TV';
            badge.style.display = 'inline-block';
            
            // Format external app invocation
            var isHttps = ch.url.indexOf('https://') === 0;
            var streamUrlNoProtocol = ch.url.replace(/^https?:\\/\\//, '');
            var scheme = isHttps ? 'https' : 'http';
            document.getElementById('generic-intent-link').href = 'intent://' + streamUrlNoProtocol + '#Intent;scheme=' + scheme + ';type=video/*;end';
            document.getElementById('direct-stream-link').href = ch.url;

            if (ch.scraped_at) {
                var ageSec = Math.floor(Date.now() / 1000) - ch.scraped_at;
                var ageMin = Math.floor(ageSec / 60);
                document.getElementById('token-age-value').innerText = ageMin + "m ago (" + ageSec + "s)";
            } else {
                document.getElementById('token-age-value').innerText = "Unknown";
            }
            
            if (activeCard) activeCard.classList.remove('active');
            cardElement.classList.add('active');
            activeCard = cardElement;

            if (isPlayerLoaded) {
                loadBrowserPlayer(ch.url);
            }
        }

        function loadBrowserPlayer(url) {
            playerPlaceholder.style.display = "none";
            isPlayerLoaded = true;

            if (hls) {
                hls.destroy();
            }

            if (window.Hls && Hls.isSupported()) {
                hls = new Hls({
                    maxMaxBufferLength: 10,
                    enableWorker: true
                });
                hls.loadSource(url);
                hls.attachMedia(video);
                hls.on(Hls.Events.MANIFEST_PARSED, function() {
                    video.play().catch(function(e) { console.log("Auto-play blocked:", e); });
                });

                hls.on(Hls.Events.ERROR, function(event, data) {
                    if (data.fatal) {
                        switch (data.type) {
                            case Hls.ErrorTypes.NETWORK_ERROR:
                                if (data.response && data.response.code === 403) {
                                    showToast("Token expired. Auto-refreshing playlist...", "warning");
                                    autoRefreshAndPlay();
                                } else {
                                    console.log("Fatal HLS network error, retrying...", data);
                                    hls.startLoad();
                                }
                                break;
                            case Hls.ErrorTypes.MEDIA_ERROR:
                                console.log("Fatal HLS media error, attempting recovery...");
                                hls.recoverMediaError();
                                break;
                            default:
                                console.log("HLS unrecoverable playback error:", data);
                                hls.destroy();
                                showToast("Playback error occurred.", "error");
                                break;
                        }
                    }
                });
            } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
                video.src = url;
                video.play().catch(function(e) { console.log("Auto-play blocked:", e); });
            }
        }

        function fetchServerRefresh(onComplete, onError) {
            fetch('/api/channels/refresh')
                .then(function(res) { return res.json(); })
                .then(function(data) {
                    if (data && data.channels && data.channels.length > 0) {
                        allChannels = data.channels;
                        storage.setItem('iptv_channels', JSON.stringify(allChannels));
                        updateCategoryTabs(allChannels);
                        renderChannels(allChannels);
                        if (onComplete) onComplete(allChannels);
                    } else {
                        if (onError) onError("Server-side refresh failed.");
                    }
                })
                .catch(function(e) { if (onError) onError(e); });
        }

        // --- Client-side CORS proxy scrape with multi-proxy fallback ---
        var CORS_PROXIES = [
            "https://corsproxy.io/?https://ajobtv.com/",
            "https://api.allorigins.win/raw?url=https%3A%2F%2Fajobtv.com%2F",
            "https://api.codetabs.com/v1/proxy?quest=https://ajobtv.com/",
            "https://thingproxy.freeboard.io/fetch/https://ajobtv.com/"
        ];

        function parseChannelsFromHtml(html) {
            // Fix: use single-escaped regex (\\s becomes \s in JS)
            var patterns = [
                /(?:const|var|let)\s+channels\s*=\s*(\[[\s\S]*?\]);/,
                /channels\s*:\s*(\[[\s\S]*?\])[,\s}]/
            ];
            for (var p = 0; p < patterns.length; p++) {
                var match = html.match(patterns[p]);
                if (match) {
                    try {
                        var channelsData = JSON.parse(match[1]);
                        var formatted = channelsData.map(function(ch) {
                            var url = (ch.play_url || "").replace(/\\\//g, '/');
                            if (url && url.indexOf('token=') !== -1 && url.indexOf('remote=') === -1) {
                                url += (url.indexOf('?') !== -1 ? '&' : '?') + 'remote=no_check_ip';
                            }
                            return {
                                name: ch.name || ch.channel_name || "Unknown",
                                url: url,
                                logo: ch.logo || ch.channel_logo || "",
                                stream_source: (ch.stream_source || "").replace(/\\\//g, '/'),
                                category: ch.category_name || "Live TV"
                            };
                        }).filter(function(ch) { return ch.url; });
                        if (formatted.length > 0) return formatted;
                    } catch(e) { continue; }
                }
            }
            // Fallback: scan for raw m3u8 URLs
            var m3uRegex = /(https?:\/\/[^\s"'`]+\.m3u8(?:[^\s"'`]*)?)/g;
            var m3uMatches = html.match(m3uRegex);
            if (m3uMatches && m3uMatches.length > 0) {
                return m3uMatches.map(function(url, i) {
                    url = url.replace(/\\\//g, '/');
                    if (url.indexOf('token=') !== -1 && url.indexOf('remote=') === -1) {
                        url += (url.indexOf('?') !== -1 ? '&' : '?') + 'remote=no_check_ip';
                    }
                    return { name: "Channel " + (i+1), url: url, logo: "", stream_source: url.split('?')[0], category: "Live TV" };
                });
            }
            return [];
        }

        function submitChannelsToBackend(formatted, onComplete, onError) {
            if (!formatted || formatted.length === 0) { if (onError) onError("No valid channels to submit."); return; }
            console.log("Client scraped " + formatted.length + " channels. Submitting to backend...");
            fetch('/api/channels/update', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ channels: formatted })
            })
            .then(function(r) { return r.json(); })
            .then(function(res) {
                if (res.status === 'success') {
                    // Use channels returned directly in the response to avoid Vercel cold-start cache miss
                    var updated = (res.channels && res.channels.length > 0) ? res.channels : null;
                    if (updated) {
                        allChannels = mergeCustomChannels(updated);
                        storage.setItem('iptv_channels', JSON.stringify(allChannels));
                        updateCategoryTabs(allChannels);
                        renderChannels(allChannels);
                        if (onComplete) onComplete(allChannels);
                    } else {
                        // Fallback: try a GET in case in-memory cache persists (local dev)
                        fetch('/api/channels')
                            .then(function(r) { return r.json(); })
                            .then(function(fetched) {
                                if (fetched && fetched.length > 0) {
                                    allChannels = mergeCustomChannels(fetched);
                                    storage.setItem('iptv_channels', JSON.stringify(allChannels));
                                    updateCategoryTabs(allChannels);
                                    renderChannels(allChannels);
                                    if (onComplete) onComplete(allChannels);
                                } else {
                                    if (onError) onError("Failed to load updated channels.");
                                }
                            })
                            .catch(function(e) { if (onError) onError(e); });
                    }
                } else {
                    if (onError) onError("Update API returned status error.");
                }
            })
            .catch(function(e) { if (onError) onError(e); });
        }

        function tryProxies(proxyList, idx, onComplete, onError) {
            if (idx >= proxyList.length) {
                console.warn("All CORS proxies failed. Falling back to server-side refresh...");
                fetchServerRefresh(onComplete, onError);
                return;
            }
            var proxyUrl = proxyList[idx];
            console.log("Trying CORS proxy [" + idx + "]: " + proxyUrl);
            fetch(proxyUrl)
                .then(function(res) {
                    if (!res.ok) throw new Error("HTTP " + res.status);
                    return res.text();
                })
                .then(function(html) {
                    var formatted = parseChannelsFromHtml(html);
                    if (formatted.length > 0) {
                        submitChannelsToBackend(formatted, onComplete, onError);
                    } else {
                        console.warn("Proxy [" + idx + "] returned HTML but no channels found. Trying next proxy...");
                        tryProxies(proxyList, idx + 1, onComplete, onError);
                    }
                })
                .catch(function(err) {
                    console.warn("Proxy [" + idx + "] failed: " + err + ". Trying next...");
                    tryProxies(proxyList, idx + 1, onComplete, onError);
                });
        }

        function performClientScrape(onComplete, onError) {
            console.log("Starting client-side scrape with " + CORS_PROXIES.length + " proxy fallbacks...");
            tryProxies(CORS_PROXIES, 0, onComplete, onError);
        }

        function autoRefreshAndPlay() {
            var originalText = refreshBtn.innerText;
            refreshBtn.innerText = "Auto-Refreshing...";
            refreshBtn.disabled = true;

            performClientScrape(
                function(channels) {
                    var merged = mergeCustomChannels(channels);
                    allChannels = merged;
                    storage.setItem('iptv_channels', JSON.stringify(allChannels));
                    
                    var currentCh = allChannels.find(function(c) { return c.id === currentChannelId; });
                    if (currentCh) {
                        var card = document.getElementById('channel-card-' + currentCh.id);
                        if (card) selectChannel(currentCh, card);
                        var playUrl = currentCh.url;
                        if (currentCh.url.indexOf('http://') === 0 && currentCh.url.indexOf('hd.ctghub.com') === -1) {
                            playUrl = '/api/proxy?url=' + encodeURIComponent(currentCh.url);
                        }
                        loadBrowserPlayer(playUrl);
                        showToast("Token refreshed! Resuming play...", "success");
                    }
                    refreshBtn.innerText = originalText;
                    refreshBtn.disabled = false;
                },
                function(err) {
                    console.error("Auto-refresh failed", err);
                    showToast("Failed to refresh token automatically.", "error");
                    refreshBtn.innerText = originalText;
                    refreshBtn.disabled = false;
                }
            );
        }

        playBrowserBtn.onclick = function() {
            if (currentUrl) {
                var playUrl = currentUrl;
                if (currentUrl.indexOf('http://') === 0 && currentUrl.indexOf('hd.ctghub.com') === -1) {
                    playUrl = '/api/proxy?url=' + encodeURIComponent(currentUrl);
                }
                loadBrowserPlayer(playUrl);
            } else {
                showToast("Please select a channel first!", "warning");
            }
        };

        if (refreshBtn) {
            refreshBtn.onclick = function() {
                var originalText = refreshBtn.innerText;
                refreshBtn.innerText = "Refreshing...";
                refreshBtn.disabled = true;
                
                performClientScrape(
                    function(channels) {
                        allChannels = mergeCustomChannels(channels);
                        storage.setItem('iptv_channels', JSON.stringify(allChannels));
                        updateCategoryTabs(allChannels);
                        renderChannels(allChannels);
                        
                        if (currentChannelId) {
                            var currentCh = allChannels.find(function(c) { return c.id === currentChannelId; });
                            if (currentCh) {
                                var card = document.getElementById('channel-card-' + currentCh.id);
                                if (card) selectChannel(currentCh, card);
                             }
                        }
                        showToast("All channels refreshed successfully!", "success");
                        refreshBtn.innerText = originalText;
                        refreshBtn.disabled = false;
                    },
                    function(err) {
                        console.error("Manual refresh failed", err);
                        showToast("Failed to refresh channels.", "error");
                        refreshBtn.innerText = originalText;
                        refreshBtn.disabled = false;
                    }
                );
            };
        }

        function handleImageError(img, name) {
            img.src = 'https://via.placeholder.com/150/14141c/ffffff?text=' + encodeURIComponent(name);
            img.onerror = null;
        }

        function getCustom4KChannels() {
            var cached = storage.getItem('custom_4k_channels');
            if (cached) {
                try {
                    return JSON.parse(cached);
                } catch (e) {
                    return [];
                }
            }
            return [];
        }

        function mergeCustomChannels(channels) {
            var customChs = getCustom4KChannels();
            var existingIds = {};
            channels.forEach(function(c) { existingIds[c.id] = true; });
            customChs.forEach(function(c) {
                if (!existingIds[c.id]) {
                    channels.push(c);
                }
            });
            return channels;
        }

        function deleteCustomChannel(id) {
            var customChs = getCustom4KChannels();
            var filteredChs = customChs.filter(function(c) { return c.id !== id; });
            storage.setItem('custom_4k_channels', JSON.stringify(filteredChs));
            
            allChannels = allChannels.filter(function(c) { return c.id !== id; });
            storage.setItem('iptv_channels', JSON.stringify(allChannels));
            
            if (currentChannelId === id) {
                currentChannelId = null;
                currentUrl = null;
            }
            
            updateCategoryTabs(allChannels);
            renderChannels(allChannels);
            showToast("Channel deleted successfully", "success");
        }

        function reClean(str) {
            return str.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
        }

        function updateCategoryTabs(channels) {
            var tabsContainer = document.getElementById('category-tabs');
            tabsContainer.innerHTML = '<button class="tab active" data-category="ALL">All Categories</button>';
            
            var categories = {};
            channels.forEach(function(ch) {
                if (ch.category) categories[ch.category] = true;
            });
            
            Object.keys(categories).sort().forEach(function(cat) {
                var tab = document.createElement('button');
                tab.className = 'tab' + (cat === '4K' ? ' tab-4k' : '');
                tab.innerText = cat;
                tab.setAttribute('data-category', cat);
                tabsContainer.appendChild(tab);
            });

            var tabs = tabsContainer.querySelectorAll('.tab');
            tabs.forEach(function(tab) {
                tab.onclick = function() {
                    tabs.forEach(function(t) { t.classList.remove('active'); });
                    tab.classList.add('active');
                    activeCategory = tab.getAttribute('data-category');
                    renderChannels(allChannels);
                };
            });
        }

        function renderChannels(channels) {
            var grid = document.getElementById('channels-grid');
            grid.innerHTML = '';
            
            var query = searchInput.value.toLowerCase().trim();
            
            var filtered = channels.filter(function(ch) {
                var matchesCategory = (activeCategory === "ALL" || ch.category === activeCategory);
                var matchesSearch = (!query || ch.name.toLowerCase().indexOf(query) !== -1);
                return matchesCategory && matchesSearch;
            });

            if (filtered.length === 0) {
                grid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; color: var(--text-muted); padding: 40px 0;">No matching channels found.</div>';
                return;
            }

            filtered.forEach(function(ch, idx) {
                var card = document.createElement('div');
                card.className = 'card';
                card.id = 'channel-card-' + ch.id;
                if (currentChannelId === ch.id) {
                    card.classList.add('active');
                    activeCard = card;
                }
                
                var logoUrl = ch.logo || 'https://via.placeholder.com/150/14141c/ffffff?text=' + encodeURIComponent(ch.name);
                var safeName = ch.name.replace(/'/g, "\\\\'");
                
                var innerHTML = 
                    (ch.category ? '<span class="card-badge" data-category="' + ch.category + '">' + ch.category + '</span>' : '') +
                    '<img src="' + logoUrl + '" alt="' + ch.name + '" onerror="handleImageError(this, \\\'' + safeName + '\\\')">' +
                    '<div class="card-name">' + ch.name + '</div>';

                if (ch.id && ch.id.indexOf('custom_') === 0) {
                    innerHTML += '<button class="delete-btn" title="Delete Channel">&times;</button>';
                }

                card.innerHTML = innerHTML;
                card.onclick = function() { selectChannel(ch, card); };

                if (ch.id && ch.id.indexOf('custom_') === 0) {
                    var delBtn = card.querySelector('.delete-btn');
                    if (delBtn) {
                        delBtn.onclick = function(e) {
                            e.stopPropagation();
                            if (confirm("Are you sure you want to delete '" + ch.name + "'?")) {
                                deleteCustomChannel(ch.id);
                            }
                        };
                    }
                }

                grid.appendChild(card);
                
                if (!currentChannelId && idx === 0) {
                    selectChannel(ch, card);
                }
            });
        }

        searchInput.oninput = function() {
            renderChannels(allChannels);
        };

        add4kBtn.onclick = function() {
            add4kModal.style.display = 'flex';
            inputName.value = '';
            inputUrl.value = '';
        };

        function hideModal() {
            add4kModal.style.display = 'none';
        }

        cancel4kBtn.onclick = hideModal;
        modalCloseBtn.onclick = hideModal;

        save4kBtn.onclick = function() {
            var name = inputName.value.trim();
            var url = inputUrl.value.trim();

            if (!name || !url) {
                showToast("Please enter both Name and URL", "warning");
                return;
            }

            save4kBtn.innerText = "Processing...";
            save4kBtn.disabled = true;

            var proxiedUrl = '/api/proxy?url=' + encodeURIComponent(url);
            fetch(proxiedUrl)
                .then(function(res) {
                    if (!res.ok) throw new Error("HTTP " + res.status);
                    return res.text();
                })
                .then(function(text) {
                    var customChs = getCustom4KChannels();
                    
                    if (text.indexOf('#EXTINF:') !== -1) {
                        var lines = text.split(/\\r?\\n/);
                        var addedCount = 0;
                        var currentChannel = null;
                        
                        for (var i = 0; i < lines.length; i++) {
                            var line = lines[i].trim();
                            if (line.indexOf('#EXTINF:') === 0) {
                                currentChannel = {};
                                var commaIdx = line.lastIndexOf(',');
                                if (commaIdx !== -1) {
                                    currentChannel.name = line.substring(commaIdx + 1).trim();
                                } else {
                                    currentChannel.name = "Custom Channel " + (addedCount + 1);
                                }
                                var logoMatch = line.match(/tvg-logo="([^"]+)"/i);
                                if (logoMatch) {
                                    currentChannel.logo = logoMatch[1];
                                }
                            } else if (line && line.indexOf('#') !== 0) {
                                if (currentChannel) {
                                    currentChannel.url = line;
                                    currentChannel.category = "4K";
                                    currentChannel.id = 'custom_' + reClean(currentChannel.name) + '_' + Math.random().toString(36).substring(2, 7);
                                    
                                    if (line.indexOf('http://') !== 0 && line.indexOf('https://') !== 0) {
                                        try {
                                            var base = url.substring(0, url.lastIndexOf('/') + 1);
                                            currentChannel.url = base + line;
                                        } catch (e) {}
                                    }
                                    
                                    customChs.push(currentChannel);
                                    addedCount++;
                                    currentChannel = null;
                                }
                            }
                        }
                        
                        if (addedCount > 0) {
                            storage.setItem('custom_4k_channels', JSON.stringify(customChs));
                            showToast("Successfully imported " + addedCount + " channels from playlist!", "success");
                        } else {
                            showToast("No channels found in the playlist.", "warning");
                        }
                    } else {
                        var newCh = {
                            id: 'custom_' + reClean(name) + '_' + Math.random().toString(36).substring(2, 7),
                            name: name,
                            url: url,
                            logo: "https://img.icons8.com/color/144/4k-resolution.png",
                            category: "4K"
                        };
                        customChs.push(newCh);
                        storage.setItem('custom_4k_channels', JSON.stringify(customChs));
                        showToast("Successfully added single stream: " + name, "success");
                    }
                    
                    allChannels = mergeCustomChannels(allChannels);
                    storage.setItem('iptv_channels', JSON.stringify(allChannels));
                    
                    activeCategory = '4K';
                    updateCategoryTabs(allChannels);
                    
                    var tabs = document.querySelectorAll('.tab');
                    tabs.forEach(function(t) {
                        t.classList.remove('active');
                        if (t.getAttribute('data-category') === '4K') {
                            t.classList.add('active');
                        }
                    });
                    
                    renderChannels(allChannels);
                    hideModal();
                    save4kBtn.innerText = "Save to 4K Grid";
                    save4kBtn.disabled = false;
                })
                .catch(function(err) {
                    console.error("Error loading playlist:", err);
                    var customChs = getCustom4KChannels();
                    var newCh = {
                        id: 'custom_' + reClean(name) + '_' + Math.random().toString(36).substring(2, 7),
                        name: name,
                        url: url,
                        logo: "https://img.icons8.com/color/144/4k-resolution.png",
                        category: "4K"
                    };
                    customChs.push(newCh);
                    storage.setItem('custom_4k_channels', JSON.stringify(customChs));
                    
                    allChannels = mergeCustomChannels(allChannels);
                    storage.setItem('iptv_channels', JSON.stringify(allChannels));
                    
                    activeCategory = '4K';
                    updateCategoryTabs(allChannels);
                    
                    var tabs = document.querySelectorAll('.tab');
                    tabs.forEach(function(t) {
                        t.classList.remove('active');
                        if (t.getAttribute('data-category') === '4K') {
                            t.classList.add('active');
                        }
                    });
                    
                    renderChannels(allChannels);
                    showToast("Added as single channel (offline check)", "success");
                    hideModal();
                    save4kBtn.innerText = "Save to 4K Grid";
                    save4kBtn.disabled = false;
                });
        };

        function init() {
            var cachedData = storage.getItem('iptv_channels');
            var hasLoadedFromCache = false;

            if (cachedData) {
                try {
                    var parsed = JSON.parse(cachedData);
                    if (parsed && parsed.length > 0) {
                        allChannels = mergeCustomChannels(parsed);
                        updateCategoryTabs(allChannels);
                        renderChannels(allChannels);
                        hasLoadedFromCache = true;
                    }
                } catch (e) {
                    console.error("Cache parse error", e);
                }
            }

            fetch('/api/channels')
                .then(function(res) { return res.json(); })
                .then(function(channels) {
                    if (channels && channels.length > 0) {
                        allChannels = mergeCustomChannels(channels);
                        storage.setItem('iptv_channels', JSON.stringify(allChannels));
                        updateCategoryTabs(allChannels);
                        renderChannels(allChannels);
                        
                        if (currentChannelId) {
                            var currentCh = allChannels.find(function(c) { return c.id === currentChannelId; });
                            if (currentCh) {
                                var card = document.getElementById('channel-card-' + currentCh.id);
                                if (card) selectChannel(currentCh, card);
                            }
                        }
                    }
                    performClientScrape();
                })
                .catch(function(e) {
                    console.error("Fetch channels error, attempting client scrape...", e);
                    performClientScrape(
                        function() { /* Succeeded, UI already rendered */ },
                        function() {
                            if (!hasLoadedFromCache) {
                                document.getElementById('channels-grid').innerHTML = 
                                    '<div style="grid-column: 1/-1; text-align: center; color: var(--text-muted); padding: 40px 0;">Failed to load channels from server.</div>';
                            }
                        }
                    );
                });
        }
        init();
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
