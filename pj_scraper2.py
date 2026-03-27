#!/usr/bin/env python3
"""
PagesJaunes scraper for garage/concession/carrosserie listings.
Uses curl_cffi with chrome101/104/110 impersonation and follows pagination
via the data-pjlb encoded next-page URL.
"""

import json
import time
import re
import sys
import base64
import random
from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup

OUTPUT_FILE = "/home/user/Website01/agent_pj_fresh_scrape.json"

# Impersonation modes that work (rotate to avoid blocks)
IMPERSONATE_MODES = ['chrome101', 'chrome104', 'chrome110', 'chrome120', 'chrome123', 'chrome124']

BASE_HEADERS = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7',
    'sec-fetch-dest': 'document',
    'sec-fetch-mode': 'navigate',
    'sec-fetch-site': 'none',
    'sec-fetch-user': '?1',
    'upgrade-insecure-requests': '1',
}

TARGETS = [
    # (location_slug, category, cp, ville)
    # Toulouse area - garage
    ("toulouse-31", "garage-automobile", "31000", "Toulouse"),
    ("colomiers-31770", "garage-automobile", "31770", "Colomiers"),
    ("blagnac-31700", "garage-automobile", "31700", "Blagnac"),
    ("muret-31600", "garage-automobile", "31600", "Muret"),
    # Toulouse area - concession
    ("toulouse-31", "concession-automobile", "31000", "Toulouse"),
    ("colomiers-31770", "concession-automobile", "31770", "Colomiers"),
    ("blagnac-31700", "concession-automobile", "31700", "Blagnac"),
    ("muret-31600", "concession-automobile", "31600", "Muret"),
    # Toulouse - carrosserie
    ("toulouse-31", "carrosserie-automobile", "31000", "Toulouse"),
    # Évry area
    ("evry-91000", "garage-automobile", "91000", "Évry"),
    ("evry-91000", "concession-automobile", "91000", "Évry"),
    ("corbeil-essonnes-91100", "garage-automobile", "91100", "Corbeil-Essonnes"),
    ("ris-orangis-91130", "garage-automobile", "91130", "Ris-Orangis"),
]

MAX_PAGES = 15
DELAY = 2.5


def get_impersonate():
    return random.choice(IMPERSONATE_MODES)


def format_phone(raw):
    """Normalize phone number to 0X XX XX XX XX format."""
    if not raw:
        return None
    digits = re.sub(r'\D', '', raw)
    # Handle +33 prefix
    if digits.startswith('33') and len(digits) == 11:
        digits = '0' + digits[2:]
    if len(digits) == 10 and digits.startswith('0'):
        return f"{digits[0:2]} {digits[2:4]} {digits[4:6]} {digits[6:8]} {digits[8:10]}"
    return None


def extract_phones_from_li(li):
    """Extract all phone numbers from a listing li element."""
    phones = []
    for nc in li.find_all(class_='number-contact'):
        text = nc.get_text(strip=True)
        # Remove markers
        text = re.sub(r'Tél\s*:\s*', '', text, flags=re.I)
        text = re.sub(r'Opposé aux opérations de marketing', '', text, flags=re.I)
        text = re.sub(r'Fax\s*:\s*', '', text, flags=re.I)
        nums = re.findall(r'0[1-9](?:[\s\.\-]?\d{2}){4}', text)
        for n in nums:
            formatted = format_phone(n)
            if formatted and formatted not in phones:
                phones.append(formatted)
    return phones


def extract_address_from_li(li):
    """Extract address from a listing li element."""
    # Try .bi-address
    addr_el = li.select_one('.bi-address')
    if addr_el:
        # Remove 'Voir le plan' text
        text = addr_el.get_text(separator=' ', strip=True)
        text = re.sub(r'Voir le plan', '', text, flags=re.I).strip()
        text = re.sub(r'\s+', ' ', text)
        return text
    # Try itemprop
    addr_el = li.find(itemprop='address')
    if addr_el:
        return addr_el.get_text(separator=' ', strip=True)
    return ''


def parse_page_listings(soup, cp_default, ville_default, categorie):
    """Parse all listings from a page soup."""
    results = []

    # Find all li elements containing number-contact (these are listing items)
    lis = soup.find_all('li')

    for li in lis:
        ncs = li.find_all(class_='number-contact')
        if not ncs:
            continue

        # Name
        name = ''
        h3 = li.find('h3')
        if h3:
            name = h3.get_text(strip=True)
        if not name:
            denom = li.select_one('.bi-denomination')
            if denom:
                name = denom.get_text(strip=True)

        # Phones
        phones = extract_phones_from_li(li)

        # Address
        address = extract_address_from_li(li)

        # Extract CP from address if possible
        cp = cp_default
        ville = ville_default
        cp_match = re.search(r'\b(\d{5})\b', address)
        if cp_match:
            cp = cp_match.group(1)

        # Create entries for each phone
        if phones:
            for phone in phones:
                results.append({
                    "nom": name,
                    "telephone": phone,
                    "adresse": address,
                    "code_postal": cp,
                    "ville": ville,
                    "categorie": categorie,
                    "source": "PJ_fresh"
                })
        elif name:
            # Include even without phone
            results.append({
                "nom": name,
                "telephone": "",
                "adresse": address,
                "code_postal": cp,
                "ville": ville,
                "categorie": categorie,
                "source": "PJ_fresh"
            })

    return results


