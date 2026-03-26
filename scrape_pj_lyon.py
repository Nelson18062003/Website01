#!/usr/bin/env python3
"""
Scrape PagesJaunes by category for Lyon area, then fuzzy-match
with split_lyon.json to enrich company records.
"""

import json
import re
import time
import os
import sys
from urllib.parse import quote
from difflib import SequenceMatcher

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Installing required packages...")
    os.system("pip install requests beautifulsoup4 lxml")
    import requests
    from bs4 import BeautifulSoup

# ── Config ──────────────────────────────────────────────────────────────
BASE_DIR = "/home/user/Website01"
SOURCE_FILE = os.path.join(BASE_DIR, "split_lyon.json")
OUTPUT_FILE = os.path.join(BASE_DIR, "enriched_lyon_pj.json")
PJ_CACHE_FILE = os.path.join(BASE_DIR, "pj_results_cache.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
}

CATEGORIES = [
    ("garage automobile", "garage%20automobile"),
    ("concession automobile", "concession%20automobile"),
    ("carrosserie automobile", "carrosserie%20automobile"),
    ("concession moto", "concession%20moto"),
    ("garage moto", "garage%20moto"),
]

DELAY = 2  # seconds between requests


def extract_listings_from_page(html):
    """Extract business listings from a PagesJaunes HTML page."""
    soup = BeautifulSoup(html, "lxml")
    results = []

    # PagesJaunes lists results in <li> elements with class 'bi-generic' or similar
    listings = soup.select("li.bi-generic, li.bi")
    if not listings:
        # Try alternative selectors
        listings = soup.select("[id^='bloc-liste-'] li, .bi-bloc, .bi-content-wrapper")
    if not listings:
        # Another try - each listing often has data-pjid
        listings = soup.select("[data-pjid]")
    if not listings:
        # Broader: any div/article with class containing 'bi'
        listings = soup.select("article.bi, div.bi-bloc")

    for item in listings:
        entry = {}

        # Name
        name_el = item.select_one("h3 a, .denomination-links a, .bi-denomination a, a.bi-denomination, .bi-header-title a, h2 a")
        if not name_el:
            name_el = item.select_one("h3, .bi-denomination, .denomination-links")
        if name_el:
            entry["pj_nom"] = name_el.get_text(strip=True)
        else:
            continue  # skip if no name

        # Address
        addr_el = item.select_one(".bi-address, .bi-adresse, .address, .bi-address-street")
        if addr_el:
            entry["pj_adresse"] = addr_el.get_text(" ", strip=True)
        else:
            # Try combining street + city
            street = item.select_one(".bi-address-street, .street-address")
            city = item.select_one(".bi-address-city, .locality")
            parts = []
            if street:
                parts.append(street.get_text(strip=True))
            if city:
                parts.append(city.get_text(strip=True))
            if parts:
                entry["pj_adresse"] = " ".join(parts)

        # Phone
        phone_el = item.select_one(".bi-phone-number, .click_phone_number, a[href^='tel:'], .bi-phone a, .number-phone, [data-phone]")
        if phone_el:
            phone_text = phone_el.get("href", "") or phone_el.get("data-phone", "") or phone_el.get_text(strip=True)
            phone_text = phone_text.replace("tel:", "").strip()
            if phone_text:
                entry["pj_telephone"] = phone_text

        # Also check for phone number in data attribute
        if "pj_telephone" not in entry:
            phone_data = item.select_one("[data-num]")
            if phone_data:
                entry["pj_telephone"] = phone_data.get("data-num", "")

        # Website
        web_el = item.select_one("a.bi-website, a[data-pjlabel='site_internet'], a.pj-link--website, a[title*='site'], a.bi-site-internet")
        if web_el:
            href = web_el.get("href", "")
            if href and "pagesjaunes" not in href:
                entry["pj_site_web"] = href
            else:
                entry["pj_site_web"] = web_el.get_text(strip=True)

        # Email - rarely visible on listing pages
        email_el = item.select_one("a[href^='mailto:']")
        if email_el:
            entry["pj_email"] = email_el.get("href", "").replace("mailto:", "").strip()

        if entry.get("pj_nom"):
            results.append(entry)

    return results, soup


def has_next_page(soup):
    """Check if there's a next page link."""
    next_link = soup.select_one("a.link_pagination.next, a[id='pagination-next'], a.pagination-next, li.next a, a[title='Page suivante']")
    if next_link:
        return next_link.get("href")
    # Check for pagination numbers
    pages = soup.select("a.link_pagination, .pagination a")
    return None


