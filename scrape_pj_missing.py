#!/usr/bin/env python3
"""Scrape PagesJaunes for missing moto/auto categories."""

import json
import time
import re
import sys
from itertools import cycle

from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup

OUTPUT_FILE = "/home/user/Website01/agent_pj_moto_missing.json"

IMPERSONATES = cycle(["chrome101", "chrome104", "chrome110", "chrome120", "chrome124"])

TARGETS = [
    # concession-moto
    ("toulouse-31", "concession-moto", "Toulouse", "31000"),
    ("colomiers-31770", "concession-moto", "Colomiers", "31770"),
    ("blagnac-31700", "concession-moto", "Blagnac", "31700"),
    ("muret-31600", "concession-moto", "Muret", "31600"),
    # garage-moto
    ("toulouse-31", "garage-moto", "Toulouse", "31000"),
    ("colomiers-31770", "garage-moto", "Colomiers", "31770"),
    ("blagnac-31700", "garage-moto", "Blagnac", "31700"),
    ("muret-31600", "garage-moto", "Muret", "31600"),
    # carrosserie-automobile
    ("colomiers-31770", "carrosserie-automobile", "Colomiers", "31770"),
    ("blagnac-31700", "carrosserie-automobile", "Blagnac", "31700"),
    ("muret-31600", "carrosserie-automobile", "Muret", "31600"),
    # concession-automobile
    ("evry-91000", "concession-automobile", "Évry", "91000"),
    ("corbeil-essonnes-91100", "concession-automobile", "Corbeil-Essonnes", "91100"),
    ("ris-orangis-91130", "concession-automobile", "Ris-Orangis", "91130"),
    # garage-automobile
    ("bondoufle-91070", "garage-automobile", "Bondoufle", "91070"),
    ("lisses-91090", "garage-automobile", "Lisses", "91090"),
]

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://www.pagesjaunes.fr/",
}


def format_phone(raw: str) -> str:
    """Format phone number as 0X XX XX XX XX."""
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("33") and len(digits) == 11:
        digits = "0" + digits[2:]
    if len(digits) == 10:
        return " ".join([digits[i:i+2] for i in range(0, 10, 2)])
    return raw.strip()


def extract_postal(address: str) -> str:
    """Extract 5-digit postal code from address string."""
    m = re.search(r"\b(\d{5})\b", address)
    return m.group(1) if m else ""


def parse_listing(html: str, ville: str, cp: str, categorie: str) -> list:
    """Parse listings from HTML page."""
    soup = BeautifulSoup(html, "html.parser")
    results = []

    # Find all business items
    items = soup.select("li.bi")
    if not items:
        items = soup.select("article.bi, div.bi-card, div.bi-item")
    if not items:
        items = soup.select("div[class*='bi-']")

    print(f"  Found {len(items)} items on page")

    for item in items:
        # Name - h3 inside bi-denomination link or bi-header-title
        nom = ""
        for sel in [
            "a.bi-denomination h3",
            ".bi-denomination h3",
            ".bi-header-title h3",
            ".bi-denomination a",
            "h3.truncate-2-lines",
        ]:
            el = item.select_one(sel)
            if el:
                nom = el.get_text(strip=True)
                break

        # Phone - in .number-contact div (revealed in-page by JS, but present in HTML)
        phone_raw = ""
        phone_el = item.select_one(".number-contact")
        if phone_el:
            phone_raw = phone_el.get_text(strip=True)
            # Remove "Tél :" prefix
            phone_raw = re.sub(r"^[Tt]él\s*:\s*", "", phone_raw).strip()
        if not phone_raw:
            # Try tel: href link
            tel_link = item.select_one('a[href^="tel:"]')
            if tel_link:
                phone_raw = tel_link.get("href", "").replace("tel:", "").strip()
        if not phone_raw:
            # Try any element with phone-related class
            for cls in ["bi-phone", "phone", "contact-phone"]:
                el = item.select_one(f'[class*="{cls}"]')
                if el:
                    phone_raw = el.get_text(strip=True)
                    phone_raw = re.sub(r"^[Tt]él\s*:\s*", "", phone_raw).strip()
                    break

        # Address - inside .bi-address a tag (text content minus icon labels)
        adresse = ""
        addr_el = item.select_one(".bi-address")
        if addr_el:
            # Get the link's text content
            a_tag = addr_el.select_one("a")
            if a_tag:
                # Remove span/label children (icons and "Voir le plan")
                for span in a_tag.select("span"):
                    span.decompose()
                adresse = a_tag.get_text(separator=" ", strip=True)
            else:
                adresse = addr_el.get_text(separator=" ", strip=True)
            adresse = re.sub(r"Voir le plan", "", adresse)
            adresse = re.sub(r"\s+", " ", adresse).strip()

        # Extract postal code from address, fallback to cp param
        code_postal = extract_postal(adresse) or cp

        if nom and phone_raw:
            tel_formatted = format_phone(phone_raw)
            results.append({
                "nom": nom,
                "telephone": tel_formatted,
                "adresse": adresse,
                "code_postal": code_postal,
                "ville": ville,
                "categorie": categorie,
                "source": "PJ_fresh"
            })
        elif nom and not phone_raw:
            # Still record entries without phone (some businesses hide it)
            pass

    return results


