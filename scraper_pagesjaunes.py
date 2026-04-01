#!/usr/bin/env python3
"""Scraper: Pages Jaunes (pagesjaunes.fr) — Heavy scraping with pagination."""
import sys
import time
import re
import json
import requests
from bs4 import BeautifulSoup
from scraper_utils import (
    ZONES, HEADERS, setup_logging, save_json, format_phone, format_postal_code,
    categorize_by_naf_and_name, safe_request
)

logger = setup_logging("pagesjaunes")

# Search categories for Pages Jaunes
PJ_CATEGORIES = [
    ("laboratoire d'analyses médicales", "Laboratoire d'analyses médicales", "86.90B"),
    ("hopital", "Hôpital", "86.10Z"),
    ("clinique", "Clinique privée", "86.10Z"),
    ("cabinet dentaire", "Cabinet dentaire", "86.23Z"),
    ("dentiste", "Cabinet dentaire", "86.23Z"),
    ("medecin generaliste", "Cabinet médical / Médecin généraliste", "86.21Z"),
    ("medecin specialiste", "Cabinet de médecin spécialiste", "86.22C"),
    ("cabinet medical", "Cabinet médical / Médecin généraliste", "86.21Z"),
    ("centre de sante", "Centre de santé", "86.21Z"),
    ("maison de sante", "Maison de santé pluridisciplinaire", "86.21Z"),
    ("centre de radiologie", "Centre de radiologie / Imagerie médicale", "86.22A"),
    ("imagerie medicale", "Centre de radiologie / Imagerie médicale", "86.22A"),
    ("centre de dialyse", "Centre de dialyse", "86.10Z"),
    ("kinesitherapeute", "Cabinet de kinésithérapie / Rééducation", "86.90E"),
    ("ophtalmologue", "Cabinet d'ophtalmologie", "86.22C"),
    ("ophtalmologiste", "Cabinet d'ophtalmologie", "86.22C"),
    ("dermatologue", "Cabinet de dermatologie", "86.22C"),
    ("cardiologue", "Cabinet de cardiologie", "86.22C"),
    ("gynecologue", "Cabinet de gynécologie", "86.22C"),
    ("medecine du travail", "Centre de médecine du travail", "86.22C"),
    ("centre de vaccination", "Centre de vaccination", "86.90F"),
]

# City names for Pages Jaunes search
CITY_NAMES = {
    "paris": ["Paris"],
    "marseille": ["Marseille"],
    "lille": ["Lille", "Roubaix", "Tourcoing", "Villeneuve-d'Ascq", "Lambersart", "La Madeleine"],
}

BASE_URL = "https://www.pagesjaunes.fr/annuaire/chercherlespros"
DETAIL_BASE = "https://www.pagesjaunes.fr"

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def scrape_pj_page(query, city, page=1):
    """Scrape a single page of Pages Jaunes results."""
    params = {
        "quoiqui": query,
        "ou": city,
        "page": page,
    }

    url = f"https://www.pagesjaunes.fr/annuaire/chercherlespros?quoiqui={requests.utils.quote(query)}&ou={requests.utils.quote(city)}&page={page}"

    try:
        r = SESSION.get(url, timeout=30)
        if r.status_code == 403:
            logger.warning(f"PJ blocked (403) for {query} in {city} page {page}")
            return [], False
        if r.status_code != 200:
            logger.warning(f"PJ HTTP {r.status_code} for {query} in {city} page {page}")
            return [], False

        soup = BeautifulSoup(r.text, 'lxml')
        results = []

        # Find business listings
        listings = soup.select('.bi-bloc, .bi-content, .bi-header-title, [data-pjax]')
        if not listings:
            listings = soup.find_all('div', class_=re.compile(r'bi-'))

        # Try different selectors for business cards
        cards = soup.select('li.bi, .bi-bloc, article.bi')
        if not cards:
            cards = soup.find_all(['li', 'article', 'div'], class_=re.compile(r'^bi[\s-]'))

        for card in cards:
            record = extract_pj_record(card)
            if record and record.get("raison_sociale"):
                results.append(record)

        # Check if there's a next page
        has_next = bool(soup.select('.pagination-next a, a.next, .link_pagination.next'))
        if not has_next:
            # Also check if there are page numbers higher than current
            page_links = soup.select('.pagination a, .pagination-page a')
            for pl in page_links:
                try:
                    pnum = int(pl.get_text(strip=True))
                    if pnum > page:
                        has_next = True
                        break
                except (ValueError, TypeError):
                    pass

        return results, has_next

    except Exception as e:
        logger.error(f"PJ error: {query} in {city} page {page}: {e}")
        return [], False


