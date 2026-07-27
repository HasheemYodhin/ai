import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs

def test_google_search(query, num_results=5):
    url = f"https://www.google.com/search?q={requests.utils.quote(query)}&num={num_results}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    
    print(f"Searching: {url}")
    response = requests.get(url, headers=headers, timeout=10)
    print(f"Status Code: {response.status_code}")
    
    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    
    h3s = soup.find_all("h3")
    for h3 in h3s:
        a_tag = h3.find_parent("a")
        if not a_tag:
            continue
        href = a_tag.get("href", "")
        if href.startswith("/url?"):
            parsed = urlparse(href)
            href = parse_qs(parsed.query).get("q", [None])[0] or href
        
        title = h3.get_text(strip=True)
        
        # Find the snippet
        snippet = ""
        parent_container = h3.find_parent("div", class_="g") or h3.find_parent("div")
        if parent_container:
            snippet_el = parent_container.select_one(".VwiC3b, .yDopNe, .st")
            if snippet_el:
                snippet = snippet_el.get_text(strip=True)
            else:
                text_parts = [t for t in parent_container.stripped_strings if t != title]
                snippet = " ".join(text_parts)[:200]
        
        if title and href:
            results.append({
                "title": title,
                "url": href,
                "snippet": snippet,
            })
            
    print(f"Found {len(results)} results:")
    for idx, r in enumerate(results):
        print(f"\n{idx+1}. {r['title']}\n   URL: {r['url']}\n   Snippet: {r['snippet']}")

if __name__ == "__main__":
    test_google_search("NVIDIA NIM minimax-m3")