def get_page(url: str, impersonate: str) -> tuple:
    """Fetch a page, return (html, status_code)."""
    try:
        resp = cffi_requests.get(
            url,
            headers=HEADERS,
            impersonate=impersonate,
            timeout=20,
            allow_redirects=True,
        )
        return resp.text, resp.status_code
    except Exception as e:
        print(f"  ERROR fetching {url}: {e}")
        return None, 0


def has_next_page(html: str) -> bool:
    """Check if there's a next page link."""
    soup = BeautifulSoup(html, "html.parser")
    # Look for pagination next link
    next_link = soup.select_one("a[rel='next'], .pagination-next a, a.next, li.next a")
    if next_link:
        return True
    # Check page numbering
    current = soup.select_one(".pagination .current, .pagination .active")
    if current:
        # Check if there's a higher page number
        pages = soup.select(".pagination a[href*='/page-']")
        return len(pages) > 0
    return False


def get_max_page(html: str) -> int:
    """Get maximum page number from pagination."""
    soup = BeautifulSoup(html, "html.parser")
    max_p = 1
    for a in soup.select("a[href*='/page-']"):
        href = a.get("href", "")
        m = re.search(r"/page-(\d+)", href)
        if m:
            n = int(m.group(1))
            if n > max_p:
                max_p = n
    # Also check text content of pagination links
    for a in soup.select(".pagination a, nav a"):
        try:
            n = int(a.get_text(strip=True))
            if n > max_p:
                max_p = n
        except ValueError:
            pass
    return max_p


def scrape_category(ville_slug: str, categorie: str, ville: str, cp: str) -> list:
    """Scrape all pages for a category/ville combination."""
    all_results = []
    base_url = f"https://www.pagesjaunes.fr/annuaire/{ville_slug}/{categorie}"

    print(f"\n{'='*60}")
    print(f"Scraping: {ville} | {categorie}")
    print(f"URL: {base_url}")

    imp = next(IMPERSONATES)
    html, status = get_page(base_url, imp)

    if status == 429:
        print("  [RATE LIMITED] Got 429 - STOPPING")
        return None  # Signal to stop

    if status == 0 or html is None:
        print(f"  [SKIP] Failed to fetch (status={status})")
        return all_results

    if status == 404:
        print(f"  [SKIP] 404 Not Found")
        return all_results

    print(f"  Page 1 -> HTTP {status}")

    results = parse_listing(html, ville, cp, categorie)
    all_results.extend(results)
    print(f"  Parsed {len(results)} entries from page 1 (total: {len(all_results)})")

    # Get max page
    max_page = get_max_page(html)
    print(f"  Max pages detected: {max_page}")

    time.sleep(2.5)

    for page_num in range(2, max_page + 1):
        url = f"{base_url}/page-{page_num}"
        imp = next(IMPERSONATES)

        html, status = get_page(url, imp)

        if status == 429:
            print(f"  [RATE LIMITED] Got 429 on page {page_num} - STOPPING")
            return None  # Signal to stop

        if status in (0, 404) or html is None:
            print(f"  [STOP PAGINATION] status={status} on page {page_num}")
            break

        print(f"  Page {page_num} -> HTTP {status}")
        results = parse_listing(html, ville, cp, categorie)
        all_results.extend(results)
        print(f"  Parsed {len(results)} entries (total: {len(all_results)})")

        if not results:
            print(f"  [STOP PAGINATION] No results on page {page_num}")
            break

        time.sleep(2.5)

    return all_results


def main():
    all_data = []
    rate_limited = False

    for ville_slug, categorie, ville, cp in TARGETS:
        if rate_limited:
            break

        result = scrape_category(ville_slug, categorie, ville, cp)

        if result is None:
            print("\n[STOPPED] Rate limit hit. Saving collected data...")
            rate_limited = True
        else:
            all_data.extend(result)

        # Save after each category
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(all_data, f, ensure_ascii=False, indent=2)
        print(f"\nSaved {len(all_data)} total entries to {OUTPUT_FILE}")

    print(f"\n{'='*60}")
    print(f"COMPLETE. Total entries scraped: {len(all_data)}")
    print(f"Output: {OUTPUT_FILE}")

    # Summary by category
    by_cat = {}
    for entry in all_data:
        key = f"{entry['categorie']} | {entry['ville']}"
        by_cat[key] = by_cat.get(key, 0) + 1

    print("\nBreakdown:")
    for k, v in sorted(by_cat.items()):
        print(f"  {k}: {v} entries")


if __name__ == "__main__":
    main()
