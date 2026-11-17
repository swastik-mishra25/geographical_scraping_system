import urllib.parse
from bs4 import BeautifulSoup
import requests
import base64

def decode_bing_url(bing_url: str) -> str:
    parsed = urllib.parse.urlparse(bing_url)
    params = urllib.parse.parse_qs(parsed.query)
    u_val = params.get('u', [''])[0]
    if not u_val:
        return bing_url
    raw = u_val[2:] if u_val.startswith(('a1', 'a0')) else u_val
    padded = raw + '=' * (-len(raw) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode('ascii')).decode('utf-8', errors='ignore')
    except Exception:
        return bing_url

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-IN,en;q=0.9',
}

queries = [
    # 1. Digital Marketing in Andheri
    '"digital marketing" "andheri" agency',
    # 2. Software Development in Pune
    '"software company" "pune" -wikipedia',
    # 3. Healthcare / Hospitals in Jaipur
    '"hospital" "jaipur" private',
    # 4. Real Estate in Hyderabad
    '"real estate" "hyderabad" properties',
    # 5. Manufacturing in Ahmedabad
    '"manufacturing company" "ahmedabad"',
    # 6. IT Services in Bhubaneswar
    '"IT company" "bhubaneswar" services',
]

for q in queries:
    url = f'https://www.bing.com/search?q={urllib.parse.quote(q)}&count=15'
    try:
        r = requests.get(url, headers=headers, timeout=6)
        soup = BeautifulSoup(r.text, 'html.parser')
        items = []
        for li in soup.select('li.b_algo'):
            h2 = li.select_one('h2 a')
            if h2 and h2.get('href'):
                real_url = decode_bing_url(h2['href'])
                title = h2.get_text(strip=True)
                domain = urllib.parse.urlparse(real_url).netloc.lower().replace('www.', '')
                if domain and '.' in domain and not any(k in domain for k in ['bing.', 'microsoft.', 'google.', 'wikipedia.']):
                    items.append({'domain': domain, 'title': title[:45]})
        print(f"\nQuery: {q} -> Found {len(items)} domains:")
        for it in items[:5]:
            print(f"   {it['domain']} | {it['title']}")
    except Exception as e:
        print(f"Error {q}: {e}")
