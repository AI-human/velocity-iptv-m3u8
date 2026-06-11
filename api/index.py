import os
import re
import json
import time
import requests
from bs4 import BeautifulSoup
from flask import Flask, Response, jsonify, render_template_string

app = Flask(__name__)

# Cache tokens in memory for 10 minutes (600 seconds) to ensure speed and prevent rate-limiting
CACHE_EXPIRY = 600  
cached_channels = None
last_cache_time = 0

# Path to the pre-generated JSON file
JSON_FILE_PATH = os.path.join(os.path.dirname(__file__), "..", "channels.json")

# Prevent caching of all responses in the client/browser
@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

def scrape_fresh_tokens():
    """Scrapes the live website to retrieve the latest tokenized m3u8 stream URLs."""
    url = "https://ajobtv.com/"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    found_urls = {}
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            html_content = response.text
            
            # Method 1: Parse standard video/source elements
            soup = BeautifulSoup(html_content, 'html.parser')
            for element in soup.find_all(['source', 'video', 'iframe']):
                src = element.get('src') or element.get('data-src')
                if src and '.m3u8' in src:
                    base = src.split('?')[0]
                    found_urls[base] = src
            
            # Method 2: Regex scanning (for javascript configuration blocks)
            regex_pattern = r'(https?://[^\s"\'\`]+\.m3u8(?:[^\s"\'\`]*)?)'
            matches = re.findall(regex_pattern, html_content)
            for match in matches:
                clean_url = match.replace('\\/', '/')
                base = clean_url.split('?')[0]
                found_urls[base] = clean_url
    except Exception as e:
        print(f"Error scraping tokens: {e}")
        
    return found_urls

def load_channels():
    global cached_channels, last_cache_time
    
    current_time = time.time()
    # Return memory cache if it's still valid
    if cached_channels and (current_time - last_cache_time < CACHE_EXPIRY):
        return cached_channels

    # Load base channels list
    channels = []
    if os.path.exists(JSON_FILE_PATH):
        try:
            with open(JSON_FILE_PATH, 'r', encoding='utf-8') as f:
                # Deep copy to prevent mutating the original reference
                channels = json.load(f)
        except Exception as e:
            print(f"Error reading JSON database: {e}")
            return []

    # Fetch fresh tokenized URLs
    fresh_links = scrape_fresh_tokens()
    
    # Merge fresh tokens into our channel structure matching by base stream path
    for ch in channels:
        base_url = ch["url"].split('?')[0]
        if base_url in fresh_links:
            ch["url"] = fresh_links[base_url]

    # Save to cache
    cached_channels = channels
    last_cache_time = current_time
    
    return channels

@app.route("/api/channels")
def get_channels():
    return jsonify(load_channels())

@app.route("/playlist.m3u")
def get_m3u_playlist():
    channels = load_channels()
    m3u_content = "#EXTM3U\n"
    
    for channel in channels:
        logo_part = f' tvg-logo="{channel["logo"]}"' if channel["logo"] else ''
        m3u_content += (
            f'#EXTINF:-1 tvg-id="{channel["id"]}"{logo_part} '
            f'group-title="Live TV",{channel["name"]}\n'
            f'{channel["url"]}\n'
        )
        
    return Response(m3u_content, mimetype="text/plain")

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)

