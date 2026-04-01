#!/usr/bin/env python3
"""Scraper: Pages Jaunes (pagesjaunes.fr) — Mobile UA to bypass Cloudflare 403."""
import sys
import time
import re
import json
import random
import requests
from bs4 import BeautifulSoup
from scraper_utils import (
    setup_logging, save_json, format_phone, format_postal_code,
    categorize_by_naf_and_name,
)

logger = setup_logging("pagesjaunes")

# Search categories: (query, category_label, naf_code)
PJ_CATEGORIES = [
    ("laboratoire d'analyses medicales", "Laboratoire d'analyses medicales", "86.90B"),
    ("hopital", "Hopital", "86.10Z"),
    ("clinique", "Clinique privee", "86.10Z"),
    ("dentiste", "Cabinet dentaire", "86.23Z"),
    ("medecin generaliste", "Medecin generaliste", "86.21Z"),
    ("centre de sante", "Centre de sante", "86.21Z"),
    ("radiologue", "Centre de radiologie", "86.22A"),
    ("kinesitherapeute", "Kinesitherapeute", "86.90E"),
    ("ophtalmologue", "Ophtalmologue", "86.22C"),
]

CITY_NAMES = {
    "paris": ["Paris"],
    "marseille": ["Marseille"],
    "lille": ["Lille"],
}

# Mobile User-Agents (Pages Jaunes blocks desktop UAs with 403 via Cloudflare)
MOBILE_UAS = [
    (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.5 Mobile/15E148 Safari/604.1"
    ),
    (
        "Mozilla/5.0 (Linux; Android 14; SM-S928B) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Mobile Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Mobile Safari/537.36"
    ),
]

BASE_URL = "https://www.pagesjaunes.fr/annuaire/chercherlespros"
MAX_PAGES = 20
PAGE_DELAY_MIN = 4.0
PAGE_DELAY_MAX = 7.0
CATEGORY_DELAY = 8.0
RATE_LIMIT_PAUSE = 90


def create_session():
    """Create a session with mobile UA."""
    session = requests.Session()
    ua = random.choice(MOBILE_UAS)
    session.headers.update({
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9",
    })
    logger.info("Session created with UA: %s", ua[:50])
    return session


def extract_record(card):
    """Extract a business record from a PJ listing card."""
    rec = {}

    # Name from .bi-header-title (clean out tooltips)
    header = card.select_one(".bi-header-title")
    if header:
        header_soup = BeautifulSoup(str(header), "lxml")
        for el in header_soup.select(
            ".container-tootlip, .tooltip-text, .badge-mobile-sticky, .badge-desktop"
        ):
            el.decompose()
        name = header_soup.get_text(strip=True)
        name = re.sub(r"En savoir plus.*", "", name).strip()
        name = re.sub(r"Ouvrir la tooltip.*", "", name).strip()
        rec["raison_sociale"] = name

    if not rec.get("raison_sociale"):
        return None

    # Activity type
    act_el = card.select_one(".bi-activity-unit")
    if act_el:
        act_text = act_el.get_text(strip=True)
        act_text = re.sub(r"^\+\d+", "", act_text).strip()
        act_text = re.sub(r"\s+", " ", act_text)
        rec["activite_pj"] = act_text

    # Address
    addr_el = card.select_one(".bi-address")
    if addr_el:
        addr_text = addr_el.get_text(strip=True)
        rec["adresse_complete"] = addr_text
        # postal code is 5 digits, may or may not have space before city
        cp_match = re.search(r"(\d{5})\s*(.+?)$", addr_text)
        if cp_match:
            rec["code_postal"] = cp_match.group(1)
            rec["ville"] = cp_match.group(2).strip()
            rec["adresse"] = addr_text[: cp_match.start()].strip().rstrip(",")

    # Phone from data attribute
    phone_el = card.select_one("[data-phone-number]")
    if phone_el:
        rec["telephone"] = format_phone(phone_el.get("data-phone-number", ""))

    # Profile URL
    for anchor in card.select("a[href*='/pros/']"):
        href = anchor.get("href", "")
        if href:
            if not href.startswith("http"):
                href = f"https://www.pagesjaunes.fr{href}"
            rec["url_pj"] = href
            break

    # Rating
    rating_el = card.select_one(".note_moyenne")
    if rating_el:
        rec["note"] = rating_el.get_text(strip=True)

    return rec