def get_total_pages(soup):
    """Try to determine total number of pages from pagination."""
    pages = soup.select("a.link_pagination, .pagination a, span.pagination-number")
    max_page = 1
    for p in pages:
        text = p.get_text(strip=True)
        if text.isdigit():
            max_page = max(max_page, int(text))
    return max_page


def scrape_category(session, cat_name, cat_url_part):
    """Scrape all pages for a given category in Lyon."""
    all_results = []
    base_url = f"https://www.pagesjaunes.fr/annuaire/lyon-69/{cat_url_part}"
    page = 1

    print(f"\n{'='*60}")
    print(f"Scraping category: {cat_name}")
    print(f"{'='*60}")

    while True:
        if page == 1:
            url = base_url
        else:
            url = f"{base_url}/page-{page}"

        print(f"  Page {page}: {url}")
        try:
            resp = session.get(url, headers=HEADERS, timeout=30)
            print(f"    Status: {resp.status_code}")

            if resp.status_code == 404:
                print(f"    Page not found, stopping pagination.")
                break
            if resp.status_code != 200:
                print(f"    Non-200 status, stopping.")
                break

            listings, soup = extract_listings_from_page(resp.text)
            print(f"    Found {len(listings)} listings")

            if not listings:
                # Maybe blocked or end of results
                # Save HTML for debugging first page only
                if page == 1:
                    debug_path = os.path.join(BASE_DIR, f"debug_pj_{cat_url_part.replace('%20','_')}.html")
                    with open(debug_path, "w", encoding="utf-8") as f:
                        f.write(resp.text)
                    print(f"    Saved debug HTML to {debug_path}")
                break

            all_results.extend(listings)

            # Check total pages on first page
            if page == 1:
                total = get_total_pages(soup)
                print(f"    Estimated total pages: {total}")

            # Check for next page
            next_href = has_next_page(soup)
            if next_href:
                page += 1
                time.sleep(DELAY)
            else:
                # Try incrementing page anyway up to reasonable limit
                if page < 20 and len(listings) >= 10:
                    page += 1
                    time.sleep(DELAY)
                else:
                    break

        except Exception as e:
            print(f"    Error: {e}")
            break

        time.sleep(DELAY)

    print(f"  Total for '{cat_name}': {len(all_results)} listings")
    return all_results


def normalize_name(name):
    """Normalize a company name for matching."""
    if not name:
        return ""
    name = name.upper()
    # Remove common suffixes/prefixes
    name = re.sub(r'\b(SARL|SAS|SA|EURL|SCI|SNC|AUTO|AUTOMOBILES?|GARAGE|CARROSSERIE)\b', '', name)
    # Remove parenthetical content
    name = re.sub(r'\(.*?\)', '', name)
    # Remove punctuation
    name = re.sub(r'[^A-Z0-9\s]', '', name)
    # Collapse whitespace
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def normalize_address(addr):
    """Normalize an address for matching."""
    if not addr:
        return ""
    addr = addr.upper()
    addr = re.sub(r'[^A-Z0-9\s]', '', addr)
    addr = re.sub(r'\s+', ' ', addr).strip()
    return addr


def extract_street_number_and_name(addr):
    """Extract street number and street name from address."""
    if not addr:
        return "", ""
    addr = addr.upper().strip()
    m = re.match(r'^(\d+)\s+(.+?)(?:\s+\d{5}\s+.*)?$', addr)
    if m:
        return m.group(1), m.group(2).strip()
    return "", addr


def fuzzy_match(name1, name2, threshold=0.55):
    """Return similarity ratio between two names."""
    n1 = normalize_name(name1)
    n2 = normalize_name(name2)
    if not n1 or not n2:
        return 0.0
    return SequenceMatcher(None, n1, n2).ratio()


def address_match(addr1, addr2, threshold=0.6):
    """Check if two addresses match."""
    a1 = normalize_address(addr1)
    a2 = normalize_address(addr2)
    if not a1 or not a2:
        return 0.0
    return SequenceMatcher(None, a1, a2).ratio()