# HTML Template optimized for low footprint and multiple TV/Android Player integrations
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>IPTV Player Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0f0f11;
            --card-bg: #1c1c1e;
            --accent-color: #ff3b30;
            --text-color: #f2f2f7;
            --text-muted: #8e8e93;
        }
        body {
            font-family: 'Inter', sans-serif;
            background: var(--bg-color);
            color: var(--text-color);
            margin: 0;
            padding: 20px;
        }
        .header {
            text-align: center;
            margin-bottom: 25px;
        }
        .header h1 {
            margin: 0 0 5px 0;
            font-weight: 700;
        }
        .header p {
            color: var(--text-muted);
            margin: 0;
        }
        .player-wrapper {
            width: 100%;
            max-width: 800px;
            margin: 0 auto 25px auto;
            background: #000;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 10px 30px rgba(0,0,0,0.5);
        }
        video {
            width: 100%;
            display: block;
            aspect-ratio: 16/9;
        }
        .controls {
            padding: 15px;
            background: #1c1c1e;
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 15px;
            flex-wrap: wrap;
        }
        .btn-group {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }
        .btn {
            padding: 8px 16px;
            background: var(--accent-color);
            color: white;
            text-decoration: none;
            border-radius: 8px;
            font-weight: 600;
            font-size: 13px;
            transition: opacity 0.2s;
            border: none;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
        }
        .btn:hover {
            opacity: 0.9;
        }
        .btn-secondary {
            background: #3a3a3c;
        }
        .btn-green {
            background: #34c759;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
            gap: 15px;
            max-width: 1200px;
            margin: 0 auto;
        }
        .card {
            background: var(--card-bg);
            border-radius: 10px;
            padding: 15px;
            text-align: center;
            cursor: pointer;
            border: 2px solid transparent;
            transition: all 0.2s;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            align-items: center;
            height: 120px;
        }
        .card:hover {
            transform: translateY(-5px);
            border-color: var(--accent-color);
        }
        .card.active {
            border-color: var(--accent-color);
            background: #2c2c2e;
        }
        .card img {
            width: 100%;
            height: 60px;
            object-fit: contain;
            margin-bottom: 10px;
            border-radius: 4px;
        }
        .card-name {
            font-size: 13px;
            font-weight: 600;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            width: 100%;
        }
        @media(max-width: 768px) {
            .grid {
                grid-template-columns: repeat(3, 1fr);
                gap: 10px;
            }
            body {
                padding: 10px;
            }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>IPTV Player Dashboard</h1>
        <p>Stream directly in browser or open via VLC / IPTV apps</p>
    </div>

    <div class="player-wrapper" id="player-wrapper" style="display: none;">
        <video id="video" controls playsinline></video>
    </div>

    <div style="max-width: 800px; margin: 0 auto 25px auto; background: #1c1c1e; border-radius: 12px; padding: 15px; box-shadow: 0 10px 30px rgba(0,0,0,0.5);">
        <div class="controls" style="padding: 0; background: transparent;">
            <span id="current-channel-title" style="font-weight:600; font-size: 16px;">Select a channel</span>
            <div class="btn-group">
                <a id="generic-intent-link" href="#" class="btn">Play in Player</a>
                <a id="direct-stream-link" href="#" class="btn btn-green" target="_blank">Direct Stream URL</a>
                <button id="play-browser-btn" class="btn btn-secondary">Play in Browser</button>
                <a href="/playlist.m3u" class="btn btn-secondary" target="_blank">Get M3U Playlist</a>
            </div>
        </div>
    </div>

    <div class="grid" id="channels-grid"></div>

    <script>
        const video = document.getElementById('video');
        const playerWrapper = document.getElementById('player-wrapper');
        const playBrowserBtn = document.getElementById('play-browser-btn');
        let hls = null;
        let activeCard = null;
        let currentUrl = "";
        let currentName = "";
        let isPlayerLoaded = false;

        function selectChannel(url, name, cardElement) {
            currentUrl = url;
            currentName = name;
            document.getElementById('current-channel-title').innerText = name;
            
            // Scheme 1: Generic Intent URL (Ideal for launching any installed video player on Android/TV)
            const isHttps = url.startsWith('https://');
            const streamUrlNoProtocol = url.replace(/^https?:\/\//, '');
            const scheme = isHttps ? 'https' : 'http';
            document.getElementById('generic-intent-link').href = `intent://${streamUrlNoProtocol}#Intent;scheme=${scheme};type=video/*;end`;
            
            // Scheme 2: Direct link to the raw .m3u8 file
            document.getElementById('direct-stream-link').href = url;
            
            if (activeCard) activeCard.classList.remove('active');
            cardElement.classList.add('active');
            activeCard = cardElement;

            // If browser player was already activated, switch the active stream
            if (isPlayerLoaded) {
                loadBrowserPlayer(url);
            }
        }

        function loadBrowserPlayer(url) {
            playerWrapper.style.display = "block";
            isPlayerLoaded = true;

            if (hls) {
                hls.destroy();
            }

            if (Hls.isSupported()) {
                hls = new Hls({
                    maxMaxBufferLength: 10
                });
                hls.loadSource(url);
                hls.attachMedia(video);
                hls.on(Hls.Events.MANIFEST_PARSED, function() {
                    video.play().catch(e => console.log("Play blocked: ", e));
                });
            } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
                video.src = url;
                video.play().catch(e => console.log("Play blocked: ", e));
            }
        }

        playBrowserBtn.onclick = () => {
            if (currentUrl) {
                loadBrowserPlayer(currentUrl);
            } else {
                alert("Please select a channel first!");
            }
        };

        async function init() {
            const res = await fetch('/api/channels');
            const channels = await res.json();
            const grid = document.getElementById('channels-grid');
            
            if (channels.length === 0) {
                grid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; color: var(--text-muted);">No channels found. Please upload/check IPTV Player.html</div>';
                return;
            }

            channels.forEach((ch, idx) => {
                const card = document.createElement('div');
                card.className = 'card';
                const logoUrl = ch.logo && !ch.logo.startsWith('./') ? ch.logo : 'https://via.placeholder.com/150/1c1c1e/ffffff?text=' + encodeURIComponent(ch.name);
                card.innerHTML = `
                    <img src="${logoUrl}" alt="${ch.name}" onerror="this.src='https://via.placeholder.com/150/1c1c1e/ffffff?text=${encodeURIComponent(ch.name)}'">
                    <div class="card-name">${ch.name}</div>
                `;
                card.onclick = () => selectChannel(ch.url, ch.name, card);
                grid.appendChild(card);
                
                if (idx === 0) {
                    selectChannel(ch.url, ch.name, card);
                }
            });
        }
        init();
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
