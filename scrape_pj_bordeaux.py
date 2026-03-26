#!/usr/bin/env python3
"""
Scrape Pages Jaunes by category for Bordeaux area businesses,
then match results with split_bordeaux.json entries.
"""

import json
import time
import re
import sys
import os
from urllib.parse import quote
from difflib import SequenceMatcher

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'requests', 'beautifulsoup4', 'lxml'])
    import requests
    from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Cache-Control': 'max-age=0',
}

BASE_URL = "https://www.pagesjaunes.fr"

SEARCHES = [
    ("garage automobile", "bordeaux-33"),
    ("concession automobile", "bordeaux-33"),
    ("carrosserie automobile", "bordeaux-33"),
    ("concession moto", "bordeaux-33"),
    ("garage moto", "bordeaux-33"),
]

OUTPUT_FILE = "/home/user/Website01/pj_results_bordeaux.json"
ENRICHED_FILE = "/home/user/Website01/enriched_bordeaux_pj.json"
SOURCE_FILE = "/home/user/Website01/split_bordeaux.json"


def extract_listings(soup):
    """Extract business listings from a PagesJaunes results page."""
    listings = []

    # Try multiple selectors for listing blocks
    blocks = soup.select('li.bi-generic, li.bi, div.bi-generic, div.bi, li[id^="bi-"]')
    if not blocks:
        blocks = soup.select('[class*="bi-"]')

    for block in blocks:
        entry = {}

        # Name
        name_el = block.select_one('.bi-denomination, .denomination-links a, h3 a, .bi-header-title a, a.bi-denomination, .pj-link')
        if name_el:
            entry['nom_pj'] = name_el.get_text(strip=True)
        else:
            # Try broader search
            name_el = block.select_one('[class*="denom"] a, [class*="name"]')
            if name_el:
                entry['nom_pj'] = name_el.get_text(strip=True)

        if not entry.get('nom_pj'):
            continue

        # Address
        addr_el = block.select_one('.bi-address-street, .bi-adresse .bi-address-street, .address-street, [class*="address"]')
        if addr_el:
            entry['adresse_pj'] = addr_el.get_text(strip=True)

        city_el = block.select_one('.bi-address-city, .bi-adresse .bi-address-city, .address-city, [class*="city"]')
        if city_el:
            entry['ville_pj'] = city_el.get_text(strip=True)

        # Phone
        phone_el = block.select_one('.bi-phone-number, .click_phone_number, [class*="phone"] span, .number-phone')
        if phone_el:
            phone = phone_el.get_text(strip=True)
            phone = re.sub(r'[^\d\s+]', '', phone).strip()
            if phone:
                entry['telephone'] = phone

        # Also try data attribute for phone
        if not entry.get('telephone'):
            phone_link = block.select_one('a[data-phone], a[href^="tel:"]')
            if phone_link:
                phone = phone_link.get('data-phone', '') or phone_link.get('href', '').replace('tel:', '')
                phone = re.sub(r'[^\d\s+]', '', phone).strip()
                if phone:
                    entry['telephone'] = phone

        # Website
        web_el = block.select_one('a.bi-website, a[class*="website"], a[data-pjlabel="site_internet"]')
        if web_el:
            url = web_el.get('href', '')
            if url and 'pagesjaunes' not in url:
                entry['site_web'] = url

        # Detail page URL (to get more info later if needed)
        detail_el = block.select_one('a.bi-denomination, .denomination-links a, h3 a, a.bi-header-title')
        if detail_el:
            href = detail_el.get('href', '')
            if href:
                if href.startswith('/'):
                    entry['url_pj'] = BASE_URL + href
                elif href.startswith('http'):
                    entry['url_pj'] = href

        listings.append(entry)

    return listings


