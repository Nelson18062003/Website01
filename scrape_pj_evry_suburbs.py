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
}

# Rotate between known-working impersonation targets
IMPERSONATE_POOL = [
    "safari17_2_ios",
    "chrome131",
    "firefox133",
    "edge99",
    "chrome110",
    "safari15_5",
    "chrome107",
    "edge101",
]
_imp_idx = 0

def next_impersonate():
    global _imp_idx
    val = IMPERSONATE_POOL[_imp_idx % len(IMPERSONATE_POOL)]
    _imp_idx += 1
    return val

PHONE_RE = re.compile(r'0[1-9][\s.]?\d{2}[\s.]?\d{2}[\s.]?\d{2}[\s.]?\d{2}')
PHONE_10_RE = re.compile(r'0[1-9]\d{8}')


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


def fetch_with_retry(session, url, max_retries=10, base_delay=1):
    """Fetch URL with retry on 403 (Cloudflare intermittent challenge)."""
    headers = dict(HEADERS)
    for attempt in range(max_retries):
        imp = next_impersonate()
        try:
            resp = session.get(url, headers=headers, timeout=30, impersonate=imp)
            if resp.status_code == 200:
                return resp
            if resp.status_code == 404:
                return None
            # 403: short delay then retry with next impersonate
            time.sleep(base_delay + (attempt % 3))
        except Exception as e:
            time.sleep(base_delay)
    return None


def extract_phone_from_img(img_src):
    """Extract phone number embedded in PJ image filename."""
    if not img_src:
        return ''
    # The folder name (second-to-last path segment) contains the phone
    parts = img_src.split('/')
    if len(parts) >= 2:
        folder = parts[-2]
        m = PHONE_10_RE.search(folder)
        if m:
            phone = m.group()
            if not phone.startswith('0300'):
                return phone
    return ''


def get_next_page_info(soup):
    """Extract AJAX URL for next page from pagination element."""
    pag = soup.select_one('.pagination-inf[data-pjajax]')
    if pag:
        try:
            data = json.loads(pag.get('data-pjajax', '{}'))
            return data.get('url', '')
        except Exception:
            pass
    return ''


def extract_listings(html, category, zone):
    soup = BeautifulSoup(html, 'lxml')
    results = []

    cards = soup.select('li.bi-generic, li.bi-pro')

    for card in cards:
        # Name
        nom = ''
        h = card.select_one('h3, h2, .bi-denomination')
        if h:
            nom = h.get_text(strip=True)

        if not nom:
            continue

        # Address extraction
        addr_el = card.select_one('.bi-address')
        adresse_full = ''
        cp = ''
        ville_card = ''
        adresse = ''
        if addr_el:
            # Strategy 1: get text from the link (full address is often inside <a>)
            addr_link = addr_el.select_one('a')
            if addr_link:
                raw_text = addr_link.get_text(separator=' ', strip=True)
                # Remove "Voir le plan" suffix
                raw_text = re.sub(r'\s*Voir le plan\s*$', '', raw_text, flags=re.IGNORECASE).strip()
                adresse_full = re.sub(r'\s+', ' ', raw_text).strip()
            else:
                # Strategy 2: direct text nodes + matched span
                direct_text = ' '.join(
                    t.strip() for t in addr_el.find_all(string=True, recursive=False)
                    if t.strip()
                )
                matched_span = addr_el.select_one('.matched')
                if matched_span:
                    direct_text = direct_text + ' ' + matched_span.get_text(strip=True)
                adresse_full = re.sub(r'\s+', ' ', direct_text).strip()

            # Extract postal code
            cp_match = re.search(r'\b(\d{5})\b', adresse_full)
            if cp_match:
                cp = cp_match.group(1)
                after_cp = adresse_full[cp_match.end():].strip()
                if after_cp:
                    ville_card = after_cp
                adresse = adresse_full[:cp_match.start()].strip()
            else:
                adresse = adresse_full

        # Phone: try from img src filename first
        telephone = ''
        img = card.select_one('img')
        if img:
            telephone = extract_phone_from_img(img.get('src', ''))

        # Fallback: regex on raw card HTML (excluding image paths)
        if not telephone:
            # Search in text content only (not img src)
            card_text = card.get_text()
            phones_found = PHONE_RE.findall(card_text)
            for p in phones_found:
                p_clean = clean_phone(p)
                if not p_clean.startswith('0300'):
                    telephone = p_clean
                    break

        # Site web via pjlb decoding
        site_web = ''
        url_pj = ''
        for a in card.find_all('a', attrs={'data-pjlb': True}):
            label = a.get_text(strip=True).lower()
            classes = ' '.join(a.get('class', []))
            data_pjlb = a.get('data-pjlb', '')
            if any(kw in label for kw in ['site web', 'website', 'visiter', 'voir le site']):
                decoded = decode_pjlb_url(data_pjlb)
                if decoded and decoded.startswith('http'):
                    site_web = decoded
                    break

        # PJ URL from main link
        main_link = card.select_one('a.bi-link-mobile, a[href^="/pros/"]')
        if main_link:
            href = main_link.get('href', '')
            if href.startswith('/pros/'):
                url_pj = 'https://www.pagesjaunes.fr' + href

        results.append({
            'nom': nom,
            'adresse': adresse,
            'code_postal': cp,
            'ville': ville_card,
            'telephone': telephone,
            'site_web': site_web,
            'url_pj': url_pj,
            'search_category': category,
            'zone_recherche': zone,
        })

    return results, get_next_page_info(soup)


