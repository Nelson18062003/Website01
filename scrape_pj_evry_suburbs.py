#!/usr/bin/env python3
"""
Scraper Pages Jaunes pour les communes de la banlieue d'Évry.
"""

import re
import json
import time
import base64
import sys

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    print("Installing curl_cffi...")
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "curl_cffi", "beautifulsoup4", "lxml"])
    from curl_cffi import requests as curl_requests

from bs4 import BeautifulSoup

OUTPUT_FILE = "/home/user/Website01/agent_out_2_pj_evry_suburbs.json"

CITIES = [
    ("Corbeil-Essonnes", "Corbeil-Essonnes+91100"),
    ("Ris-Orangis", "Ris-Orangis+91130"),
    ("Lisses", "Lisses+91090"),
    ("Bondoufle", "Bondoufle+91070"),
    ("Évry-Courcouronnes", "Evry-Courcouronnes+91000"),
    ("Courcouronnes", "Courcouronnes+91080"),
]

CATEGORIES = [
    "garage+automobile",
    "concession+automobile",
    "carrosserie+automobile",
    "garage+moto",
    "concession+moto",
]

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
    "Referer": "https://www.pagesjaunes.fr/",
}

IMPERSONATE = "safari17_2_ios"

PHONE_RE = re.compile(r'0[1-9][\s.]?\d{2}[\s.]?\d{2}[\s.]?\d{2}[\s.]?\d{2}')


def decode_pjlb_url(s):
    try:
        d = json.loads(s)
        u = d.get('url', '')
        if u:
            pad = 4 - len(u) % 4
            if pad != 4:
                u += '=' * pad
            return base64.b64decode(u).decode('utf-8', 'ignore')
    except Exception:
        pass
    return ''


def clean_phone(phone):
    return re.sub(r'[\s.]', '', phone)


def extract_listings(html, category, zone):
    soup = BeautifulSoup(html, 'lxml')
    results = []

    # Find all listing cards
    cards = soup.select('li.bi-generic, li.bi-pro, article.bi-generic, article.bi-pro, div.bi-generic, div.bi-pro')
    if not cards:
        # fallback: broader selector
        cards = soup.select('[class*="bi-"]')
    if not cards:
        cards = soup.select('div.trombi-item, div.listing-item')

    # Try another approach - look for structured data
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string)
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict) and data.get('@type') == 'ItemList':
                items = data.get('itemListElement', [])
            else:
                continue
            for item in items:
                if isinstance(item, dict):
                    thing = item.get('item', item)
                    name = thing.get('name', '')
                    addr = thing.get('address', {})
                    if isinstance(addr, str):
                        address_str = addr
                        cp = ''
                        city = ''
                    else:
                        address_str = addr.get('streetAddress', '')
                        cp = addr.get('postalCode', '')
                        city = addr.get('addressLocality', '')
                    phone = ''
                    if thing.get('telephone'):
                        phone = clean_phone(thing['telephone'])
                    url = thing.get('url', '')
                    if name:
                        results.append({
                            'nom': name,
                            'adresse': address_str,
                            'code_postal': cp,
                            'ville': city,
                            'telephone': phone,
                            'site_web': url,
                            'search_category': category,
                            'zone_recherche': zone,
                            'source': 'json-ld',
                        })
        except Exception:
            pass

    if results:
        return results

    # Parse HTML cards directly
    # Pages Jaunes uses various selectors
    cards = soup.select('div[class*="card"], li[class*="result"]')
    if not cards:
        # Try to find any block with a company name
        cards = soup.select('div.bloc-result, div.result-content')

    for card in cards:
        nom = ''
        adresse = ''
        cp = ''
        ville_card = ''
        telephone = ''
        site_web = ''

        # Name
        name_el = card.select_one('a[class*="denomination"], span[class*="denomination"], h2, h3, a.bi-denomination')
        if not name_el:
            name_el = card.select_one('[class*="name"], [class*="nom"]')
        if name_el:
            nom = name_el.get_text(strip=True)

        # Address
        addr_el = card.select_one('[class*="address"], [class*="adresse"]')
        if addr_el:
            adresse = addr_el.get_text(strip=True)

        # Extract CP/ville from address
        cp_match = re.search(r'\b(9\d{4})\b', adresse)
        if cp_match:
            cp = cp_match.group(1)

        # Phone from HTML
        phones = PHONE_RE.findall(str(card))
        for p in phones:
            p_clean = clean_phone(p)
            if not p_clean.startswith('0300'):
                telephone = p_clean
                break

        # Site web - look for pjlb encoded URLs
        for a in card.find_all('a', href=True):
            href = a['href']
            if 'pjlb' in href or 'site-web' in a.get('class', []):
                # Try data attribute
                data_pjlb = a.get('data-pjlb', '')
                if data_pjlb:
                    decoded = decode_pjlb_url(data_pjlb)
                    if decoded:
                        site_web = decoded
                        break

        if nom:
            results.append({
                'nom': nom,
                'adresse': adresse,
                'code_postal': cp,
                'ville': ville_card,
                'telephone': telephone,
                'site_web': site_web,
                'search_category': category,
                'zone_recherche': zone,
                'source': 'html',
            })

    # If still no results, try extracting phones from raw HTML with context
    if not results:
        # Look for any structured listing blocks
        # Try to extract from raw HTML with regex patterns
        raw_phones = PHONE_RE.findall(html)
        filtered = []
        for p in raw_phones:
            p_clean = clean_phone(p)
            if not p_clean.startswith('0300') and p_clean not in filtered:
                filtered.append(p_clean)

        # Try to find business names around phone numbers
        blocks = re.findall(
            r'(?:denomination|nom-enseigne)[^>]*>([^<]+)<',
            html, re.IGNORECASE
        )
        if blocks and filtered:
            for i, (name, phone) in enumerate(zip(blocks, filtered)):
                results.append({
                    'nom': name.strip(),
                    'adresse': '',
                    'code_postal': '',
                    'ville': '',
                    'telephone': phone,
                    'site_web': '',
                    'search_category': category,
                    'zone_recherche': zone,
                    'source': 'regex',
                })

    return results


