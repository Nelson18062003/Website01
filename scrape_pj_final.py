#!/usr/bin/env python3
"""
Scrape PagesJaunes by category for Lyon area using cloudscraper.
Then fuzzy-match with split_lyon.json to enrich company records.
"""

import json
import re
import time
import os
from difflib import SequenceMatcher
import cloudscraper
from bs4 import BeautifulSoup

BASE_DIR = "/home/user/Website01"
SOURCE_FILE = os.path.join(BASE_DIR, "split_lyon.json")
OUTPUT_FILE = os.path.join(BASE_DIR, "enriched_lyon_pj.json")
PJ_CACHE_FILE = os.path.join(BASE_DIR, "pj_results_cache.json")

CATEGORIES = [
    ("garage automobile", "garage-automobile"),
    ("concession automobile", "concession-automobile"),
    ("carrosserie automobile", "carrosserie-automobile"),
    ("concession moto", "concession-moto"),
    ("garage moto", "garage-moto"),
]

MAX_RETRIES = 5
DELAY_BETWEEN_REQUESTS = 2
DELAY_BETWEEN_RETRIES = 5


def create_scraper():
    """Create a fresh cloudscraper instance."""
    return cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'linux',
            'mobile': False,
            'desktop': True,
        },
        delay=3,
    )


def fetch_with_retry(scraper_holder, url, max_retries=MAX_RETRIES):
    """Fetch URL with retries, recreating scraper if needed."""
    for attempt in range(max_retries):
        try:
            resp = scraper_holder[0].get(url)
            # Check if we got actual content (not just Cloudflare page)
            if 'bi-denomination' in resp.text or 'bi-content' in resp.text:
                return resp
            if resp.status_code == 404:
                return resp
            # Check if it's a "no results" page
            if 'Aucun résultat' in resp.text or 'aucun professionnel' in resp.text.lower():
                return resp
            print(f"      Attempt {attempt+1}: Got status {resp.status_code}, no listing content (len={len(resp.text)})")
        except Exception as e:
            print(f"      Attempt {attempt+1}: Error: {e}")

        # Recreate scraper and retry
        time.sleep(DELAY_BETWEEN_RETRIES + attempt * 2)
        scraper_holder[0] = create_scraper()

    return None


def extract_listings(html):
    """Extract business listings from PagesJaunes HTML."""
    soup = BeautifulSoup(html, 'lxml')
    results = []

    listings = soup.select('li[id^="bi-"]')
    if not listings:
        return results, soup

    for li in listings:
        entry = {}

        # Name
        name_el = li.select_one('.bi-denomination a')
        if not name_el:
            name_el = li.select_one('.bi-denomination')
        if not name_el:
            continue
        entry["pj_nom"] = name_el.get_text(strip=True)

        # Address
        addr_el = li.select_one('.bi-address')
        if addr_el:
            addr_text = addr_el.get_text(' ', strip=True)
            # Remove "Voir le plan" suffix
            addr_text = re.sub(r'\s*Voir le plan\s*$', '', addr_text)
            entry["pj_adresse"] = addr_text

        # Phone numbers - in the hidden fantomas section
        bi_id = li.get('id', '').replace('bi-', '')
        fantomas = li.select_one(f'#bi-fantomas-{bi_id}, .bi-fantomas')
        if fantomas:
            phones = []
            for num_div in fantomas.select('.number-contact'):
                text = num_div.get_text(strip=True)
                # Extract phone number
                phone_match = re.search(r'(0[1-9][\s.]\d{2}[\s.]\d{2}[\s.]\d{2}[\s.]\d{2})', text)
                if phone_match:
                    phones.append(phone_match.group(1).replace(' ', '').replace('.', ''))
            if phones:
                entry["pj_telephone"] = phones[0]
                if len(phones) > 1:
                    entry["pj_telephone2"] = phones[1]

        # Also check for phone outside fantomas
        if "pj_telephone" not in entry:
            phone_matches = re.findall(
                r'(0[1-9][\s.]\d{2}[\s.]\d{2}[\s.]\d{2}[\s.]\d{2})',
                str(li)
            )
            if phone_matches:
                entry["pj_telephone"] = phone_matches[0].replace(' ', '').replace('.', '')

        # Website
        web_el = li.select_one('a.pj-link--website, a[data-pjlabel*="site_internet"]')
        if web_el:
            href = web_el.get('href', '')
            if href and 'pagesjaunes.fr' not in href:
                entry["pj_site_web"] = href

        # Also check fantomas for website
        if "pj_site_web" not in entry and fantomas:
            web_el2 = fantomas.select_one('a[href^="http"]')
            if web_el2:
                href = web_el2.get('href', '')
                if 'pagesjaunes' not in href:
                    entry["pj_site_web"] = href

        # Email
        email_el = li.select_one('a[href^="mailto:"]')
        if email_el:
            entry["pj_email"] = email_el.get('href', '').replace('mailto:', '').strip()
        if not email_el and fantomas:
            email_el2 = fantomas.select_one('a[href^="mailto:"]')
            if email_el2:
                entry["pj_email"] = email_el2.get('href', '').replace('mailto:', '').strip()

        results.append(entry)

    # Check pagination
    page_links = re.findall(r'/page-(\d+)', html)
    max_page = max([int(p) for p in page_links], default=1) if page_links else 1

    return results, soup, max_page


