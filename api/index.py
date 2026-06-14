import os
import re
import json
import time
import requests
from bs4 import BeautifulSoup
from flask import Flask, Response, jsonify, render_template_string, request, redirect

app = Flask(__name__)

# Cache tokens in memory for 10 minutes (600 seconds) to ensure speed and prevent rate-limiting
CACHE_EXPIRY = 600  
cached_channels = None
last_cache_time = 0

# Path to the pre-generated JSON file
JSON_FILE_PATH = os.path.join(os.path.dirname(__file__), "..", "channels.json")

# Prevent caching of all responses in the client/browser except static assets (logos)
@app.after_request
def add_header(response):
    # Enable CORS globally for older Android TV platforms, web players, and external apps
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

def get_base_url():
    """Dynamically resolves the external scheme and host for Vercel/reverse proxies."""
    try:
        scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
        return f"{scheme}://{request.host}/"
    except Exception:
        return "/"

def scrape_fresh_tokens():
    """Scrapes the live website and parses the channels JSON array to get fresh play URLs."""
    url = "https://ajobtv.com/"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    found_urls = {}
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            html_content = response.text
            # Extract the channels array definition from the inline javascript script block
            match = re.search(r'const\s+channels\s*=\s*(\[[\s\S]*?\]);', html_content)
            if match:
                channels_data = json.loads(match.group(1))
                for ch in channels_data:
                    stream_source = ch.get("stream_source")
                    play_url = ch.get("play_url")
                    if stream_source and play_url:
                        base = stream_source.split('?')[0]
                        found_urls[base] = play_url
    except Exception as e:
        print(f"Error scraping tokens: {e}")
        
    return found_urls