def get_total_pages(soup):
    """Determine the total number of result pages."""
    # Look for pagination
    pagination = soup.select('.pagination-compteur, .pagination span, [class*="pagination"]')
    for p in pagination:
        text = p.get_text()
        match = re.search(r'(\d+)\s*/\s*(\d+)', text)
        if match:
            return int(match.group(2))
        match = re.search(r'sur\s+(\d+)', text)
        if match:
            return int(match.group(1))

    # Check for page links
    page_links = soup.select('a[class*="pagination"], .pagination a')
    max_page = 1
    for link in page_links:
        text = link.get_text(strip=True)
        if text.isdigit():
            max_page = max(max_page, int(text))
        href = link.get('href', '')
        match = re.search(r'page-(\d+)', href)
        if match:
            max_page = max(max_page, int(match.group(1)))

    return max_page


def scrape_category(search_term, location, session):
    """Scrape all pages for a given search term and location."""
    all_listings = []
    encoded_term = quote(search_term)

    page = 1
    max_pages = 20  # Safety limit

    while page <= max_pages:
        if page == 1:
            url = f"{BASE_URL}/recherche/{location}/{encoded_term}"
        else:
            url = f"{BASE_URL}/recherche/{location}/{encoded_term}/{page}"

        print(f"  Fetching page {page}: {url}")

        try:
            resp = session.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
        except Exception as e:
            print(f"  Error fetching {url}: {e}")
            break

        soup = BeautifulSoup(resp.text, 'lxml')

        # On first page, determine total pages
        if page == 1:
            total = get_total_pages(soup)
            max_pages = min(total, 20)
            print(f"  Total pages detected: {total}, will fetch up to {max_pages}")

        listings = extract_listings(soup)
        print(f"  Found {len(listings)} listings on page {page}")

        if not listings and page > 1:
            print(f"  No listings found, stopping pagination")
            break

        all_listings.extend(listings)

        # Check if there's a next page link
        next_link = soup.select_one('a[id="pagination-next"], a.next, a[class*="next"]')
        if not next_link and page > 1:
            # No next button found, check if we got fewer results
            pass

        page += 1

        # Respectful delay
        time.sleep(1.5)

    return all_listings


def normalize_name(name):
    """Normalize a business name for matching."""
    if not name:
        return ""
    name = name.upper()
    # Remove common suffixes/prefixes
    name = re.sub(r'\b(SARL|SAS|SA|EURL|SCI|SASU|ETS|ETABLISSEMENTS?)\b', '', name)
    # Remove parenthetical content
    name = re.sub(r'\([^)]*\)', '', name)
    # Remove special chars
    name = re.sub(r'[^A-Z0-9\s]', ' ', name)
    # Collapse whitespace
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def normalize_address(addr):
    """Normalize an address for matching."""
    if not addr:
        return ""
    addr = addr.upper()
    addr = re.sub(r'[^A-Z0-9\s]', ' ', addr)
    addr = re.sub(r'\s+', ' ', addr).strip()
    return addr


def extract_postal_and_city(ville_pj):
    """Extract postal code and city from PJ city field like '33000 Bordeaux'."""
    if not ville_pj:
        return '', ''
    match = re.match(r'(\d{5})\s+(.*)', ville_pj.strip())
    if match:
        return match.group(1), match.group(2).upper()
    return '', ville_pj.upper()


def fuzzy_match(s1, s2):
    """Return similarity ratio between two strings."""
    return SequenceMatcher(None, s1, s2).ratio()