def has_next_page(html):
    soup = BeautifulSoup(html, 'lxml')
    # Check for "page suivante" link or pagination
    next_link = soup.select_one('a[class*="next"], a[rel="next"], [class*="pagination"] a[aria-label*="suivant"]')
    if next_link:
        return True
    # Check if there are results at all
    no_result = soup.select_one('[class*="no-result"], [class*="aucun"]')
    if no_result:
        return False
    return False


def scrape_combination(session, city_label, city_query, category):
    results = []
    print(f"  [{city_label}] {category}", end="", flush=True)

    for page in range(1, 31):
        url = f"https://www.pagesjaunes.fr/annuaire/chercherlespros?quoiqui={category}&ou={city_query}&page={page}"

        try:
            resp = session.get(url, headers=HEADERS, timeout=30, impersonate=IMPERSONATE)
            html = resp.text
        except Exception as e:
            print(f" [ERROR: {e}]", end="", flush=True)
            break

        if resp.status_code == 404 or resp.status_code == 403:
            print(f" [HTTP {resp.status_code}]", end="", flush=True)
            break

        page_results = extract_listings(html, category, f"{city_label} 91")

        if not page_results:
            # No more results
            if page == 1:
                print(f" [0]", end="", flush=True)
            break

        results.extend(page_results)
        print(f" p{page}({len(page_results)})", end="", flush=True)

        # Check if there's a next page
        if not has_next_page(html):
            break

        time.sleep(2)

    print(f" => total: {len(results)}")
    return results


def deduplicate(results):
    seen = set()
    deduped = []
    for r in results:
        key = (r.get('nom', '').lower().strip(), r.get('telephone', '').strip(), r.get('adresse', '').lower().strip()[:30])
        if key not in seen and any(key):
            seen.add(key)
            deduped.append(r)
    return deduped


def main():
    print("=== Scraper Pages Jaunes - Banlieue d'Évry ===")
    print(f"Villes: {[c[0] for c in CITIES]}")
    print(f"Catégories: {CATEGORIES}")
    print()

    session = curl_requests.Session()
    all_results = []
    summary = {}

    for city_label, city_query in CITIES:
        print(f"\n--- {city_label} ---")
        city_results = []
        summary[city_label] = {}

        for category in CATEGORIES:
            combo_results = scrape_combination(session, city_label, city_query, category)
            city_results.extend(combo_results)
            summary[city_label][category] = len(combo_results)
            time.sleep(1)

        all_results.extend(city_results)
        print(f"  Sous-total {city_label}: {len(city_results)} entrées")
        time.sleep(3)

    # Deduplicate
    print(f"\nTotal brut: {len(all_results)}")
    all_results = deduplicate(all_results)
    print(f"Total après déduplication: {len(all_results)}")

    # Save output
    output = {
        "metadata": {
            "source": "Pages Jaunes",
            "date": "2026-03-27",
            "zone": "Banlieue d'Évry (91)",
            "total": len(all_results),
        },
        "summary": summary,
        "results": all_results,
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nFichier sauvegardé: {OUTPUT_FILE}")

    # Print summary table
    print("\n=== RÉSUMÉ ===")
    print(f"{'Ville':<25} {'Cat.':<30} {'Résultats':>10}")
    print("-" * 70)
    for city, cats in summary.items():
        for cat, count in cats.items():
            print(f"{city:<25} {cat:<30} {count:>10}")
        city_total = sum(cats.values())
        print(f"{'':25} {'TOTAL ' + city:<30} {city_total:>10}")
        print()

    grand_total = sum(sum(cats.values()) for cats in summary.values())
    print(f"\nTotal général: {grand_total} entrées (après dédup: {len(all_results)})")


if __name__ == "__main__":
    main()
