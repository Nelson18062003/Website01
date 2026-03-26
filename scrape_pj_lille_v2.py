#!/usr/bin/env python3
"""
Scrape Pages Jaunes by category for Lille area businesses,
then match results with split_lille.json entries.
"""

import json
import time
import re
import sys
import os
import base64
from urllib.parse import quote, unquote
from difflib import SequenceMatcher

try:
    from curl_cffi import requests as cffi_requests
    from bs4 import BeautifulSoup
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'curl_cffi', 'beautifulsoup4', 'lxml'])
    from curl_cffi import requests as cffi_requests
    from bs4 import BeautifulSoup

HEADERS = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7',
    'Referer': 'https://www.pagesjaunes.fr/',
}

BASE_URL = "https://www.pagesjaunes.fr"

SEARCHES = [
    ("garage automobile", "garage+automobile", "lille+33"),
    ("concession automobile", "concession+automobile", "lille+33"),
    ("carrosserie automobile", "carrosserie+automobile", "lille+33"),
    ("concession moto", "concession+moto", "lille+33"),
    ("garage moto", "garage+moto", "lille+33"),
]

PJ_CACHE_FILE = "/home/user/Website01/pj_cache_lille.json"
OUTPUT_FILE = "/home/user/Website01/pj_results_lille.json"
ENRICHED_FILE = "/home/user/Website01/enriched_lille_pj.json"
SOURCE_FILE = "/home/user/Website01/split_lille.json"


