#!/usr/bin/env python3
"""
Scrape Pages Jaunes for auto garage data (phone numbers, addresses).

Uses curl_cffi to bypass Cloudflare protection.
Searches by department for "garage automobile" and paginates through results.
Caches results to JSON files per department.

Usage:
    python3 scrape_pagesjaunes_garages.py              # All 36 departments
    python3 scrape_pagesjaunes_garages.py 59 62 80     # Specific departments

Output: pagesjaunes_garages_cache/ directory with JSON files per department.
"""

import json
import os
import re
import sys
import time

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    print("ERROR: curl_cffi is required. Install with: pip install curl_cffi")
    sys.exit(1)

from bs4 import BeautifulSoup

# =============================================================================
# Configuration
# =============================================================================

CACHE_DIR = "pagesjaunes_garages_cache"
RESULTS_PER_PAGE = 20
MAX_PAGES_PER_DEPT = 80  # Safety limit (80 pages * 20 = 1600 results max)
DELAY_BETWEEN_PAGES = 2.5  # seconds
DELAY_BETWEEN_DEPTS = 5.0  # seconds

# Search queries to cover different garage types
SEARCH_QUERIES = [
    "garage automobile",
    "réparation automobile",
]

# Department definitions (same as build_garages_auto_zones.py)
TOP_ZONE_DEPTS = ["06", "59", "60", "77", "78", "88", "91", "93", "95"]
MIDDLE_ZONE_DEPTS = [
    "17", "24", "27", "28", "30", "31", "33", "35", "38", "40", "41", "42",
    "44", "45", "46", "57", "62", "67", "72", "73", "76", "79", "80", "83",
    "86", "971", "973",
]

DEPT_NAMES = {
    "06": "Alpes-Maritimes", "17": "Charente-Maritime", "24": "Dordogne",
    "27": "Eure", "28": "Eure-et-Loir", "30": "Gard", "31": "Haute-Garonne",
    "33": "Gironde", "35": "Ille-et-Vilaine", "38": "Isère", "40": "Landes",
    "41": "Loir-et-Cher", "42": "Loire", "44": "Loire-Atlantique",
    "45": "Loiret", "46": "Lot", "57": "Moselle", "59": "Nord",
    "60": "Oise", "62": "Pas-de-Calais", "67": "Bas-Rhin", "72": "Sarthe",
    "73": "Savoie", "76": "Seine-Maritime", "77": "Seine-et-Marne",
    "78": "Yvelines", "79": "Deux-Sèvres", "80": "Somme", "83": "Var",
    "86": "Vienne", "88": "Vosges", "91": "Essonne",
    "93": "Seine-Saint-Denis", "95": "Val-d'Oise",
    "971": "Guadeloupe", "973": "Guyane",
}


# =============================================================================
# HTML Parsing
# =============================================================================

def clean_phone(text):
    """Extract and clean phone number from raw text."""
    if not text:
        return ""
    # Remove "Opposé aux opérations de marketing" prefix
    text = re.sub(r'Opposé aux opérations de marketing\s*', '', text)
    text = re.sub(r'Tél\s*:\s*', '', text)
    text = text.strip()
    # Extract phone pattern
    match = re.search(r'(\+?\d[\d\s.()-]{7,})', text)
    if match:
        return match.group(1).strip()
    return text.strip() if re.search(r'\d{6,}', text) else ""


def format_phone_international(phone):
    """Convert French phone to international +33 format."""
    if not phone:
        return ""
    p = str(phone).strip()
    for sep in [";", "/", ","]:
        if sep in p:
            p = p.split(sep)[0].strip()
    digits = re.sub(r'[^\d+]', '', p)
    if digits.startswith('+33'):
        digits = '0' + digits[3:]
    elif digits.startswith('0033'):
        digits = '0' + digits[4:]
    elif digits.startswith('33') and len(digits) == 11:
        digits = '0' + digits[2:]
    digits = re.sub(r'[^\d]', '', digits)
    if digits.startswith('0') and len(digits) == 10:
        return f"+33 {digits[1]} {digits[2:4]} {digits[4:6]} {digits[6:8]} {digits[8:10]}"
    elif len(digits) == 9 and not digits.startswith('0'):
        return f"+33 {digits[0]} {digits[1:3]} {digits[3:5]} {digits[5:7]} {digits[7:9]}"
    return p