def match_pj_to_source(pj_results, source_data):
    """Match PagesJaunes results to source file entries."""
    matches = {}  # source index -> best PJ match

    for pj in pj_results:
        pj_name = pj.get("pj_nom", "")
        pj_addr = pj.get("pj_adresse", "")

        best_score = 0
        best_idx = None

        for idx, src in enumerate(source_data):
            src_name = src.get("nom", "")
            src_addr = src.get("adresse", "")

            # Name similarity
            name_score = fuzzy_match(pj_name, src_name)

            # Address similarity
            addr_score = address_match(pj_addr, src_addr)

            # Combined score - name is more important
            combined = name_score * 0.65 + addr_score * 0.35

            # Bonus if both name and address are decent matches
            if name_score > 0.5 and addr_score > 0.5:
                combined += 0.1

            # Also check if PJ name contains key words from source or vice versa
            pj_words = set(normalize_name(pj_name).split())
            src_words = set(normalize_name(src_name).split())
            if pj_words and src_words:
                common = pj_words & src_words
                if len(common) >= 2:
                    combined += 0.1
                elif len(common) >= 1 and len(min(pj_words, src_words, key=len)) <= 2:
                    combined += 0.05

            if combined > best_score and combined > 0.45:
                best_score = combined
                best_idx = idx

        if best_idx is not None:
            if best_idx not in matches or matches[best_idx][1] < best_score:
                matches[best_idx] = (pj, best_score)

    return matches


def main():
    # Load source data
    print("Loading source data...")
    with open(SOURCE_FILE, "r", encoding="utf-8") as f:
        source_data = json.load(f)
    print(f"Loaded {len(source_data)} companies")

    # Check for cached PJ results
    all_pj_results = []
    if os.path.exists(PJ_CACHE_FILE):
        print("Loading cached PJ results...")
        with open(PJ_CACHE_FILE, "r", encoding="utf-8") as f:
            all_pj_results = json.load(f)
        print(f"Loaded {len(all_pj_results)} cached results")

    if not all_pj_results:
        # Scrape PagesJaunes
        session = requests.Session()

        for cat_name, cat_url in CATEGORIES:
            results = scrape_category(session, cat_name, cat_url)
            all_pj_results.extend(results)

            # Save intermediate cache
            with open(PJ_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(all_pj_results, f, ensure_ascii=False, indent=2)
            print(f"  Cached {len(all_pj_results)} total results so far")

            time.sleep(3)  # Extra delay between categories

        print(f"\nTotal PJ results scraped: {len(all_pj_results)}")

    # Deduplicate PJ results by name
    seen = set()
    unique_pj = []
    for r in all_pj_results:
        key = normalize_name(r.get("pj_nom", ""))
        if key and key not in seen:
            seen.add(key)
            unique_pj.append(r)
    print(f"Unique PJ results after dedup: {len(unique_pj)}")

    # Match and enrich
    print("\nMatching PJ results to source data...")
    matches = match_pj_to_source(unique_pj, source_data)
    print(f"Found {len(matches)} matches")

    # Enrich source data
    enriched = []
    matched_count = 0
    for idx, company in enumerate(source_data):
        entry = dict(company)
        if idx in matches:
            pj_data, score = matches[idx]
            entry["pj_telephone"] = pj_data.get("pj_telephone", "")
            entry["pj_site_web"] = pj_data.get("pj_site_web", "")
            entry["pj_email"] = pj_data.get("pj_email", "")
            entry["pj_adresse"] = pj_data.get("pj_adresse", "")
            entry["pj_nom_match"] = pj_data.get("pj_nom", "")
            entry["pj_match_score"] = round(score, 3)
            entry["pj_enriched"] = True
            matched_count += 1
        else:
            entry["pj_telephone"] = ""
            entry["pj_site_web"] = ""
            entry["pj_email"] = ""
            entry["pj_adresse_pj"] = ""
            entry["pj_nom_match"] = ""
            entry["pj_match_score"] = 0
            entry["pj_enriched"] = False
        enriched.append(entry)

    # Save enriched data
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)

    print(f"\nDone! Enriched {matched_count}/{len(source_data)} companies")
    print(f"Saved to {OUTPUT_FILE}")

    # Print some stats on matches
    if matched_count > 0:
        scores = [matches[i][1] for i in matches]
        print(f"Match scores: min={min(scores):.3f}, max={max(scores):.3f}, avg={sum(scores)/len(scores):.3f}")
        print("\nSample matches:")
        for idx in list(matches.keys())[:10]:
            pj, score = matches[idx]
            src = source_data[idx]
            print(f"  {src['nom'][:40]:40s} <-> {pj['pj_nom'][:40]:40s} (score: {score:.3f})")


if __name__ == "__main__":
    main()