def scrape_category(scraper_holder, cat_name, cat_slug):
    """Scrape all pages for a category."""
    all_results = []
    page_num = 1
    max_page = 1

    print(f"\n{'='*60}")
    print(f"Category: {cat_name}")
    print(f"{'='*60}")

    while page_num <= max(max_page, 50):  # Safety limit
        if page_num == 1:
            url = f"https://www.pagesjaunes.fr/annuaire/lyon-69/{cat_slug}"
        else:
            url = f"https://www.pagesjaunes.fr/annuaire/lyon-69/{cat_slug}/page-{page_num}"

        print(f"  Page {page_num}: {url}")

        resp = fetch_with_retry(scraper_holder, url)
        if resp is None:
            print(f"    Failed after {MAX_RETRIES} retries, stopping category.")
            break

        if resp.status_code == 404:
            print(f"    404 - end of pages")
            break

        if 'Aucun résultat' in resp.text or 'aucun professionnel' in resp.text.lower():
            print(f"    No results found")
            break

        listings, soup, detected_max = extract_listings(resp.text)
        if page_num == 1 and detected_max > 1:
            max_page = detected_max
            print(f"    Detected max page: {max_page}")

        print(f"    Found {len(listings)} listings")
        phones_count = sum(1 for l in listings if l.get('pj_telephone'))
        print(f"    With phone: {phones_count}")

        if not listings:
            if page_num == 1:
                print(f"    No listings on page 1")
            break

        all_results.extend(listings)
        page_num += 1
        time.sleep(DELAY_BETWEEN_REQUESTS)

    print(f"  Total for '{cat_name}': {len(all_results)} listings")
    return all_results