def extract_postal_city(address_text):
    """Extract postal code and city from address string."""
    if not address_text:
        return "", "", address_text or ""
    text = address_text.strip()
    # Pattern: ... 59000 Lille or ... 97100 Basse-Terre
    match = re.search(r'(\d{5})\s+(.+?)$', text)
    if match:
        postal = match.group(1)
        city = match.group(2).strip()
        street = text[:match.start()].strip()
        return postal, city, street
    return "", "", text


def parse_listings(html):
    """Parse Pages Jaunes HTML and extract garage listings."""
    soup = BeautifulSoup(html, 'lxml')
    listings = soup.select('li.bi')
    results = []

    for li in listings:
        # Name
        name_el = li.select_one('h3')
        name = name_el.get_text(strip=True) if name_el else ''
        if not name:
            continue

        # Address
        addr_el = li.select_one('.bi-address')
        addr_text = ''
        if addr_el:
            addr_text = addr_el.get_text(separator=' ', strip=True)
            addr_text = addr_text.replace('Voir le plan', '').strip()
            addr_text = re.sub(r'\s+', ' ', addr_text)

        postal_code, city, street = extract_postal_city(addr_text)

        # Phone - from fantomas div (hidden phone number revealed on click)
        phone = ''
        fantomas = li.select_one('.bi-fantomas')
        if fantomas:
            phone_text = fantomas.get_text(strip=True)
            phone = clean_phone(phone_text)

        if not phone:
            num_contact = li.select_one('.number-contact')
            if num_contact:
                phone = clean_phone(num_contact.get_text(strip=True))

        phone_intl = format_phone_international(phone)

        # Activity type
        activity_el = li.select_one('.bi-activity-unit')
        activity = activity_el.get_text(strip=True) if activity_el else ''

        # PJ internal ID
        ancre = li.select_one('.ancre-google')
        pj_id = ancre.get('id', '').replace('epj-', '') if ancre else ''

        entry = {
            'name': name,
            'phone': phone,
            'phone_intl': phone_intl,
            'address': street,
            'postal_code': postal_code,
            'city': city,
            'full_address': addr_text,
            'activity': activity,
            'pj_id': pj_id,
            'source': 'Pages Jaunes',
        }
        results.append(entry)

    return results


# =============================================================================
# Scraping
# =============================================================================

def scrape_department(dept_num, session, query="garage automobile"):
    """Scrape all pages of garage listings for a department."""
    dept_name = DEPT_NAMES.get(dept_num, dept_num)
    ou_param = f"{dept_name} ({dept_num})"

    all_results = []
    page = 1
    consecutive_errors = 0
    empty_pages = 0

    while page <= MAX_PAGES_PER_DEPT:
        url = "https://www.pagesjaunes.fr/annuaire/chercherlespros"
        params = {
            'quoiqui': query,
            'ou': ou_param,
            'page': str(page),
        }

        try:
            resp = session.get(url, params=params, timeout=20)

            if resp.status_code == 403:
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    print(f"      [WARN] 3x 403 errors at page {page}, stopping")
                    break
                time.sleep(8)
                continue

            if resp.status_code != 200:
                print(f"      [WARN] HTTP {resp.status_code} on page {page}")
                break

            consecutive_errors = 0
            listings = parse_listings(resp.text)

            if not listings:
                empty_pages += 1
                if empty_pages >= 2:
                    break
                page += 1
                time.sleep(DELAY_BETWEEN_PAGES)
                continue

            empty_pages = 0
            all_results.extend(listings)

            if page % 10 == 0:
                print(f"      p.{page}: +{len(listings)} "
                      f"(total: {len(all_results)})")

            # If we got fewer than a full page, we're at the end
            if len(listings) < RESULTS_PER_PAGE:
                break

            page += 1
            time.sleep(DELAY_BETWEEN_PAGES)

        except Exception as e:
            print(f"      [ERROR] Page {page}: {e}")
            consecutive_errors += 1
            if consecutive_errors >= 3:
                break
            time.sleep(5)

    return all_results