def scrape_page(session, query, city, page):
    """Scrape one page of PJ results.

    Returns (records, total_results, has_next).
    """
    url = (
        f"{BASE_URL}?quoiqui={requests.utils.quote(query)}"
        f"&ou={requests.utils.quote(city)}&page={page}"
    )

    for attempt in range(3):
        try:
            resp = session.get(url, timeout=20)

            if resp.status_code == 403:
                wait = RATE_LIMIT_PAUSE * (attempt + 1)
                logger.warning(
                    "PJ 403 for %s/%s page %d, waiting %ds (attempt %d/3)",
                    query, city, page, wait, attempt + 1,
                )
                time.sleep(wait)
                # Switch UA
                session.headers["User-Agent"] = random.choice(MOBILE_UAS)
                continue

            if resp.status_code == 429:
                wait = RATE_LIMIT_PAUSE * (attempt + 1) + random.uniform(10, 30)
                logger.warning(
                    "PJ 429 for %s/%s page %d, waiting %ds",
                    query, city, page, int(wait),
                )
                time.sleep(wait)
                continue

            if resp.status_code != 200:
                logger.warning(
                    "PJ HTTP %d for %s/%s page %d",
                    resp.status_code, query, city, page,
                )
                return [], 0, False

            soup = BeautifulSoup(resp.text, "lxml")
            cards = soup.select("li.bi")

            if not cards:
                return [], 0, False

            records = []
            for card in cards:
                rec = extract_record(card)
                if rec:
                    records.append(rec)

            # Total results
            total = 0
            total_text = soup.get_text()
            total_match = re.search(
                r"([\d\s\xa0]+)\s*r[eé]sultat", total_text
            )
            if total_match:
                digits = re.sub(r"[^\d]", "", total_match.group(1))
                if digits:
                    total = int(digits)

            # Has next page (more pages exist if we got a full page of results)
            has_next = len(cards) >= 20

            return records, total, has_next

        except requests.exceptions.Timeout:
            logger.warning(
                "Timeout for %s/%s page %d (attempt %d/3)",
                query, city, page, attempt + 1,
            )
            time.sleep((attempt + 1) * 5)
        except Exception as exc:
            logger.error("Error %s/%s page %d: %s", query, city, page, exc)
            if attempt >= 2:
                return [], 0, False
            time.sleep((attempt + 1) * 5)

    return [], 0, False


def scrape_category_city(session, query, city, category, naf_code):
    """Scrape all pages for a query/city combination."""
    all_records = []
    seen_names = set()

    for page in range(1, MAX_PAGES + 1):
        records, total, has_next = scrape_page(session, query, city, page)

        if not records:
            break

        for rec in records:
            key = f"{rec.get('raison_sociale', '')}|{rec.get('adresse_complete', '')}"
            if key in seen_names:
                continue
            seen_names.add(key)

            rec["categorie"] = category
            rec["code_naf"] = naf_code
            rec["source"] = "Pages Jaunes"
            rec.setdefault("telephone", "")
            rec.setdefault("adresse", "")
            rec.setdefault("code_postal", "")
            rec.setdefault("ville", "")
            rec.setdefault("siret", "")
            rec.setdefault("siren", "")
            rec.setdefault("email", "")
            rec.setdefault("site_web", "")
            all_records.append(rec)

        logger.info(
            "  PJ: %s / %s page %d: %d records (total: %d)",
            query, city, page, len(records), total,
        )

        if not has_next:
            break

        delay = random.uniform(PAGE_DELAY_MIN, PAGE_DELAY_MAX)
        time.sleep(delay)

    return all_records


def scrape_zone(zone_name, session):
    """Scrape all categories for a zone."""
    cities = CITY_NAMES.get(zone_name, [])
    all_results = []

    for city in cities:
        for query, category, naf_code in PJ_CATEGORIES:
            logger.info("PJ: Scraping '%s' in %s...", query, city)
            results = scrape_category_city(session, query, city, category, naf_code)
            all_results.extend(results)
            logger.info("  => %d records", len(results))

            delay = CATEGORY_DELAY + random.uniform(0, 4)
            time.sleep(delay)

    return all_results


def main():
    zone = sys.argv[1] if len(sys.argv) > 1 else "all"

    if zone == "all":
        zones_to_scrape = ["paris", "marseille", "lille"]
    else:
        zones_to_scrape = [zone]

    session = create_session()

    for zone_name in zones_to_scrape:
        logger.info("=== Pages Jaunes: Starting %s ===", zone_name.upper())
        results = scrape_zone(zone_name, session)

        filename = f"pagesjaunes_{zone_name}.json"
        save_json(results, filename)
        logger.info(
            "=== PJ %s: %d results saved to data/%s ===",
            zone_name.upper(), len(results), filename,
        )

        if zone_name != zones_to_scrape[-1]:
            pause = 30 + random.uniform(0, 15)
            logger.info("Pausing %.0fs before next zone...", pause)
            time.sleep(pause)
            session = create_session()


if __name__ == "__main__":
    main()