def normalize_name(name):
    if not name:
        return ""
    name = name.upper()
    name = re.sub(r'\b(SARL|SAS|SA|EURL|SCI|SNC|AUTOMOBILES?|CARROSSERIE)\b', '', name)
    name = re.sub(r'\(.*?\)', '', name)
    name = re.sub(r'[^A-Z0-9\s]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def normalize_address(addr):
    if not addr:
        return ""
    addr = addr.upper()
    addr = re.sub(r'[^A-Z0-9\s]', '', addr)
    addr = re.sub(r'\s+', ' ', addr).strip()
    return addr


def match_pj_to_source(pj_results, source_data):
    """Match PJ results to source data with fuzzy matching."""
    matches = {}  # source_idx -> (pj_entry, score)

    print(f"Matching {len(pj_results)} PJ results against {len(source_data)} source entries...")

    for pj_idx, pj in enumerate(pj_results):
        pj_name = pj.get("pj_nom", "")
        pj_addr = pj.get("pj_adresse", "")
        pj_name_norm = normalize_name(pj_name)
        pj_addr_norm = normalize_address(pj_addr)
        pj_words = set(pj_name_norm.split()) if pj_name_norm else set()

        best_score = 0
        best_idx = None

        for idx, src in enumerate(source_data):
            src_name = src.get("nom", "")
            src_addr = src.get("adresse", "")
            src_name_norm = normalize_name(src_name)
            src_addr_norm = normalize_address(src_addr)

            # Quick pre-filter: at least one word in common
            src_words = set(src_name_norm.split()) if src_name_norm else set()
            common_words = pj_words & src_words
            if not common_words and pj_name_norm and src_name_norm:
                # Check substring match
                if pj_name_norm not in src_name_norm and src_name_norm not in pj_name_norm:
                    # Check address overlap as last resort
                    if pj_addr_norm and src_addr_norm:
                        addr_overlap = SequenceMatcher(None, pj_addr_norm, src_addr_norm).ratio()
                        if addr_overlap < 0.6:
                            continue
                    else:
                        continue

            name_score = SequenceMatcher(None, pj_name_norm, src_name_norm).ratio() if pj_name_norm and src_name_norm else 0
            addr_score = SequenceMatcher(None, pj_addr_norm, src_addr_norm).ratio() if pj_addr_norm and src_addr_norm else 0

            combined = name_score * 0.6 + addr_score * 0.4

            if name_score > 0.5 and addr_score > 0.5:
                combined += 0.1
            if len(common_words) >= 2:
                combined += 0.1
            elif len(common_words) >= 1 and len(min(pj_words, src_words, key=len)) <= 2:
                combined += 0.05

            if combined > best_score and combined > 0.45:
                best_score = combined
                best_idx = idx

        if best_idx is not None:
            if best_idx not in matches or matches[best_idx][1] < best_score:
                matches[best_idx] = (pj, best_score)

    return matches


def main():
    print("Loading source data...")
    with open(SOURCE_FILE, "r", encoding="utf-8") as f:
        source_data = json.load(f)
    print(f"Loaded {len(source_data)} companies")

    # Check for cached PJ results
    all_pj_results = []
    scraped_categories = set()
    if os.path.exists(PJ_CACHE_FILE):
        with open(PJ_CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)
        if isinstance(cache, dict):
            all_pj_results = cache.get("results", [])
            scraped_categories = set(cache.get("done_categories", []))
        elif isinstance(cache, list):
            all_pj_results = cache
        print(f"Loaded {len(all_pj_results)} cached results, done categories: {scraped_categories}")

    # Scrape remaining categories
    scraper_holder = [create_scraper()]
    categories_to_do = [(n, s) for n, s in CATEGORIES if n not in scraped_categories]

    if categories_to_do:
        for cat_name, cat_slug in categories_to_do:
            results = scrape_category(scraper_holder, cat_name, cat_slug)
            all_pj_results.extend(results)
            scraped_categories.add(cat_name)

            # Save cache
            with open(PJ_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "results": all_pj_results,
                    "done_categories": list(scraped_categories)
                }, f, ensure_ascii=False, indent=2)
            print(f"  Cached. Total: {len(all_pj_results)} results")

            time.sleep(3)

    print(f"\nTotal PJ results: {len(all_pj_results)}")

    # Deduplicate by normalized name
    seen = set()
    unique_pj = []
    for r in all_pj_results:
        key = normalize_name(r.get("pj_nom", ""))
        addr = normalize_address(r.get("pj_adresse", ""))
        dedup_key = f"{key}|{addr}"
        if dedup_key and dedup_key not in seen:
            seen.add(dedup_key)
            unique_pj.append(r)
    print(f"Unique after dedup: {len(unique_pj)}")

    # Stats
    with_phone = sum(1 for r in unique_pj if r.get("pj_telephone"))
    with_web = sum(1 for r in unique_pj if r.get("pj_site_web"))
    with_email = sum(1 for r in unique_pj if r.get("pj_email"))
    print(f"With phone: {with_phone}, with website: {with_web}, with email: {with_email}")

    # Match
    matches = match_pj_to_source(unique_pj, source_data)
    print(f"Matched: {len(matches)} / {len(source_data)} companies")

    # Enrich
    enriched = []
    matched_count = 0
    for idx, company in enumerate(source_data):
        entry = dict(company)
        if idx in matches:
            pj_data, score = matches[idx]
            entry["pj_telephone"] = pj_data.get("pj_telephone", "")
            entry["pj_telephone2"] = pj_data.get("pj_telephone2", "")
            entry["pj_site_web"] = pj_data.get("pj_site_web", "")
            entry["pj_email"] = pj_data.get("pj_email", "")
            entry["pj_adresse_pj"] = pj_data.get("pj_adresse", "")
            entry["pj_nom_match"] = pj_data.get("pj_nom", "")
            entry["pj_match_score"] = round(score, 3)
            entry["pj_enriched"] = True
            matched_count += 1
        else:
            entry["pj_telephone"] = ""
            entry["pj_telephone2"] = ""
            entry["pj_site_web"] = ""
            entry["pj_email"] = ""
            entry["pj_adresse_pj"] = ""
            entry["pj_nom_match"] = ""
            entry["pj_match_score"] = 0
            entry["pj_enriched"] = False
        enriched.append(entry)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"DONE! Enriched {matched_count}/{len(source_data)} companies")
    print(f"Saved to {OUTPUT_FILE}")
    print(f"{'='*60}")

    if matched_count > 0:
        scores = [matches[i][1] for i in matches]
        print(f"Match scores: min={min(scores):.3f}, max={max(scores):.3f}, avg={sum(scores)/len(scores):.3f}")
        print("\nSample matches (first 15):")
        for idx in list(matches.keys())[:15]:
            pj, score = matches[idx]
            src = source_data[idx]
            phone = pj.get('pj_telephone', 'N/A')
            print(f"  {src['nom'][:40]:40s} <-> {pj['pj_nom'][:40]:40s} ({score:.3f}) tel:{phone}")


if __name__ == "__main__":
    main()
