/**
 * IPTV Console Scraper — Paste this into Kiwi Browser console while on ajobtv.com
 * 
 * This is the JavaScript equivalent of scrape_tokens.py
 * It extracts channels from the page, generates M3U, and pushes to GitHub Gist.
 * 
 * Usage: Open ajobtv.com in Kiwi Browser → Dev Tools → Console → Paste & Enter
 */

(async function () {
    // ===== CONFIG =====
    const GIST_ID = 'YOUR_GIST_ID_HERE';  // Replace with your Gist ID
    const GITHUB_TOKEN = 'YOUR_GITHUB_TOKEN_HERE';  // Replace with your GitHub token

    // ===== STEP 1: Extract channels from page =====
    console.log('🔄 Step 1: Extracting channels from page...');

    let channelsRaw = null;
    const scripts = document.querySelectorAll('script');

    for (let i = 0; i < scripts.length; i++) {
        const text = scripts[i].textContent || '';
        const match = text.match(/const\s+channels\s*=\s*(\[[\s\S]*?\]);\s*\n/);
        if (match) {
            try {
                channelsRaw = JSON.parse(match[1]);
            } catch (e) {
                try { channelsRaw = (new Function('return ' + match[1]))(); } catch (e2) { }
            }
            if (channelsRaw) break;
        }
    }

    if (!channelsRaw || channelsRaw.length === 0) {
        alert('❌ No channels found on this page! Make sure you are on ajobtv.com');
        return;
    }

    console.log(`✅ Found ${channelsRaw.length} channels`);

    // ===== STEP 2: Process channels (same logic as scrape_tokens.py) =====
    console.log('🔄 Step 2: Processing channels...');

    const channels = [];
    for (const ch of channelsRaw) {
        let playUrl = (ch.play_url || '').replace(/\\\//g, '/');
        const name = (ch.name || 'Unknown').trim();
        const logo = (ch.logo || '').trim();
        const category = (ch.category_name || 'Live TV').trim();

        if (!playUrl) continue;

        // Add remote=no_check_ip if token exists but remote doesn't
        if (playUrl.includes('token=') && !playUrl.includes('remote=')) {
            const sep = playUrl.includes('?') ? '&' : '?';
            playUrl += sep + 'remote=no_check_ip';
        }

        const chId = name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');

        channels.push({
            id: chId,
            name: name,
            logo: logo,
            url: playUrl,
            category: category,
            scraped_at: Math.floor(Date.now() / 1000)
        });
    }

    // Add default 4K channels
    const default4K = [
        { id: 'golive_4k', name: 'GoLive 4K', logo: 'https://img.icons8.com/color/144/4k-resolution.png', url: 'http://203.18.159.180/GoLIve/index.m3u8', category: '4K', scraped_at: Math.floor(Date.now() / 1000) },
        { id: 'hdr_4k', name: 'HDR 4K', logo: 'https://img.icons8.com/color/144/4k-resolution.png', url: 'https://go8knm.optikl.ink/OT/live/HDR/HDR/1950411.m3u8', category: '4K', scraped_at: Math.floor(Date.now() / 1000) }
    ];

    const existingIds = new Set(channels.map(c => c.id));
    for (const ch of default4K) {
        if (!existingIds.has(ch.id)) channels.push(ch);
    }

    console.log(`✅ Processed ${channels.length} total channels (including 4K)`);

    // ===== STEP 3: Generate M3U playlist =====
    console.log('🔄 Step 3: Generating M3U playlist...');

    let m3u = '#EXTM3U\n';
    for (const ch of channels) {
        let logoUrl = '';
        if (ch.logo) {
            logoUrl = ch.logo.startsWith('http') ? ch.logo : 'https://ajobtv.com/assets/images/channels/' + ch.logo;
        }
        const logoPart = logoUrl ? ` tvg-logo="${logoUrl}"` : '';

        m3u += `#EXTINF:-1 tvg-id="${ch.id}"${logoPart} tvg-name="${ch.name}" group-title="${ch.category}",${ch.name}\n`;
        m3u += ch.url + '\n';
    }

    // ===== STEP 4: Push to GitHub Gist =====
    console.log('🔄 Step 4: Pushing to GitHub Gist...');

    try {
        const response = await fetch('https://api.github.com/gists/' + GIST_ID, {
            method: 'PATCH',
            headers: {
                'Authorization': 'token ' + GITHUB_TOKEN,
                'Accept': 'application/vnd.github.v3+json',
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                description: 'Velocity IPTV Live M3U Playlist - Auto Updated',
                files: {
                    'playlist.m3u': { content: m3u },
                    'playlist.m3u8': { content: m3u },
                    'channels.json': { content: JSON.stringify(channels, null, 2) }
                }
            })
        });

        if (!response.ok) {
            throw new Error('HTTP ' + response.status + ' ' + response.statusText);
        }

        const data = await response.json();

        console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
        console.log('✅ SUCCESS! Gist updated with ' + channels.length + ' channels');
        console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
        for (const [filename, file] of Object.entries(data.files)) {
            console.log(filename + ': ' + file.raw_url.replace(/\/raw\/[a-f0-9]+\//, '/raw/'));
        }
        console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');

        alert('✅ SUCCESS! Updated ' + channels.length + ' channels on Gist');

    } catch (err) {
        console.error('❌ Failed to update Gist:', err);
        alert('❌ Failed: ' + err.message);
    }
})();
