#!/usr/bin/env python3
"""
Scrape Pages Jaunes for auto garage phone numbers by department.

Scrapes "garage automobile" listings from pagesjaunes.fr for each of the
36 target departments, extracting: name, address, postal code, city,
phone, email, website.

Results are cached by department in JSON files to allow resuming.

Output: pagesjaunes_garages_<dept>.json per department
        pagesjaunes_garages_all.json consolidated file
"""

import requests
import json
import os
import re
import time
import sys
from bs4 import BeautifulSoup

# =============================================================================
# Configuration
# =============================================================================

BASE_URL = "https://www.pagesjaunes.fr/annuaire/chercherlespros"
SEARCH_WHAT = "garage automobile"

CACHE_DIR = "pj_cache"
OUTPUT_FILE = "pagesjaunes_garages_all.json"

# Target departments (Top Zone + Middle Zone)
TOP_ZONE_DEPTS = ["06", "59", "60", "77", "78", "88", "91", "93", "95"]
MIDDLE_ZONE_DEPTS = [
    "17", "24", "27", "28", "30", "31", "33", "35", "38", "40", "41", "42",
    "44", "45", "46", "57", "62", "67", "72", "73", "76", "79", "80", "83",
    "86", "971", "973",
]
ALL_DEPTS = TOP_ZONE_DEPTS + MIDDLE_ZONE_DEPTS

DEPT_NAMES = {
    "06": "Alpes-Maritimes", "17": "Charente-Maritime", "24": "Dordogne",
    "27": "Eure", "28": "Eure-et-Loir", "30": "Gard",
    "31": "Haute-Garonne", "33": "Gironde", "35": "Ille-et-Vilaine",
    "38": "Isere", "40": "Landes", "41": "Loir-et-Cher",
    "42": "Loire", "44": "Loire-Atlantique", "45": "Loiret",
    "46": "Lot", "57": "Moselle", "59": "Nord",
    "60": "Oise", "62": "Pas-de-Calais", "67": "Bas-Rhin",
    "72": "Sarthe", "73": "Savoie", "76": "Seine-Maritime",
    "77": "Seine-et-Marne", "78": "Yvelines", "79": "Deux-Sevres",
    "80": "Somme", "83": "Var", "86": "Vienne",
    "88": "Vosges", "91": "Essonne", "93": "Seine-Saint-Denis",
    "95": "Val-d-Oise", "971": "Guadeloupe", "973": "Guyane",
}

# HTTP headers to mimic a real browser
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
}

# Pagination
RESULTS_PER_PAGE = 20
MAX_PAGES = 100   # safety limit (20 * 100 = 2000 per dept, enough for any dept)

# Rate limiting
DELAY_BETWEEN_PAGES = 2.0    # seconds between page requests
DELAY_BETWEEN_DEPTS = 5.0    # seconds between departments


# =============================================================================
# Utility functions
# =============================================================================

def format_phone_international(phone):
    """Convert French phone to international +33 format."""
    if not phone:
        return ""
    p = str(phone).strip()
    # Take first number if multiple
    for sep in [";", "/", ","]:
        if sep in p:
            p = p.split(sep)[0].strip()

    digits = re.sub(r"[^\d+]", "", p)
    if digits.startswith("+33"):
        digits = "0" + digits[3:]
    elif digits.startswith("0033"):
        digits = "0" + digits[4:]
    elif digits.startswith("33") and len(digits) == 11:
        digits = "0" + digits[2:]

    digits = re.sub(r"[^\d]", "", digits)

    if digits.startswith("0") and len(digits) == 10:
        return (
            f"+33 {digits[1]} {digits[2:4]} {digits[4:6]} "
            f"{digits[6:8]} {digits[8:10]}"
        )
    return p


def clean_text(text):
    """Clean whitespace from extracted text."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text).strip())


def ensure_cache_dir():
    """Create cache directory if it doesn't exist."""
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)