def load_cache():
    if os.path.exists(PJ_CACHE_FILE):
        with open(PJ_CACHE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_cache(cache):
    with open(PJ_CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def decode_pjlb_url(data_pjlb_str):
    """Decode base64-encoded URL from data-pjlb attribute."""
    try:
        data = json.loads(data_pjlb_str)
        url_b64 = data.get('url', '')
        if url_b64:
            # Fix base64 padding
            padding = 4 - len(url_b64) % 4
            if padding != 4:
                url_b64 += '=' * padding
            decoded = base64.b64decode(url_b64).decode('utf-8', errors='ignore')
            return decoded
    except Exception:
        pass
    return ''


def extract_listings(soup):
    """Extract business listings from a PagesJaunes results page."""
    listings = []
    blocks = soup.select('li.bi')

    for block in blocks:
        entry = {}

        # Name - the .bi-denomination is usually an <a> tag
        denom = block.select_one('.bi-denomination')
        if denom:
            entry['nom_pj'] = denom.get_text(strip=True)
            # Extract detail URL from data-pjlb
            pjlb = denom.get('data-pjlb', '')
            if pjlb:
                detail_path = decode_pjlb_url(pjlb)
                if detail_path and detail_path.startswith('/'):
                    entry['url_pj'] = BASE_URL + detail_path

        if not entry.get('nom_pj'):
            continue

        # Address
        addr_link = block.select_one('a.bi-address, [class*="bi-address"]')
        if not addr_link:
            # Try broader
            addr_link = block.select_one('.bi-adresse a, .address')

        if addr_link:
            addr_text = addr_link.get_text(' ', strip=True)
            # Remove "Voir le plan" and "Site web" etc.
            addr_text = re.sub(r'Voir le plan.*', '', addr_text).strip()
            addr_text = re.sub(r'Site web.*', '', addr_text).strip()
            entry['adresse_pj'] = addr_text

            # Try to split postal code and city
            m = re.search(r'(\d{5})\s+(.+)$', addr_text)
            if m:
                entry['code_postal_pj'] = m.group(1)
                entry['ville_pj'] = m.group(2).strip()

        # Phone - extract from raw HTML of the listing
        html_str = str(block)
        phones = re.findall(r'0[1-9][\s.]?\d{2}[\s.]?\d{2}[\s.]?\d{2}[\s.]?\d{2}', html_str)
        # Filter out 03 00 00 05 11 type numbers (PJ tracking)
        valid_phones = []
        for p in phones:
            clean = p.replace(' ', '').replace('.', '')
            if not clean.startswith('0300') and len(clean) == 10:
                valid_phones.append(p)
        if valid_phones:
            entry['telephone'] = valid_phones[0]

        # Website - look for .bi-website link with data-pjlb containing base64 URL
        web_el = block.select_one('a.bi-website')
        if web_el:
            pjlb = web_el.get('data-pjlb', '')
            if pjlb:
                url = decode_pjlb_url(pjlb)
                if url and url.startswith('http'):
                    entry['site_web'] = url

        # Also check for devis/external links that might contain the website
        if not entry.get('site_web'):
            for a_tag in block.select('a.btn_external_link, a[data-pjlb]'):
                pjlb = a_tag.get('data-pjlb', '')
                if pjlb:
                    url = decode_pjlb_url(pjlb)
                    if url and url.startswith('http') and 'pagesjaunes' not in url:
                        entry['site_web'] = url
                        break

        listings.append(entry)

    return listings


def get_total_pages(soup):
    """Determine the total number of result pages."""
    pag = soup.select_one('.pagination-compteur')
    if pag:
        text = pag.get_text()
        m = re.search(r'/\s*(\d+)', text)
        if m:
            return int(m.group(1))
    return 1


def scrape_category(cat_name, cat_query, location, session, cache):
    """Scrape all pages for a given category."""
    cache_key = f"cat_{cat_name}"
    if cache_key in cache and len(cache[cache_key]) > 0:
        print(f"  [CACHE] {cat_name}: {len(cache[cache_key])} results already cached")
        return cache[cache_key]

    all_listings = []
    max_pages = 50  # safety limit

    page = 1
    while page <= max_pages:
        url = f"{BASE_URL}/annuaire/chercherlespros?quoiqui={cat_query}&ou={location}"
        if page > 1:
            url += f"&page={page}"

        print(f"  Page {page}: {url}")

        try:
            resp = session.get(url, headers=HEADERS, timeout=30)
            if resp.status_code == 403:
                print(f"    HTTP 403 - blocked, waiting 10s and retrying...")
                time.sleep(10)
                resp = session.get(url, headers=HEADERS, timeout=30)
            if resp.status_code != 200:
                print(f"    HTTP {resp.status_code}, stopping")
                break
        except Exception as e:
            print(f"    Error: {e}")
            break

        soup = BeautifulSoup(resp.text, 'lxml')

        if page == 1:
            total = get_total_pages(soup)
            max_pages = min(total, 50)
            print(f"    Total pages: {total} (fetching up to {max_pages})")

        listings = extract_listings(soup)
        print(f"    Found {len(listings)} listings")

        if not listings:
            if page == 1:
                # Save debug HTML
                debug_file = f"/home/user/Website01/debug_pj_{cat_name.replace(' ', '_')}.html"
                with open(debug_file, 'w', encoding='utf-8') as f:
                    f.write(resp.text)
                print(f"    No listings on page 1 - saved debug HTML to {debug_file}")
            break

        all_listings.extend(listings)

        # Save progress after each page
        cache[cache_key] = all_listings
        save_cache(cache)

        page += 1
        # Respectful delay 1.5-2.5s
        delay = 1.5 + (page % 3) * 0.5
        time.sleep(delay)

    cache[cache_key] = all_listings
    save_cache(cache)
    print(f"  => Total for '{cat_name}': {len(all_listings)} listings")
    return all_listings


def normalize_name(name):
    """Normalize a business name for matching."""
    if not name:
        return ""
    name = name.upper()
    name = re.sub(r'\b(SARL|SAS|SA|EURL|SCI|SASU|SNC|ETS|ETABLISSEMENTS?)\b', '', name)
    name = re.sub(r'\([^)]*\)', '', name)
    name = re.sub(r'[^A-Z0-9\s]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def normalize_address(addr):
    """Normalize an address for matching."""
    if not addr:
        return ""
    addr = addr.upper()
    # Standardize common abbreviations
    addr = re.sub(r'\bAV\b\.?', 'AVENUE', addr)
    addr = re.sub(r'\bBD\b\.?', 'BOULEVARD', addr)
    addr = re.sub(r'\bPL\b\.?', 'PLACE', addr)
    addr = re.sub(r'\bALL\b\.?', 'ALLEE', addr)
    addr = re.sub(r'[^A-Z0-9\s]', ' ', addr)
    addr = re.sub(r'\s+', ' ', addr).strip()
    return addr


def fuzzy_match(s1, s2):
    return SequenceMatcher(None, s1, s2).ratio()


def extract_postal_and_city(ville_pj):
    if not ville_pj:
        return '', ''
    match = re.match(r'(\d{5})\s+(.*)', ville_pj.strip())
    if match:
        return match.group(1), match.group(2).upper()
    return '', ville_pj.upper()


def match_listings(source_data, pj_listings):
    """Match PJ listings to source entries using fuzzy matching.

    Uses a two-pass approach:
    1. High-confidence matches (name score > 0.7 or exact containment + same city)
    2. Medium-confidence matches (combined score >= 0.6 with location verification)
    """
    matched_count = 0

    # Pre-compute normalized PJ data
    pj_normalized = []
    for pj in pj_listings:
        pj_normalized.append({
            'orig': pj,
            'name': normalize_name(pj.get('nom_pj', '')),
            'addr': normalize_address(pj.get('adresse_pj', '')),
            'cp': pj.get('code_postal_pj', ''),
            'ville': pj.get('ville_pj', '').upper(),
        })

    for entry in source_data:
        src_name = normalize_name(entry.get('nom', ''))
        src_addr = normalize_address(entry.get('adresse', ''))
        src_cp = entry.get('code_postal', '')
        src_ville = entry.get('ville', '').upper()

        best_match = None
        best_score = 0
        best_name_score = 0

        for pjn in pj_normalized:
            pj_name = pjn['name']
            pj_addr = pjn['addr']
            pj_cp = pjn['cp']
            pj_ville = pjn['ville']

            # Name similarity
            name_score = fuzzy_match(src_name, pj_name)

            # Containment bonus - only meaningful words
            contains_bonus = 0
            if src_name and pj_name:
                if src_name in pj_name or pj_name in src_name:
                    # Only if the contained string is meaningful (> 4 chars)
                    if len(min(src_name, pj_name, key=len)) > 4:
                        contains_bonus = 0.3
                # Check significant word overlap
                src_words = set(w for w in src_name.split() if len(w) > 3)
                pj_words = set(w for w in pj_name.split() if len(w) > 3)
                if src_words and pj_words:
                    common = src_words & pj_words
                    overlap = len(common) / max(len(src_words), len(pj_words))
                    if overlap > 0.5:
                        contains_bonus = max(contains_bonus, overlap * 0.25)

            # Address similarity
            addr_score = 0
            if src_addr and pj_addr:
                addr_score = fuzzy_match(src_addr, pj_addr)

            # Location match - postal code is strongest signal
            location_bonus = 0
            location_match = False
            if src_cp and pj_cp:
                if src_cp == pj_cp:
                    location_bonus = 0.15
                    location_match = True
                elif src_cp[:2] == pj_cp[:2]:
                    # Same department
                    location_bonus = 0.05
                    location_match = True
            elif src_ville and pj_ville:
                if src_ville == pj_ville or src_ville in pj_ville or pj_ville in src_ville:
                    location_bonus = 0.1
                    location_match = True

            # Combined score
            score = name_score * 0.6 + contains_bonus + addr_score * 0.25 + location_bonus

            if score > best_score:
                best_score = score
                best_name_score = name_score
                best_match = pjn['orig']

        # Threshold: 0.65 combined score to avoid false positives
        # High name similarity (>0.8) can accept at 0.6
        accept = False
        if best_score >= 0.65 and best_match:
            accept = True
        elif best_score >= 0.6 and best_name_score >= 0.8:
            accept = True

        if accept:
            matched_count += 1
            entry['telephone'] = best_match.get('telephone', '')
            entry['site_web'] = best_match.get('site_web', '')
            entry['nom_pj'] = best_match.get('nom_pj', '')
            entry['adresse_pj'] = best_match.get('adresse_pj', '')
            entry['ville_pj'] = best_match.get('ville_pj', '')
            entry['code_postal_pj'] = best_match.get('code_postal_pj', '')
            entry['url_pj'] = best_match.get('url_pj', '')
            entry['match_score'] = round(best_score, 3)
            entry['enrichi'] = True
        else:
            entry['enrichi'] = False

    return source_data, matched_count


def main():
    print("=" * 60)
    print("Pages Jaunes Scraper - Lille Auto Businesses")
    print("=" * 60)

    session = cffi_requests.Session(impersonate="chrome")
    cache = load_cache()

    all_pj_listings = []

    for cat_name, cat_query, location in SEARCHES:
        print(f"\n{'=' * 40}")
        print(f"Category: {cat_name}")
        print(f"{'=' * 40}")
        listings = scrape_category(cat_name, cat_query, location, session, cache)

        for l in listings:
            l['search_category'] = cat_name

        all_pj_listings.extend(listings)

        # Save intermediate results
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(all_pj_listings, f, ensure_ascii=False, indent=2)
        print(f"  Saved {len(all_pj_listings)} total PJ listings")

        time.sleep(2)

    # Deduplicate by normalized name
    seen = {}
    unique_listings = []
    for l in all_pj_listings:
        key = normalize_name(l.get('nom_pj', ''))
        if key and key not in seen:
            seen[key] = l
            unique_listings.append(l)
        elif key and key in seen:
            existing = seen[key]
            for field in ['telephone', 'site_web', 'adresse_pj', 'ville_pj', 'url_pj', 'code_postal_pj']:
                if not existing.get(field) and l.get(field):
                    existing[field] = l[field]

    print(f"\n{'=' * 60}")
    print(f"Total PJ listings: {len(all_pj_listings)}")
    print(f"Unique PJ listings: {len(unique_listings)}")

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(unique_listings, f, ensure_ascii=False, indent=2)

    # Stats on PJ data quality
    with_phone = sum(1 for l in unique_listings if l.get('telephone'))
    with_web = sum(1 for l in unique_listings if l.get('site_web'))
    with_addr = sum(1 for l in unique_listings if l.get('adresse_pj'))
    print(f"PJ data quality: {with_phone} with phone, {with_web} with website, {with_addr} with address")

    # Load source and match
    print(f"\nLoading source data from {SOURCE_FILE}...")
    with open(SOURCE_FILE, 'r', encoding='utf-8') as f:
        source_data = json.load(f)
    print(f"Source entries: {len(source_data)}")

    print("Matching PJ listings to source entries...")
    enriched, matched = match_listings(source_data, unique_listings)

    with_phone_enriched = sum(1 for e in enriched if e.get('telephone'))
    with_web_enriched = sum(1 for e in enriched if e.get('site_web'))

    print(f"\n{'=' * 60}")
    print(f"ENRICHMENT RESULTS")
    print(f"{'=' * 60}")
    print(f"Total source entries: {len(enriched)}")
    print(f"Matched with PJ: {matched}")
    print(f"With phone: {with_phone_enriched}")
    print(f"With website: {with_web_enriched}")

    with open(ENRICHED_FILE, 'w', encoding='utf-8') as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)
    print(f"\nSaved enriched data to {ENRICHED_FILE}")


if __name__ == '__main__':
    main()
