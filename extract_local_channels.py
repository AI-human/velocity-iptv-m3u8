from bs4 import BeautifulSoup

def extract_channels(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    soup = BeautifulSoup(content, 'html.parser')
    cards = soup.find_all(class_='channel-card')
    
    channels = []
    for card in cards:
        name = card.get('data-name')
        url = card.get('data-url')
        if name and url:
            channels.append((name, url))
            
    return channels

if __name__ == "__main__":
    file_path = "/home/metal/Agentic_Engineering/ip_tv_app/IPTV Player.html"
    channels = extract_channels(file_path)
    
    output_path = "/home/metal/Agentic_Engineering/ip_tv_app/channels.md"
    with open(output_path, 'w', encoding='utf-8') as out_f:
        out_f.write("# Extracted IPTV Channels\n\n")
        out_f.write("| Channel Name | M3U8 Stream URL |\n")
        out_f.write("| :--- | :--- |\n")
        for name, url in channels:
            out_f.write(f"| {name} | `{url}` |\n")
            
    print(f"Successfully extracted {len(channels)} channels to {output_path}")