def load_dept_cache(dept):
    """Load cached results for a department."""
    path = os.path.join(CACHE_DIR, f"pj_garages_{dept}.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return None


def save_dept_cache(dept, data):
    """Save scraped results for a department."""
    ensure_cache_dir()
    path = os.path.join(CACHE_DIR, f"pj_garages_{dept}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# =============================================================================
# Parsing functions
# =============================================================================

def parse_listing(card):
    """
    Parse a single business listing card from Pages Jaunes search results.

    Pages Jaunes HTML structure (approximate):
    <article class="bi-content" ...>
      <div class="bi-header">
        <h3 class="bi-denomination">...</h3>
      </div>
      <div class="bi-body">
        <address class="bi-address">...</address>
        <div class="bi-phone">...</div>
        <div class="bi-more-info">email, website...</div>
      </div>
    </article>
    """
    result = {
        "name": "",
        "address": "",
        "postal_code": "",
        "city": "",
        "phone": "",
        "phone_intl": "",
        "email": "",
        "website": "",
        "source": "Pages Jaunes",
    }

    # --- Name ---
    name_el = (
        card.find(class_="bi-denomination")
        or card.find(class_="denomination-links")
        or card.find(class_="pj-lb__name")
        or card.find("h3")
    )
    if name_el:
        a = name_el.find("a")
        result["name"] = clean_text(a.get_text() if a else name_el.get_text())

    # --- Address ---
    addr_el = (
        card.find(class_="bi-address")
        or card.find("address")
        or card.find(class_="pj-lb__address")
    )
    if addr_el:
        # Try sub-elements first
        street_el = addr_el.find(class_=re.compile(r"street|adresse", re.I))
        zip_el = addr_el.find(class_=re.compile(r"zip|postcode|postal", re.I))
        city_el = addr_el.find(class_=re.compile(r"city|commune|ville", re.I))

        if street_el:
            result["address"] = clean_text(street_el.get_text())
        if zip_el:
            result["postal_code"] = clean_text(zip_el.get_text())
        if city_el:
            result["city"] = clean_text(city_el.get_text())

        # Fallback: parse full address text
        if not result["postal_code"]:
            addr_text = clean_text(addr_el.get_text())
            # Look for 5-digit postal code
            m = re.search(r"\b(\d{5})\b", addr_text)
            if m:
                result["postal_code"] = m.group(1)
                # City is usually after postal code
                after = addr_text[m.end():].strip().lstrip(",").strip()
                result["city"] = after.split(",")[0].strip() if after else ""
                # Street is before postal code
                before = addr_text[:m.start()].strip().rstrip(",")
                result["address"] = before

    # --- Phone ---
    # Pages Jaunes may store phone in data attributes or visible text
    phone_el = (
        card.find(class_=re.compile(r"phone|tel|numero", re.I))
        or card.find("a", href=re.compile(r"^tel:", re.I))
        or card.find(attrs={"data-phone": True})
        or card.find(attrs={"data-href": re.compile(r"tel:", re.I)})
    )
    if phone_el:
        # Check data-phone attribute
        phone = (
            phone_el.get("data-phone")
            or phone_el.get("data-href", "").replace("tel:", "")
            or phone_el.get("href", "").replace("tel:", "")
            or clean_text(phone_el.get_text())
        )
        if phone and re.search(r"\d{4,}", phone):
            result["phone"] = clean_text(phone)
            result["phone_intl"] = format_phone_international(phone)

    # Also check tel: links anywhere in the card
    if not result["phone"]:
        for a in card.find_all("a", href=re.compile(r"^tel:", re.I)):
            phone = a.get("href", "").replace("tel:", "").replace("+", "00").strip()
            if phone and re.search(r"\d{6,}", phone):
                result["phone"] = clean_text(a.get_text()) or phone
                result["phone_intl"] = format_phone_international(
                    a.get("href", "").replace("tel:", "")
                )
                break

    # --- Email ---
    email_el = card.find("a", href=re.compile(r"^mailto:", re.I))
    if email_el:
        result["email"] = email_el.get("href", "").replace("mailto:", "").strip()

    # --- Website ---
    website_el = card.find(class_=re.compile(r"site|web|url", re.I))
    if website_el:
        a = website_el.find("a")
        if a and a.get("href") and not a["href"].startswith("tel:"):
            href = a["href"]
            if href.startswith("http"):
                result["website"] = href

    return result


def parse_page(html):
    """Parse a Pages Jaunes search results page, return list of listings."""
    soup = BeautifulSoup(html, "html.parser")
    listings = []

    # Find all listing cards - try multiple selectors
    cards = (
        soup.find_all("article", class_=re.compile(r"bi-content|annonce|listing", re.I))
        or soup.find_all(class_=re.compile(r"bi-content|pj-lb__container", re.I))
        or soup.find_all("li", class_=re.compile(r"result|listing", re.I))
    )

    for card in cards:
        result = parse_listing(card)
        if result["name"]:  # Only keep results with a name
            listings.append(result)

    return listings


def get_total_pages(html):
    """Extract total number of pages from the search results page."""
    soup = BeautifulSoup(html, "html.parser")

    # Look for pagination info
    # Try "X résultats" text
    total_el = soup.find(class_=re.compile(r"nb-results|total-results|count", re.I))
    if total_el:
        m = re.search(r"(\d+)", total_el.get_text())
        if m:
            total = int(m.group(1))
            return max(1, (total + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE)

    # Try last page number in pagination
    pager = soup.find(class_=re.compile(r"pager|pagination", re.I))
    if pager:
        page_nums = [
            int(a.get_text().strip())
            for a in pager.find_all("a")
            if a.get_text().strip().isdigit()
        ]
        if page_nums:
            return max(page_nums)

    return 1  # Default: assume at least 1 page


# =============================================================================
# Scraping functions
# =============================================================================

def build_search_url(dept, page=1):
    """Build Pages Jaunes search URL for a department."""
    dept_name = DEPT_NAMES.get(dept, dept)
    # Pages Jaunes accepts department names or numbers in 'ou' parameter
    params = (
        f"quoiqui={requests.utils.quote(SEARCH_WHAT)}"
        f"&ou={requests.utils.quote(dept_name)}"
    )
    if page > 1:
        params += f"&page={page}"
    return f"{BASE_URL}?{params}"


def scrape_department(dept, session):
    """Scrape all garage listings for a given department."""
    results = []
    dept_name = DEPT_NAMES.get(dept, dept)

    print(f"    Scraping dept {dept} ({dept_name})...")

    # Fetch first page
    url = build_search_url(dept, page=1)
    try:
        resp = session.get(url, headers=HEADERS, timeout=20)
        if resp.status_code == 429:
            print("    [RATE LIMIT] Waiting 30s...")
            time.sleep(30)
            resp = session.get(url, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            print(f"    [ERROR] HTTP {resp.status_code} for {url}")
            return results
    except requests.exceptions.RequestException as e:
        print(f"    [ERROR] Request failed: {e}")
        return results

    html = resp.text
    page_results = parse_page(html)
    results.extend(page_results)

    # Determine how many pages exist
    total_pages = get_total_pages(html)
    total_pages = min(total_pages, MAX_PAGES)
    print(f"    Pages: {total_pages} | Page 1: {len(page_results)} listings")

    # Fetch remaining pages
    for page in range(2, total_pages + 1):
        time.sleep(DELAY_BETWEEN_PAGES)
        url = build_search_url(dept, page=page)
        try:
            resp = session.get(url, headers=HEADERS, timeout=20)
            if resp.status_code == 429:
                print(f"    [RATE LIMIT] Page {page}, waiting 30s...")
                time.sleep(30)
                resp = session.get(url, headers=HEADERS, timeout=20)
            if resp.status_code != 200:
                print(f"    [WARN] HTTP {resp.status_code} on page {page}")
                break

            page_html = resp.text
            page_results = parse_page(page_html)
            if not page_results:
                # Empty page → stop
                print(f"    Page {page}: 0 listings, stopping.")
                break

            results.extend(page_results)
            print(f"    Page {page}/{total_pages}: {len(page_results)} listings "
                  f"(total: {len(results)})")

        except requests.exceptions.RequestException as e:
            print(f"    [ERROR] Page {page}: {e}")
            break

    # Add department info to each result
    for r in results:
        r["department_num"] = dept
        r["department_name"] = DEPT_NAMES.get(dept, dept)
        r["zone"] = "Top Zone" if dept in TOP_ZONE_DEPTS else "Middle Zone"

    return results


# =============================================================================
# Main
# =============================================================================

def main():
    print("=" * 70)
    print("  SCRAPING PAGES JAUNES - GARAGES AUTOMOBILES")
    print(f"  Recherche: '{SEARCH_WHAT}'")
    print(f"  Départements cibles: {len(ALL_DEPTS)}")
    print("=" * 70)

    ensure_cache_dir()

    # Create persistent session for cookie handling
    session = requests.Session()

    # Warm up session with homepage visit
    print("\nInitialisation session...")
    try:
        session.get("https://www.pagesjaunes.fr", headers=HEADERS, timeout=15)
        time.sleep(2)
    except Exception:
        pass

    all_results = []
    total_depts = len(ALL_DEPTS)

    for i, dept in enumerate(sorted(ALL_DEPTS, key=lambda x: x.zfill(3)), 1):
        dept_name = DEPT_NAMES.get(dept, dept)
        print(f"\n[{i:2d}/{total_depts}] Département {dept} - {dept_name}")

        # Check cache first
        cached = load_dept_cache(dept)
        if cached is not None:
            print(f"  Chargé depuis cache: {len(cached)} résultats")
            all_results.extend(cached)
            continue

        # Scrape
        results = scrape_department(dept, session)
        with_phone = sum(1 for r in results if r.get("phone"))
        print(f"  Résultats: {len(results)} | Avec téléphone: {with_phone}")

        # Save to cache
        save_dept_cache(dept, results)
        all_results.extend(results)

        # Delay between departments
        if i < total_depts:
            time.sleep(DELAY_BETWEEN_DEPTS)

    # Deduplicate by phone or name+city
    print(f"\nDéduplication ({len(all_results)} entrées brutes)...")
    seen = set()
    unique_results = []
    for r in all_results:
        phone_norm = re.sub(r"[^\d]", "", r.get("phone", ""))
        name_city = f"{r.get('name', '').lower().strip()}|{r.get('city', '').lower().strip()}"
        key = phone_norm if phone_norm and len(phone_norm) >= 8 else name_city
        if key and key not in seen:
            seen.add(key)
            unique_results.append(r)

    # Save consolidated output
    print(f"  Unique: {len(unique_results)}")
    with_phone = sum(1 for r in unique_results if r.get("phone"))
    with_email = sum(1 for r in unique_results if r.get("email"))

    print(f"\nSauvegarde dans {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(unique_results, f, ensure_ascii=False, indent=2)

    # Summary
    print("\n" + "=" * 70)
    print("  RÉSUMÉ")
    print("=" * 70)
    print(f"  Total garages scrapés:    {len(unique_results):,}")
    print(f"  Avec numéro de téléphone: {with_phone:,} ({with_phone/max(1,len(unique_results))*100:.1f}%)")
    print(f"  Avec email:               {with_email:,}")
    print(f"\n  Fichier: {OUTPUT_FILE}")
    print(f"  Cache:   {CACHE_DIR}/pj_garages_<dept>.json")
    print("\nTerminé!")


if __name__ == "__main__":
    main()
