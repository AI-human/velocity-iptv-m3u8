import os
import json
from bs4 import BeautifulSoup

def main():
    html_path = "/home/metal/Agentic_Engineering/ip_tv_app/IPTV Player.html"
    json_path = "/home/metal/Agentic_Engineering/ip_tv_app/channels.json"
    
    if not os.path.exists(html_path):
        print(f"Error: {html_path} not found")
        return
        
    with open(html_path, 'r', encoding='utf-8') as f:
        content = f.read()
        
    soup = BeautifulSoup(content, 'html.parser')
    cards = soup.find_all(class_='channel-card')
    
    channels = []
    for card in cards:
        name = card.get('data-name')
        url = card.get('data-url')
        img_tag = card.find('img')
        logo = ""
        if img_tag:
            logo = img_tag.get('src', '')
            
        if name and url:
            channels.append({
                "id": name.lower().replace(" ", "_"),
                "name": name,
                "logo": logo,
                "url": url
            })
            
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(channels, f, indent=2)
        
    print(f"Successfully generated {len(channels)} channels to {json_path}")

if __name__ == "__main__":
    main()