def scrape_combination(session, city_label, city_query, category):
    results = []
    print(f"  [{city_label}] {category}", end="", flush=True)

    base_url = f"https://www.pagesjaunes.fr/annuaire/chercherlespros?quoiqui={category}&ou={city_query}"

    page = 1
    next_ajax_url = None

    while page <= 30:
        if page == 1:
            url = base_url + "&page=1"
        else:
            if next_ajax_url:
                # For pages 2+, use the direct page URL (same pattern)
                url = base_url + f"&page={page}"
            else:
                break

        resp = fetch_with_retry(session, url)

        if resp is None:
            print(f" [FAIL p{page}]", end="", flush=True)
            break

        page_results, next_url = extract_listings(resp.text, category, f"{city_label} 91")

        if not page_results:
            if page == 1:
                print(f" [0]", end="", flush=True)
            break

        results.extend(page_results)
        print(f" p{page}({len(page_results)})", end="", flush=True)

        # Check for next page
        if next_url:
            next_ajax_url = next_url
            page += 1
            time.sleep(2)
        else:
            break

    print(f" => {len(results)}")
    return results


def deduplicate(results):
    seen = set()
    deduped = []
    for r in results:
        key = (
            r.get('nom', '').lower().strip(),
            r.get('telephone', '').strip(),
            r.get('adresse', '').lower().strip()[:30]
        )
        if key[0] and key not in seen:
            seen.add(key)
            deduped.append(r)
    return deduped


def main():
    print("=== Scraper Pages Jaunes - Banlieue d'Évry ===")
    print(f"Impersonate pool: {IMPERSONATE_POOL}")
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
        city_total = sum(summary[city_label].values())
        print(f"  Sous-total {city_label}: {city_total} entrées brutes")
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
            "categories": CATEGORIES,
            "villes": [c[0] for c in CITIES],
            "total": len(all_results),
        },
        "summary": summary,
        "results": all_results,
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nFichier sauvegardé: {OUTPUT_FILE}")

    # Print summary table
    print("\n=== RÉSUMÉ PAR VILLE ET CATÉGORIE ===")
    print(f"{'Ville':<25} {'Catégorie':<30} {'N':>6}")
    print("-" * 65)
    grand_total_raw = 0
    for city, cats in summary.items():
        for cat, count in cats.items():
            print(f"{city:<25} {cat:<30} {count:>6}")
            grand_total_raw += count
        city_total = sum(cats.values())
        print(f"{'':25} {'== TOTAL ==':30} {city_total:>6}")
        print()

    print(f"\nTotal général (brut): {grand_total_raw}")
    print(f"Total (dédupliqué):   {len(all_results)}")


if __name__ == "__main__":
    main()
