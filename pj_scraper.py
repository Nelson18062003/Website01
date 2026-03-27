#!/usr/bin/env python3
"""
PagesJaunes scraper for garage/concession/carrosserie listings
in Toulouse (31) and Évry (91) areas.
"""

import json
import time
import re
import sys
from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup

OUTPUT_FILE = "/home/user/Website01/agent_pj_fresh_scrape.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "max-age=0",
    "Referer": "https://www.pagesjaunes.fr/",
}

TARGETS = [
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

MAX_PAGES = 10  # max pages per target
DELAY = 2  # seconds between requests


def format_phone(raw):
    """Normalize phone number to 0X XX XX XX XX format."""
    if not raw:
        return None
    # Extract digits only
    digits = re.sub(r'\D', '', raw)
    # Handle +33 prefix
    if digits.startswith('33') and len(digits) == 11:
        digits = '0' + digits[2:]
    if len(digits) == 10 and digits.startswith('0'):
        return f"{digits[0:2]} {digits[2:4]} {digits[4:6]} {digits[6:8]} {digits[8:10]}"
    return None


def extract_json_ld(soup):
    """Extract business data from JSON-LD scripts."""
    results = []
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string or '')
            # Could be a list or single object
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = [data]
            else:
                continue
            for item in items:
                if isinstance(item, dict):
                    if item.get('@type') in ('LocalBusiness', 'AutoDealer', 'AutomotiveBusiness', 'AutoRepair', 'Organization', 'Store'):
                        name = item.get('name', '')
                        phone = item.get('telephone', '')
                        addr = item.get('address', {})
                        if isinstance(addr, dict):
                            address = ', '.join(filter(None, [
                                addr.get('streetAddress', ''),
                                addr.get('postalCode', ''),
                                addr.get('addressLocality', '')
                            ]))
                        else:
                            address = str(addr) if addr else ''
                        if name or phone:
                            results.append({
                                'name': name,
                                'phone': phone,
                                'address': address,
                            })
        except Exception:
            pass
    return results