def match_listings(source_data, pj_listings):
    """Match PJ listings to source entries."""
    # Build index of PJ listings by normalized name
    pj_by_name = {}
    for pj in pj_listings:
        norm = normalize_name(pj.get('nom_pj', ''))
        if norm:
            pj_by_name.setdefault(norm, []).append(pj)

    matched_count = 0

    for entry in source_data:
        src_name = normalize_name(entry.get('nom', ''))
        src_addr = normalize_address(entry.get('adresse', ''))
        src_cp = entry.get('code_postal', '')
        src_ville = entry.get('ville', '').upper()

        best_match = None
        best_score = 0

        for pj in pj_listings:
            pj_name = normalize_name(pj.get('nom_pj', ''))
            pj_addr = normalize_address(pj.get('adresse_pj', ''))
            pj_cp, pj_ville = extract_postal_and_city(pj.get('ville_pj', ''))

            # Name similarity
            name_score = fuzzy_match(src_name, pj_name)

            # Check if one name contains the other
            contains_bonus = 0
            if src_name and pj_name:
                if src_name in pj_name or pj_name in src_name:
                    contains_bonus = 0.3

            # Address similarity
            addr_score = 0
            if src_addr and pj_addr:
                addr_score = fuzzy_match(src_addr, pj_addr)

            # City/postal match bonus
            location_bonus = 0
            if src_cp and pj_cp and src_cp == pj_cp:
                location_bonus = 0.15
            elif src_ville and pj_ville and (src_ville in pj_ville or pj_ville in src_ville):
                location_bonus = 0.1

            # Combined score
            score = name_score * 0.6 + contains_bonus + addr_score * 0.25 + location_bonus

            if score > best_score:
                best_score = score
                best_match = pj

        # Threshold for accepting a match
        if best_score >= 0.55 and best_match:
            matched_count += 1
            entry['telephone'] = best_match.get('telephone', '')
            entry['site_web'] = best_match.get('site_web', '')
            entry['email'] = best_match.get('email', '')
            entry['nom_pj'] = best_match.get('nom_pj', '')
            entry['adresse_pj'] = best_match.get('adresse_pj', '')
            entry['ville_pj'] = best_match.get('ville_pj', '')
            entry['url_pj'] = best_match.get('url_pj', '')
            entry['match_score'] = round(best_score, 3)
            entry['enrichi'] = True
        else:
            entry['telephone'] = ''
            entry['site_web'] = ''
            entry['email'] = ''
            entry['enrichi'] = False

    return source_data, matched_count


def main():
    print("=" * 60)
    print("Pages Jaunes Scraper - Bordeaux Auto Businesses")
    print("=" * 60)

    session = requests.Session()

    all_pj_listings = []

    for search_term, location in SEARCHES:
        print(f"\n--- Searching: '{search_term}' in {location} ---")
        listings = scrape_category(search_term, location, session)
        print(f"  => Total for '{search_term}': {len(listings)} listings")

        # Tag with search category
        for l in listings:
            l['search_category'] = search_term

        all_pj_listings.extend(listings)

        # Save intermediate results
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(all_pj_listings, f, ensure_ascii=False, indent=2)
        print(f"  Saved {len(all_pj_listings)} total PJ listings to {OUTPUT_FILE}")

        time.sleep(2)  # Delay between categories

    # Deduplicate PJ listings by name
    seen = {}
    unique_listings = []
    for l in all_pj_listings:
        key = normalize_name(l.get('nom_pj', ''))
        if key and key not in seen:
            seen[key] = l
            unique_listings.append(l)
        elif key and key in seen:
            # Merge: keep entry with more data
            existing = seen[key]
            for field in ['telephone', 'site_web', 'email', 'adresse_pj', 'ville_pj', 'url_pj']:
                if not existing.get(field) and l.get(field):
                    existing[field] = l[field]

    print(f"\n{'=' * 60}")
    print(f"Total unique PJ listings: {len(unique_listings)}")

    # Save final PJ results
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(unique_listings, f, ensure_ascii=False, indent=2)

    # Load source data and match
    print(f"\nLoading source data from {SOURCE_FILE}...")
    with open(SOURCE_FILE, 'r', encoding='utf-8') as f:
        source_data = json.load(f)
    print(f"Source entries: {len(source_data)}")

    print("Matching PJ listings to source entries...")
    enriched, matched = match_listings(source_data, unique_listings)

    print(f"Matched: {matched} / {len(source_data)} entries")

    # Save enriched data
    with open(ENRICHED_FILE, 'w', encoding='utf-8') as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)
    print(f"Saved enriched data to {ENRICHED_FILE}")

    # Stats
    with_phone = sum(1 for e in enriched if e.get('telephone'))
    with_web = sum(1 for e in enriched if e.get('site_web'))
    print(f"\nStats:")
    print(f"  With phone: {with_phone}")
    print(f"  With website: {with_web}")
    print(f"  Enriched: {matched}")


if __name__ == '__main__':
    main()