def load_channels(force=False):
    global cached_channels, last_cache_time
    
    current_time = time.time()
    # Return memory cache if it's still valid and not forced
    if not force and cached_channels and (current_time - last_cache_time < CACHE_EXPIRY):
        return cached_channels

    # Load base channels list
    channels = []
    if os.path.exists(JSON_FILE_PATH):
        try:
            with open(JSON_FILE_PATH, 'r', encoding='utf-8') as f:
                # Load channels from database file
                channels = json.load(f)
        except Exception as e:
            print(f"Error reading JSON database: {e}")
            return []

    # Fetch fresh tokenized URLs
    fresh_links = scrape_fresh_tokens()
    
    # Check if we got any fresh links before merging/updating
    if fresh_links:
        # Merge fresh tokens into our channel structure matching by base stream path
        for ch in channels:
            base_url = ch["url"].split('?')[0]
            if base_url in fresh_links:
                ch["url"] = fresh_links[base_url]
                
            # Fix logo URL dynamically to use our own hosted static logos
            if ch.get("logo"):
                logo_file = os.path.basename(ch["logo"])
                ch["logo"] = f"{get_base_url()}static/logos/{logo_file}"
                
        # Try to persist the updated channels back to channels.json if possible
        # (fails gracefully on read-only serverless environments like Vercel)
        try:
            with open(JSON_FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(channels, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not write updated channels to file: {e}")

        # Update cache only if scrape was successful
        cached_channels = channels
        last_cache_time = current_time
    else:
        # If scrape failed but we have a memory cache, keep using the memory cache
        # Otherwise, load channel details without token update
        if not cached_channels:
            # Fix logo URLs even if scrape failed
            for ch in channels:
                if ch.get("logo"):
                    logo_file = os.path.basename(ch["logo"])
                    ch["logo"] = f"{get_base_url()}static/logos/{logo_file}"
            cached_channels = channels
            last_cache_time = current_time

    return cached_channels


@app.route("/api/channels")
def get_channels():
    return jsonify(load_channels())

@app.route("/playlist.m3u")
@app.route("/playlist.m3u8")
@app.route("/playlist")
def get_m3u_playlist():
    channels = load_channels()
    m3u_content = "#EXTM3U\n"
    
    # Use direct URLs in the playlist if ?direct=true is requested, otherwise use proxied URLs
    use_direct = request.args.get("direct") == "true"
    base_url = get_base_url()
    
    for channel in channels:
        logo_part = f' tvg-logo="{channel["logo"]}"' if channel["logo"] else ''
        if use_direct:
            stream_url = channel["url"]
        else:
            stream_url = f"{base_url}live/{channel['id']}.m3u8"
            
        m3u_content += (
            f'#EXTINF:-1 tvg-id="{channel["id"]}"{logo_part} '
            f'group-title="Live TV",{channel["name"]}\n'
            f'{stream_url}\n'
        )
        
    # We use 'application/x-mpegurl; charset=utf-8' for maximum compatibility with IPTV software/hardware
    response = Response(m3u_content, mimetype="application/x-mpegurl; charset=utf-8")
    response.headers["Content-Disposition"] = 'attachment; filename="playlist.m3u"'
    return response

@app.route("/api/channels/refresh", methods=["GET", "POST"])
def refresh_channels():
    # Force a scrape by passing force=True
    channels = load_channels(force=True)
    
    # We can inspect if the fresh URLs have tokens to verify success
    has_tokens = any("token=" in ch["url"] for ch in channels)
    if not has_tokens:
        return jsonify({
            "status": "error",
            "message": "Failed to scrape fresh tokens from ajobtv. Please check server logs."
        }), 500
        
    return jsonify({
        "status": "success",
        "message": f"Successfully refreshed {len(channels)} channels from ajobtv",
        "channels": channels
    })

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
        r = requests.get(target_url, headers=headers, timeout=6, allow_redirects=True)
        if r.status_code == 200:
            final_url = r.url
            content = r.text
            
            # Rewrite relative TS segment URLs to absolute and append &remote=no_check_ip
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
        
    target_url = channel["url"]
    
    # If the player explicitly requests a 302 redirect
    if request.args.get("redirect") == "true":
        response = redirect(target_url, code=302)
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response

    # Default: Proxy the main index .m3u8 playlist to prevent 302 redirect.
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    try:
        r = requests.get(target_url, headers=headers, timeout=6, allow_redirects=True)
        if r.status_code == 200:
            final_url = r.url
            content = r.text
            
            # Rewrite relative URLs to absolute URLs and wrap with our sub-playlist proxy
            from urllib.parse import urljoin
            lines = content.splitlines()
            new_lines = []
            for line in lines:
                line_stripped = line.strip()
                if not line_stripped:
                    continue
                if line_stripped.startswith('#'):
                    # Search and replace any relative URI attributes (e.g., URI="key.key")
                    def replace_uri(match):
                        uri = match.group(1)
                        resolved_uri = urljoin(final_url, uri)
                        if "token=" in resolved_uri and "remote=" not in resolved_uri:
                            separator = "&" if "?" in resolved_uri else "?"
                            resolved_uri += f"{separator}remote=no_check_ip"
                        # Redirect sub-playlist through our proxy
                        resolved_uri = resolved_uri.replace("https://hd.ctghub.com/", f"{get_base_url()}live-sub/")
                        return f'URI="{resolved_uri}"'
                    processed_line = re.sub(r'URI="([^"]+)"', replace_uri, line)
                    new_lines.append(processed_line)
                else:
                    # Resolve relative URL line
                    resolved_line = urljoin(final_url, line_stripped)
                    if "token=" in resolved_line and "remote=" not in resolved_line:
                        separator = "&" if "?" in resolved_line else "?"
                        resolved_line += f"{separator}remote=no_check_ip"
                    # Redirect sub-playlist through our proxy
                    resolved_line = resolved_line.replace("https://hd.ctghub.com/", f"{get_base_url()}live-sub/")
                    new_lines.append(resolved_line)
            
            proxied_m3u8 = "\n".join(new_lines)
            
            # Serve as HLS playlist mimetype
            response = Response(proxied_m3u8, mimetype="application/vnd.apple.mpegurl")
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            return response
            
    except Exception as e:
        print(f"Error proxying stream from {target_url}: {e}")
        
    # Fallback to redirect if proxying fails (e.g. timeout or fetch failure)
    response = redirect(target_url, code=302)
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


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
                <button id="refresh-tokens-btn" class="btn" style="background: #007aff;">Refresh Tokens</button>
            </div>
        </div>
    </div>

    <div class="grid" id="channels-grid"></div>

    <script>
        var video = document.getElementById('video');
        var playerWrapper = document.getElementById('player-wrapper');
        var playBrowserBtn = document.getElementById('play-browser-btn');
        var refreshBtn = document.getElementById('refresh-tokens-btn');
        var hls = null;
        var activeCard = null;
        var currentUrl = "";
        var currentName = "";
        var isPlayerLoaded = false;

        // Safe localStorage wrapper to prevent crashes on TV browsers that block it
        var storage = {
            getItem: function(key) {
                try {
                    return localStorage.getItem(key);
                } catch (e) {
                    console.warn("localStorage read blocked", e);
                    return null;
                }
            },
            setItem: function(key, value) {
                try {
                    localStorage.setItem(key, value);
                } catch (e) {
                    console.warn("localStorage write blocked", e);
                }
            }
        };

        function selectChannel(url, name, cardElement) {
            if (!url) return;
            currentUrl = url;
            currentName = name;
            document.getElementById('current-channel-title').innerText = name;
            
            var isHttps = url.indexOf('https://') === 0;
            var streamUrlNoProtocol = url.replace(/^https?:\\/\\//, '');
            var scheme = isHttps ? 'https' : 'http';
            document.getElementById('generic-intent-link').href = 'intent://' + streamUrlNoProtocol + '#Intent;scheme=' + scheme + ';type=video/*;end';
            document.getElementById('direct-stream-link').href = url;
            
            if (activeCard) activeCard.classList.remove('active');
            cardElement.classList.add('active');
            activeCard = cardElement;

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

            if (window.Hls && Hls.isSupported()) {
                hls = new Hls({
                    maxMaxBufferLength: 10
                });
                hls.loadSource(url);
                hls.attachMedia(video);
                hls.on(Hls.Events.MANIFEST_PARSED, function() {
                    video.play().catch(function(e) { console.log("Play blocked: ", e); });
                });
            } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
                video.src = url;
                video.play().catch(function(e) { console.log("Play blocked: ", e); });
            }
        }

        playBrowserBtn.onclick = function() {
            if (currentUrl) {
                loadBrowserPlayer(currentUrl);
            } else {
                alert("Please select a channel first!");
            }
        };

        if (refreshBtn) {
            refreshBtn.onclick = function() {
                var originalText = refreshBtn.innerText;
                refreshBtn.innerText = "Refreshing...";
                refreshBtn.disabled = true;
                refreshBtn.style.opacity = "0.6";
                
                fetch('/api/channels/refresh')
                    .then(function(res) { return res.json(); })
                    .then(function(data) {
                        refreshBtn.innerText = "Refreshed!";
                        setTimeout(function() {
                            refreshBtn.innerText = originalText;
                            refreshBtn.disabled = false;
                            refreshBtn.style.opacity = "1";
                        }, 2000);
                        
                        if (data && data.channels && data.channels.length > 0) {
                            var channels = data.channels;
                            storage.setItem('iptv_channels', JSON.stringify(channels));
                            updateChannelUrls(channels);
                        } else {
                            alert("Refresh completed, but no channels returned.");
                        }
                    })
                    .catch(function(e) {
                        console.error("Error refreshing tokens", e);
                        refreshBtn.innerText = "Failed!";
                        setTimeout(function() {
                            refreshBtn.innerText = originalText;
                            refreshBtn.disabled = false;
                            refreshBtn.style.opacity = "1";
                        }, 2000);
                        alert("Failed to refresh tokens. Please try again.");
                    });
            };
        }

        function handleImageError(img, name) {
            img.src = 'https://via.placeholder.com/150/1c1c1e/ffffff?text=' + encodeURIComponent(name);
            img.onerror = null;
        }

        function renderChannels(channels) {
            var grid = document.getElementById('channels-grid');
            grid.innerHTML = ''; 
            
            channels.forEach(function(ch, idx) {
                var card = document.createElement('div');
                card.className = 'card';
                card.id = 'channel-card-' + (ch.id || idx);
                var logoUrl = ch.logo && ch.logo.indexOf('./') !== 0 ? ch.logo : 'https://via.placeholder.com/150/1c1c1e/ffffff?text=' + encodeURIComponent(ch.name);
                var safeName = ch.name.replace(/'/g, "\\\\'");
                card.innerHTML = 
                    '<img src="' + logoUrl + '" alt="' + ch.name + '" onerror="handleImageError(this, \\\'' + safeName + '\\\')">' +
                    '<div class="card-name">' + ch.name + '</div>';
                
                card.onclick = function() { selectChannel(ch.url, ch.name, card); };
                grid.appendChild(card);
                
                if (idx === 0 && !activeCard) {
                    selectChannel(ch.url, ch.name, card);
                }
            });
        }

        function updateChannelUrls(channels) {
            channels.forEach(function(ch, idx) {
                var card = document.getElementById('channel-card-' + (ch.id || idx));
                if (card) {
                    card.onclick = function() { selectChannel(ch.url, ch.name, card); };
                    
                    if (card.classList.contains('active')) {
                        currentUrl = ch.url;
                        currentName = ch.name;
                        
                        var isHttps = ch.url.indexOf('https://') === 0;
                        var streamUrlNoProtocol = ch.url.replace(/^https?:\\/\\//, '');
                        var scheme = isHttps ? 'https' : 'http';
                        document.getElementById('generic-intent-link').href = 'intent://' + streamUrlNoProtocol + '#Intent;scheme=' + scheme + ';type=video/*;end';
                        document.getElementById('direct-stream-link').href = ch.url;
                        
                        if (isPlayerLoaded) {
                            loadBrowserPlayer(ch.url);
                        }
                    }
                }
            });
        }

        function init() {
            var grid = document.getElementById('channels-grid');
            var cachedData = storage.getItem('iptv_channels');
            var hasLoadedFromCache = false;

            if (cachedData) {
                try {
                    var channels = JSON.parse(cachedData);
                    if (channels && channels.length > 0) {
                        renderChannels(channels);
                        hasLoadedFromCache = true;
                    }
                } catch (e) {
                    console.error("Error parsing cached channels", e);
                }
            }

            fetch('/api/channels')
                .then(function(res) { return res.json(); })
                .then(function(channels) {
                    if (channels && channels.length > 0) {
                        storage.setItem('iptv_channels', JSON.stringify(channels));
                        if (!hasLoadedFromCache) {
                            renderChannels(channels);
                        } else {
                            updateChannelUrls(channels);
                        }
                    }
                })
                .catch(function(e) {
                    console.error("Error fetching channels", e);
                    if (!hasLoadedFromCache) {
                        grid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; color: var(--text-muted);">Failed to load channels.</div>';
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