def extract_pj_record(card):
    """Extract a business record from a Pages Jaunes card element."""
    record = {}

    # Name
    name_el = card.select_one('.bi-denomination, .bi-header-title a, h2 a, h3 a, .denomination-links a')
    if name_el:
        record["raison_sociale"] = name_el.get_text(strip=True)
    else:
        name_el = card.find(['h2', 'h3', 'span'], class_=re.compile(r'denom|name|title'))
        if name_el:
            record["raison_sociale"] = name_el.get_text(strip=True)

    if not record.get("raison_sociale"):
        return None

    # Address
    addr_el = card.select_one('.bi-address, .bi-adresse, .address, .adresse')
    if addr_el:
        full_addr = addr_el.get_text(strip=True)
        record["adresse_complete"] = full_addr
        # Try to extract postal code and city
        cp_match = re.search(r'(\d{5})\s+(.+?)$', full_addr)
        if cp_match:
            record["code_postal"] = cp_match.group(1)
            record["ville"] = cp_match.group(2).strip()
            record["adresse"] = full_addr[:cp_match.start()].strip().rstrip(',')
        else:
            record["adresse"] = full_addr

    # Phone
    phone_el = card.select_one('.bi-phone .phone-number, .number-phone, .tel, [data-phone]')
    if phone_el:
        record["telephone"] = format_phone(phone_el.get_text(strip=True))
    else:
        phone_el = card.find(string=re.compile(r'0[1-9]\s?\d{2}\s?\d{2}\s?\d{2}\s?\d{2}'))
        if phone_el:
            phone_match = re.search(r'(0[1-9]\s?\d{2}\s?\d{2}\s?\d{2}\s?\d{2})', phone_el)
            if phone_match:
                record["telephone"] = format_phone(phone_match.group(1))

    # Website
    web_el = card.select_one('a.bi-website, a[data-pjax-href*="site-internet"], .bi-site-internet a')
    if web_el:
        href = web_el.get('href', '')
        if href and not href.startswith('/'):
            record["site_web"] = href

    # SIRET (sometimes displayed)
    siret_el = card.find(string=re.compile(r'SIRET|siret'))
    if siret_el:
        siret_match = re.search(r'(\d{14})', str(siret_el.parent) if siret_el.parent else str(siret_el))
        if siret_match:
            record["siret"] = siret_match.group(1)

    return record


def scrape_category_city(query, city, category, naf_code, max_pages=50):
    """Scrape all pages for a query+city combination."""
    all_results = []
    page = 1
    consecutive_empty = 0

    while page <= max_pages:
        results, has_next = scrape_pj_page(query, city, page)

        if results:
            for r in results:
                r["categorie"] = r.get("categorie", category)
                r["code_naf"] = r.get("code_naf", naf_code)
                r["libelle_naf"] = ""
                r["source"] = "Pages Jaunes"
                r.setdefault("siret", "")
                r.setdefault("siren", "")
                r.setdefault("telephone", "")
                r.setdefault("email", "")
                r.setdefault("site_web", "")
                r.setdefault("effectif", "")
                r.setdefault("date_creation", "")
            all_results.extend(results)
            consecutive_empty = 0
            logger.info(f"  PJ: {query} / {city} page {page}: {len(results)} results")
        else:
            consecutive_empty += 1
            if consecutive_empty >= 2 or not has_next:
                break

        if not has_next:
            break

        page += 1
        # Respectful delay
        time.sleep(2.0 + (page % 3) * 0.5)

    return all_results


def scrape_zone(zone_name):
    """Scrape all categories for a given zone."""
    cities = CITY_NAMES.get(zone_name, [])
    all_results = []

    for city in cities:
        for query, category, naf_code in PJ_CATEGORIES:
            logger.info(f"PJ: Scraping '{query}' in {city}...")
            results = scrape_category_city(query, city, category, naf_code)
            all_results.extend(results)
            time.sleep(1.5)

    return all_results


def main():
    zone = sys.argv[1] if len(sys.argv) > 1 else "all"

    if zone == "all":
        zones_to_scrape = ["paris", "marseille", "lille"]
    else:
        zones_to_scrape = [zone]

    all_results = []
    for z in zones_to_scrape:
        logger.info(f"=== Pages Jaunes: Starting {z.upper()} ===")
        results = scrape_zone(z)
        all_results.extend(results)
        logger.info(f"=== Pages Jaunes {z.upper()}: {len(results)} results ===")

    filename = f"pagesjaunes_{zone}.json"
    save_json(all_results, filename)
    logger.info(f"Pages Jaunes ({zone}): {len(all_results)} total results saved to data/{filename}")
    return all_results


if __name__ == "__main__":
    main()