def deduplicate_results(results):
    """Remove duplicate entries based on pj_id or phone+name combo."""
    seen_ids = set()
    seen_phones = set()
    unique = []
    for r in results:
        pj_id = r.get('pj_id', '')
        if pj_id and pj_id in seen_ids:
            continue
        phone_digits = re.sub(r'[^\d]', '', r.get('phone', ''))
        if phone_digits and len(phone_digits) >= 8 and phone_digits in seen_phones:
            continue
        if pj_id:
            seen_ids.add(pj_id)
        if phone_digits and len(phone_digits) >= 8:
            seen_phones.add(phone_digits)
        unique.append(r)
    return unique


def load_cache(dept_num):
    """Load cached results for a department."""
    filepath = os.path.join(CACHE_DIR, f"dept_{dept_num}.json")
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_cache(dept_num, data):
    """Save results to cache."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    filepath = os.path.join(CACHE_DIR, f"dept_{dept_num}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# =============================================================================
# Main
# =============================================================================

def main():
    print("=" * 70)
    print("  SCRAPING PAGES JAUNES - GARAGES AUTOMOBILES")
    print("  (curl_cffi + Cloudflare bypass)")
    print("=" * 70)

    all_depts = sorted(
        TOP_ZONE_DEPTS + MIDDLE_ZONE_DEPTS,
        key=lambda x: x.zfill(3)
    )
    total_depts = len(all_depts)

    # Allow running specific departments from command line
    if len(sys.argv) > 1:
        requested = sys.argv[1:]
        all_depts = [d for d in requested if d in (TOP_ZONE_DEPTS + MIDDLE_ZONE_DEPTS)]
        if not all_depts:
            print(f"ERROR: None of {requested} are in the target departments.")
            sys.exit(1)
        total_depts = len(all_depts)
        print(f"\n  Running for specific departments: {all_depts}")

    print(f"\n  Departments to scrape: {total_depts}")
    print(f"  Delay between pages: {DELAY_BETWEEN_PAGES}s")
    print(f"  Search queries: {SEARCH_QUERIES}")
    print()

    # Create session with browser impersonation (bypasses Cloudflare)
    session = curl_requests.Session(impersonate='chrome120')

    grand_total = 0
    grand_with_phone = 0

    for i, dept in enumerate(all_depts, 1):
        dept_name = DEPT_NAMES.get(dept, dept)

        # Check cache
        cached = load_cache(dept)
        if cached is not None:
            total = len(cached)
            with_phone = sum(1 for r in cached if r.get('phone'))
            print(f"  [{i:2d}/{total_depts}] {dept} - {dept_name}: "
                  f"{total} garages, {with_phone} avec tél (CACHE)")
            grand_total += total
            grand_with_phone += with_phone
            continue

        print(f"  [{i:2d}/{total_depts}] {dept} - {dept_name}...", end=" ", flush=True)

        all_results = []
        for q_idx, query in enumerate(SEARCH_QUERIES):
            results = scrape_department(dept, session, query=query)
            all_results.extend(results)
            if q_idx < len(SEARCH_QUERIES) - 1:
                time.sleep(DELAY_BETWEEN_PAGES)

        # Deduplicate within department
        all_results = deduplicate_results(all_results)
        with_phone = sum(1 for r in all_results if r.get('phone'))

        print(f"{len(all_results)} garages, {with_phone} avec tél")

        # Save cache
        save_cache(dept, all_results)
        grand_total += len(all_results)
        grand_with_phone += with_phone

        if i < total_depts:
            time.sleep(DELAY_BETWEEN_DEPTS)

    # Summary
    print("\n" + "=" * 70)
    print("  RÉSUMÉ")
    print("=" * 70)
    print(f"  Total garages trouvés:     {grand_total:,}")
    print(f"  Avec numéro de téléphone:  {grand_with_phone:,}")
    print(f"  Cache: {CACHE_DIR}/")
    print("\nTerminé!")


if __name__ == "__main__":
    main()