def extract_initial_state(html_text):
    """Try to extract window.__INITIAL_STATE__ or similar JS vars."""
    results = []
    # Look for JSON data in JS variables
    patterns = [
        r'window\.__INITIAL_STATE__\s*=\s*({.+?});\s*(?:window|</script>)',
        r'window\.__DATA__\s*=\s*({.+?});\s*(?:window|</script>)',
        r'"listings"\s*:\s*(\[.+?\])',
    ]
    for pat in patterns:
        m = re.search(pat, html_text, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                # Try to navigate the data structure
                if isinstance(data, dict):
                    # Look for listings arrays
                    for key in ['listings', 'results', 'annonces', 'items', 'businesses']:
                        if key in data:
                            for item in (data[key] or []):
                                if isinstance(item, dict):
                                    results.append(item)
            except Exception:
                pass
    return results


def parse_listing_html(article, cp_default, ville_default, categorie):
    """Parse a single listing article element."""
    entry = {
        "nom": "",
        "telephone": "",
        "adresse": "",
        "code_postal": cp_default,
        "ville": ville_default,
        "categorie": categorie,
        "source": "PJ_fresh"
    }

    # Business name
    name_el = article.find(attrs={"data-denomination": True})
    if name_el:
        entry["nom"] = name_el.get("data-denomination", "").strip()
    if not entry["nom"]:
        for sel in [".bi-denomination a", "h3.bi-title a", ".denomination a", ".name a"]:
            el = article.select_one(sel)
            if el:
                entry["nom"] = el.get_text(strip=True)
                break
    if not entry["nom"]:
        # Try h3 directly
        h3 = article.find("h3")
        if h3:
            entry["nom"] = h3.get_text(strip=True)

    # Phone number - look for tel: links
    phone = None
    # Method 1: data-href with tel:
    for el in article.find_all(attrs={"data-href": True}):
        href = el.get("data-href", "")
        if "tel:" in href:
            phone = href.replace("tel:", "").strip()
            break
    # Method 2: a href with tel:
    if not phone:
        for el in article.find_all("a", href=True):
            href = el.get("href", "")
            if href.startswith("tel:"):
                phone = href.replace("tel:", "").strip()
                break
    # Method 3: elements with phone class
    if not phone:
        for el in article.find_all(class_=re.compile(r'phone|tel|numero', re.I)):
            # Check data attributes
            for attr in el.attrs:
                val = el.attrs[attr]
                if isinstance(val, str) and "tel:" in val:
                    phone = val.replace("tel:", "").strip()
                    break
            if phone:
                break
            # Check text content if it looks like a phone
            text = el.get_text(strip=True)
            if re.match(r'^[0-9\s\.\-\+]{10,}$', text):
                phone = text
    # Method 4: any element with data-phone or data-tel
    if not phone:
        for attr in ["data-phone", "data-tel", "data-numero"]:
            el = article.find(attrs={attr: True})
            if el:
                phone = el.get(attr, "").strip()
                break

    if phone:
        formatted = format_phone(phone)
        if formatted:
            entry["telephone"] = formatted
        else:
            entry["telephone"] = phone

    # Address
    addr = ""
    for sel in [".bi-address .bi-address", "[itemprop='address']", ".address-container", ".bi-address", ".adresse"]:
        el = article.select_one(sel)
        if el:
            addr = el.get_text(separator=" ", strip=True)
            break
    if not addr:
        el = article.find(itemprop="address")
        if el:
            addr = el.get_text(separator=" ", strip=True)
    entry["adresse"] = addr

    # Try to extract CP from address
    cp_match = re.search(r'\b(\d{5})\b', addr)
    if cp_match:
        entry["code_postal"] = cp_match.group(1)

    return entry


def scrape_page(url, cp, ville, categorie):
    """Scrape a single page and return list of entries."""
    try:
        resp = cffi_requests.get(url, headers=HEADERS, timeout=30, impersonate="chrome120")
        if resp.status_code != 200:
            print(f"  HTTP {resp.status_code} for {url}")
            return [], False

        html = resp.text
        soup = BeautifulSoup(html, 'html.parser')

        entries = []
        seen_phones = set()

        # Method 1: Parse JSON-LD
        json_ld_items = extract_json_ld(soup)
        for item in json_ld_items:
            phone_raw = item.get('phone', '')
            formatted = format_phone(phone_raw) if phone_raw else None
            if formatted and formatted in seen_phones:
                continue
            entry = {
                "nom": item.get('name', ''),
                "telephone": formatted or phone_raw or '',
                "adresse": item.get('address', ''),
                "code_postal": cp,
                "ville": ville,
                "categorie": categorie,
                "source": "PJ_fresh"
            }
            if formatted:
                seen_phones.add(formatted)
            if entry["nom"] or entry["telephone"]:
                entries.append(entry)

        # Method 2: Parse article/listing elements
        # Try various container selectors
        listing_containers = []
        for sel in [
            "article.bi-card",
            "article[data-bi-id]",
            ".bi-list article",
            ".SearchResult article",
            "article.annonce",
            ".listPage article",
            "div[data-bi-id]",
            ".result-item",
            "li.bi-item",
        ]:
            listing_containers = soup.select(sel)
            if listing_containers:
                print(f"    Found {len(listing_containers)} listings with selector: {sel}")
                break

        # If no specific containers, try all articles
        if not listing_containers:
            listing_containers = soup.find_all("article")
            if listing_containers:
                print(f"    Found {len(listing_containers)} generic articles")

        for article in listing_containers:
            entry = parse_listing_html(article, cp, ville, categorie)
            if entry["telephone"] and entry["telephone"] not in seen_phones:
                seen_phones.add(entry["telephone"])
                entries.append(entry)
            elif entry["nom"] and not any(e["nom"] == entry["nom"] for e in entries):
                entries.append(entry)

        # Check if there's a next page
        has_next = False
        next_patterns = [
            soup.select_one('a[rel="next"]'),
            soup.select_one('.pagination .next'),
            soup.select_one('a.next-page'),
            soup.select_one('[aria-label="Page suivante"]'),
            soup.select_one('.pager-next a'),
        ]
        for el in next_patterns:
            if el:
                has_next = True
                break

        # Also check if current page has listings (if not, stop)
        if not listing_containers and not json_ld_items:
            # Try to detect "no results"
            no_result_indicators = ['aucun résultat', 'no results', 'aucune annonce']
            page_text = html.lower()
            if any(ind in page_text for ind in no_result_indicators):
                has_next = False
            else:
                has_next = False  # Can't determine, stop

        return entries, has_next

    except Exception as e:
        print(f"  Error scraping {url}: {e}")
        return [], False


def scrape_target(location_slug, categorie, cp, ville):
    """Scrape all pages for a given target."""
    all_entries = []
    print(f"\n=== Scraping {categorie} in {ville} ({cp}) ===")

    for page_num in range(1, MAX_PAGES + 1):
        if page_num == 1:
            url = f"https://www.pagesjaunes.fr/annuaire/{location_slug}/{categorie}"
        else:
            url = f"https://www.pagesjaunes.fr/annuaire/{location_slug}/{categorie}/page-{page_num}"

        print(f"  Page {page_num}: {url}")
        entries, has_next = scrape_page(url, cp, ville, categorie)
        print(f"  -> Got {len(entries)} entries (has_next={has_next})")
        all_entries.extend(entries)

        if page_num < MAX_PAGES:
            time.sleep(DELAY)

        # Stop if no next page or no entries
        if not has_next and page_num > 1:
            break
        if len(entries) == 0 and page_num > 1:
            break

    print(f"  Total for {ville}/{categorie}: {len(all_entries)} entries")
    return all_entries


def main():
    all_results = []

    for location_slug, categorie, cp, ville in TARGETS:
        entries = scrape_target(location_slug, categorie, cp, ville)
        all_results.extend(entries)
        print(f"  Running total: {len(all_results)} entries")
        time.sleep(DELAY)

    # Deduplicate by phone number (keep first occurrence)
    seen_phones = set()
    deduped = []
    no_phone = []
    for entry in all_results:
        phone = entry.get("telephone", "").strip()
        if phone:
            if phone not in seen_phones:
                seen_phones.add(phone)
                deduped.append(entry)
        else:
            no_phone.append(entry)

    # Also add entries without phones (deduplicated by name)
    seen_names = set(e["nom"] for e in deduped)
    for entry in no_phone:
        name = entry.get("nom", "").strip()
        if name and name not in seen_names:
            seen_names.add(name)
            deduped.append(entry)

    print(f"\n=== FINAL RESULTS ===")
    print(f"Total raw entries: {len(all_results)}")
    print(f"Entries with phone: {len([e for e in deduped if e.get('telephone')])}")
    print(f"Total after dedup: {len(deduped)}")

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(deduped, f, ensure_ascii=False, indent=2)

    print(f"Saved to {OUTPUT_FILE}")

    # Print sample
    print("\nSample entries with phones:")
    count = 0
    for entry in deduped:
        if entry.get("telephone"):
            print(f"  {entry['nom']} | {entry['telephone']} | {entry['adresse']} | {entry['ville']}")
            count += 1
            if count >= 10:
                break

    return len(deduped)


if __name__ == "__main__":
    count = main()
    sys.exit(0 if count > 0 else 1)