def get_next_page_url(soup):
    """Extract the next page URL from pagination."""
    # Find the "next" pagination link
    next_link = soup.find('a', id='pagination-next')
    if not next_link:
        next_link = soup.find('a', class_=re.compile(r'\bnext\b'))

    if next_link:
        # Check if it's disabled
        classes = next_link.get('class', [])
        if 'disabled' in classes:
            return None

        # Extract URL from data-pjlb
        pjlb = next_link.get('data-pjlb', '')
        if pjlb:
            try:
                d = json.loads(pjlb)
                url_b64 = d.get('url', '')
                if url_b64:
                    decoded = base64.b64decode(url_b64).decode('utf-8')
                    if decoded.startswith('/'):
                        return 'https://www.pagesjaunes.fr' + decoded
                    return decoded
            except Exception:
                pass

        # Try href directly
        href = next_link.get('href', '')
        if href and href != '#':
            return href

    return None


def get_total_pages(soup):
    """Get total number of pages from pagination."""
    compteur = soup.select_one('#SEL-compteur')
    if compteur:
        text = compteur.get_text(strip=True)
        m = re.search(r'Page\s+\d+\s*/\s*(\d+)', text, re.I)
        if m:
            return int(m.group(1))
    return 1


def fetch_url(url, referer=None, max_retries=5):
    """Fetch a URL with retries and different impersonation modes."""
    headers = dict(BASE_HEADERS)
    if referer:
        headers['Referer'] = referer
        headers['sec-fetch-site'] = 'same-origin'

    for attempt in range(max_retries):
        imp = get_impersonate()
        try:
            resp = cffi_requests.get(
                url,
                headers=headers,
                impersonate=imp,
                timeout=30
            )

            if resp.status_code == 200 and len(resp.text) > 20000:
                return resp.text, resp.url
            elif resp.status_code == 200 and 'challenge' in resp.text.lower():
                print(f"    Cloudflare challenge (attempt {attempt+1}), waiting...")
                time.sleep(5 + attempt * 3)
            elif resp.status_code == 403:
                print(f"    403 with {imp} (attempt {attempt+1}), retrying...")
                time.sleep(4 + attempt * 2)
            elif resp.status_code == 404:
                print(f"    404 - page not found")
                return None, url
            else:
                print(f"    HTTP {resp.status_code} with {imp} (attempt {attempt+1})")
                time.sleep(3)
        except Exception as e:
            print(f"    Error with {imp}: {e}")
            time.sleep(3)

    return None, url


def scrape_target(location_slug, categorie, cp, ville):
    """Scrape all pages for a target location+category."""
    all_entries = []
    seen_phones = set()

    print(f"\n=== {categorie} in {ville} ({cp}) ===")

    first_url = f"https://www.pagesjaunes.fr/annuaire/{location_slug}/{categorie}"
    current_url = first_url
    prev_url = None
    page_num = 1

    while current_url and page_num <= MAX_PAGES:
        print(f"  Page {page_num}: {current_url[:80]}...")

        html, actual_url = fetch_url(current_url, referer=prev_url)
        if not html:
            print(f"    Failed to fetch page {page_num}")
            break

        soup = BeautifulSoup(html, 'html.parser')

        # Get total pages on first page
        if page_num == 1:
            total = get_total_pages(soup)
            print(f"    Total pages: {total}")

        # Parse listings
        entries = parse_page_listings(soup, cp, ville, categorie)

        # Deduplicate
        new_entries = 0
        for entry in entries:
            phone = entry.get("telephone", "")
            if phone:
                if phone not in seen_phones:
                    seen_phones.add(phone)
                    all_entries.append(entry)
                    new_entries += 1
            else:
                all_entries.append(entry)
                new_entries += 1

        print(f"    Got {len(entries)} entries, {new_entries} new, total phones: {len(seen_phones)}")

        if new_entries == 0 and page_num > 1:
            print("    No new entries, stopping")
            break

        # Get next page URL
        prev_url = current_url
        current_url = get_next_page_url(soup)
        page_num += 1

        if current_url:
            time.sleep(DELAY)

    print(f"  => Total for {ville}/{categorie}: {len(all_entries)} entries, {len(seen_phones)} with phones")
    return all_entries


def main():
    all_results = []

    for location_slug, categorie, cp, ville in TARGETS:
        entries = scrape_target(location_slug, categorie, cp, ville)
        all_results.extend(entries)
        print(f"  Running total: {len(all_results)} entries")
        time.sleep(DELAY)

    # Final deduplication
    seen_phones = set()
    seen_names = set()
    deduped = []

    # First pass: entries with phones
    for entry in all_results:
        phone = entry.get("telephone", "").strip()
        if phone:
            if phone not in seen_phones:
                seen_phones.add(phone)
                deduped.append(entry)

    # Second pass: entries without phones (unique by name)
    for entry in all_results:
        phone = entry.get("telephone", "").strip()
        if not phone:
            name = entry.get("nom", "").strip()
            if name and name not in seen_names:
                seen_names.add(name)
                deduped.append(entry)

    entries_with_phones = [e for e in deduped if e.get("telephone")]

    print(f"\n=== FINAL RESULTS ===")
    print(f"Total raw entries: {len(all_results)}")
    print(f"After deduplication: {len(deduped)}")
    print(f"Entries with phones: {len(entries_with_phones)}")

    # Save
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(deduped, f, ensure_ascii=False, indent=2)

    print(f"\nSaved {len(deduped)} entries to {OUTPUT_FILE}")

    # Print sample
    print("\nSample entries with phones:")
    for entry in entries_with_phones[:15]:
        print(f"  {entry['nom'][:40]:<40} | {entry['telephone']} | {entry['ville']}")

    # Stats by city/category
    print("\nStats by category/city:")
    from collections import Counter
    counter = Counter((e['ville'], e['categorie']) for e in entries_with_phones)
    for (ville, cat), count in sorted(counter.items()):
        print(f"  {ville:<20} {cat:<30} {count} phones")

    return len(entries_with_phones)


if __name__ == "__main__":
    count = main()
    print(f"\nFinal phone count: {count}")
    sys.exit(0 if count > 0 else 1)
