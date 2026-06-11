import os
import json
from flask import Flask, Response, jsonify, render_template_string

app = Flask(__name__)

# Prevent caching of all responses
@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# Path to the pre-generated JSON file
JSON_FILE_PATH = os.path.join(os.path.dirname(__file__), "..", "channels.json")

def load_channels():
    if os.path.exists(JSON_FILE_PATH):
        try:
            with open(JSON_FILE_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error reading JSON: {e}")
    return []

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

    <div class="player-wrapper">
        <video id="video" controls playsinline></video>
        <div class="controls">
            <span id="current-channel-title" style="font-weight:600;">Select a channel</span>
            <div class="btn-group">
                <a id="vlc-intent-link" href="#" class="btn">VLC Android</a>
                <a id="vlc-direct-link" href="#" class="btn btn-green">VLC (Direct M3U8)</a>
                <a href="/playlist.m3u" class="btn btn-secondary" target="_blank">Get M3U Playlist</a>
            </div>
        </div>
    </div>

    <div class="grid" id="channels-grid"></div>

    <script>
        const video = document.getElementById('video');
        const hls = new Hls({
            maxMaxBufferLength: 10
        });
        let activeCard = null;

        function playStream(url, name, cardElement, shouldPlay = true) {
            document.getElementById('current-channel-title').innerText = name;
            
            // Scheme 1: Intent URL (Ideal for browsers on mobile to launch VLC package)
            const streamUrlNoProtocol = url.replace(/^https?:\/\//, '');
            document.getElementById('vlc-intent-link').href = `intent://${streamUrlNoProtocol}#Intent;scheme=http;type=video/*;package=org.videolan.vlc;end`;
            
            // Scheme 2: Direct vlc:// protocol URL (Works on many systems/TVs where VLC handler is registered)
            document.getElementById('vlc-direct-link').href = `vlc://${url}`;
            
            if (activeCard) activeCard.classList.remove('active');
            cardElement.classList.add('active');
            activeCard = cardElement;

            if (Hls.isSupported()) {
                hls.loadSource(url);
                hls.attachMedia(video);
                hls.on(Hls.Events.MANIFEST_PARSED, function() {
                    if (shouldPlay) {
                        video.play().catch(e => console.log("Auto-play blocked: ", e));
                    }
                });
            } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
                video.src = url;
                if (shouldPlay) {
                    video.play().catch(e => console.log("Auto-play blocked: ", e));
                }
            }
        }

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
                card.onclick = () => playStream(ch.url, ch.name, card, true);
                grid.appendChild(card);
                
                if (idx === 0) {
                    playStream(ch.url, ch.name, card, false);
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
