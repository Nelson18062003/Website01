#!/usr/bin/env python3
"""Scraper: Doctolib (doctolib.fr) — Medical facility listings via internal phs_proxy API."""
import sys
import time
import json
import random
import os
import requests
from scraper_utils import setup_logging, save_json, DATA_DIR

logger = setup_logging("doctolib")

API_URL = "https://www.doctolib.fr/phs_proxy/raw"

# Categories: (doctolib_slug, display_category, naf_code)
CATEGORIES = [
    ("laboratoire-d-analyses-medicales", "Laboratoire d'analyses medicales", "86.90B"),
    ("laboratoire", "Laboratoire", "86.90B"),
    ("hopital-public", "Hopital", "86.10Z"),
    ("dentiste", "Cabinet dentaire", "86.23Z"),
    ("medecin-generaliste", "Medecin generaliste", "86.21Z"),
    ("radiologue", "Radiologue", "86.22A"),
    ("masseur-kinesitherapeute", "Kinesitherapeute", "86.90E"),
    ("ophtalmologue", "Ophtalmologue", "86.22C"),
    ("clinique-privee", "Clinique privee", "86.10Z"),
    ("centre-de-sante", "Centre de sante", "86.21Z"),
]

CITIES = {
    "paris": {"name": "Paris", "gps": {"lat": 48.8575475, "lng": 2.3513765}},
    "marseille": {"name": "Marseille", "gps": {"lat": 43.2965, "lng": 5.3698}},
    "lille": {"name": "Lille", "gps": {"lat": 50.6292, "lng": 3.0573}},
}

PAGE_SIZE = 20
MAX_PAGES = 25
BASE_DELAY = 3.0
DELAY_JITTER = 2.0
INTER_CATEGORY_DELAY = 5.0
RATE_LIMIT_PAUSE = 120


def create_session():
    """Create a fresh session with cookies from a page visit."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    })
    try:
        resp = session.get(
            "https://www.doctolib.fr/medecin-generaliste/paris",
            timeout=20,
            headers={"Accept": "text/html,application/xhtml+xml"},
        )
        logger.info(
            "Session init: HTTP %d, cookies: %s",
            resp.status_code,
            list(session.cookies.keys()),
        )
    except Exception as exc:
        logger.error("Session init failed: %s", exc)
    return session


def fetch_page(session, keyword_slug, city_key, gps, page):
    """Fetch one page of results. Returns (providers, total) or (None, 0)."""
    payload = {
        "keyword": keyword_slug,
        "location": {"gpsPoint": gps},
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Referer": f"https://www.doctolib.fr/{keyword_slug}/{city_key}",
        "Origin": "https://www.doctolib.fr",
        "sec-ch-ua": '"Chromium";v="124"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
    }

    for attempt in range(3):
        try:
            resp = session.post(
                f"{API_URL}?page={page}",
                json=payload,
                timeout=30,
                headers=headers,
            )

            if resp.status_code == 200:
                ct = resp.headers.get("content-type", "")
                if "json" not in ct:
                    logger.warning(
                        "Non-JSON 200 for %s/%s page %d (possible rate limit): %s",
                        keyword_slug, city_key, page, resp.text[:80],
                    )
                    time.sleep(RATE_LIMIT_PAUSE)
                    continue
                try:
                    data = resp.json()
                except ValueError:
                    logger.warning(
                        "JSON decode error for %s/%s page %d",
                        keyword_slug, city_key, page,
                    )
                    time.sleep(15)
                    continue
                return data.get("healthcareProviders", []), data.get("total", 0)

            if resp.status_code == 429:
                wait = RATE_LIMIT_PAUSE * (attempt + 1) + random.uniform(5, 15)
                logger.warning(
                    "Rate limited (429) for %s/%s page %d, waiting %ds (attempt %d/3)",
                    keyword_slug, city_key, page, int(wait), attempt + 1,
                )
                time.sleep(wait)
                if attempt == 1:
                    try:
                        session.get(
                            "https://www.doctolib.fr/medecin-generaliste/paris",
                            timeout=20,
                            headers={"Accept": "text/html,application/xhtml+xml"},
                        )
                    except Exception:
                        pass
                continue

            if resp.status_code >= 500:
                time.sleep((attempt + 1) * 5)
                continue

            logger.warning(
                "HTTP %d for %s/%s page %d",
                resp.status_code, keyword_slug, city_key, page,
            )
            return None, 0

        except requests.exceptions.Timeout:
            logger.warning(
                "Timeout %s/%s page %d (attempt %d/3)",
                keyword_slug, city_key, page, attempt + 1,
            )
            time.sleep((attempt + 1) * 5)
        except Exception as exc:
            logger.error("Error %s/%s page %d: %s", keyword_slug, city_key, page, exc)
            if attempt >= 2:
                return None, 0
            time.sleep((attempt + 1) * 5)

    return None, 0


def parse_provider(raw, category, naf_code, city_name):
    """Convert API provider object to our record format."""
    loc = raw.get("location", {})

    parts = []
    for field in ["title", "firstName"]:
        val = raw.get(field)
        if val:
            parts.append(val)
    name = raw.get("name", "")
    if name:
        parts.append(name)
    full_name = " ".join(parts).strip()

    street = loc.get("address", "")
    zipcode = loc.get("zipcode", "")
    city = loc.get("city", "")
    addr_str = ", ".join(
        p for p in [street, f"{zipcode} {city}".strip()] if p.strip()
    )

    link = raw.get("link", "")
    if link and not link.startswith("http"):
        link = f"https://www.doctolib.fr{link}"

    org_status = raw.get("organizationStatus") or {}
    booking = raw.get("onlineBooking")

    return {
        "source": "Doctolib",
        "raison_sociale": name,
        "nom_complet": full_name,
        "prenom": raw.get("firstName", "") or "",
        "titre": raw.get("title", "") or "",
        "genre": raw.get("gender", "") or "",
        "categorie": category,
        "code_naf": naf_code,
        "adresse": street,
        "code_postal": zipcode,
        "ville": city,
        "adresse_complete": addr_str,
        "latitude": loc.get("lat"),
        "longitude": loc.get("lng"),
        "telephone": "",
        "email": "",
        "site_web": "",
        "siret": "",
        "siren": "",
        "type_structure": org_status.get("name", ""),
        "specialite_doctolib": (raw.get("speciality") or {}).get("name", ""),
        "langues": raw.get("languages", []),
        "secteur_convention": raw.get("regulationSector", "") or "",
        "rdv_en_ligne": booking is not None,
        "teleconsultation": booking.get("telehealth", False) if booking else False,
        "lien_doctolib": link,
        "doctolib_id": raw.get("id", ""),
        "ville_recherche": city_name,
    }


def scrape_category_city(session, slug, category, naf_code, city_key):
    """Scrape all pages for one category in one city."""
    city_info = CITIES[city_key]
    gps = city_info["gps"]
    city_name = city_info["name"]
    all_records = []
    seen_ids = set()

    for page in range(0, MAX_PAGES):
        providers, total = fetch_page(session, slug, city_key, gps, page)

        if providers is None:
            logger.warning("  Failed at page %d, stopping", page)
            break
        if not providers:
            break

        for prov in providers:
            prov_id = prov.get("id", "")
            if prov_id in seen_ids:
                continue
            seen_ids.add(prov_id)
            record = parse_provider(prov, category, naf_code, city_name)
            if record["raison_sociale"]:
                all_records.append(record)

        logger.info(
            "  %s/%s page %d: %d providers (total: %d)",
            slug, city_key, page, len(providers), total,
        )

        if len(providers) < PAGE_SIZE:
            break
        if total and (page + 1) * PAGE_SIZE >= total:
            break

        delay = BASE_DELAY + random.uniform(0, DELAY_JITTER)
        time.sleep(delay)

    return all_records


def main():
    """Main entry point."""
    city_arg = sys.argv[1] if len(sys.argv) > 1 else "all"

    if city_arg == "all":
        cities = list(CITIES.keys())
    elif city_arg in CITIES:
        cities = [city_arg]
    else:
        logger.error("Unknown city: %s. Available: %s", city_arg, list(CITIES.keys()))
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("Doctolib scraper starting")
    logger.info("Categories: %d, Cities: %s", len(CATEGORIES), cities)
    logger.info("=" * 60)

    grand_total = 0

    for city_key in cities:
        logger.info("=== Starting %s ===", city_key.upper())
        session = create_session()
        time.sleep(3)

        # Load existing data to merge
        filepath = os.path.join(DATA_DIR, f"doctolib_{city_key}.json")
        existing = []
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as fh:
                    existing = json.load(fh)
                logger.info("Loaded %d existing records for %s", len(existing), city_key)
            except Exception:
                existing = []

        new_records = []
        stats = {}

        for slug, category, naf_code in CATEGORIES:
            logger.info("Scraping '%s' in %s...", slug, city_key)
            records = scrape_category_city(session, slug, category, naf_code, city_key)
            new_records.extend(records)
            stats[slug] = len(records)
            logger.info("  => %d records for %s/%s", len(records), slug, city_key)

            delay = INTER_CATEGORY_DELAY + random.uniform(0, 3)
            time.sleep(delay)

        # Merge and deduplicate
        combined = existing + new_records
        seen = set()
        deduped = []
        for rec in combined:
            key = rec.get("doctolib_id", "")
            if not key:
                key = f"{rec.get('raison_sociale', '')}|{rec.get('adresse', '')}"
            if key not in seen:
                seen.add(key)
                deduped.append(rec)

        save_json(deduped, f"doctolib_{city_key}.json")
        logger.info(
            "=== %s: %d total (%d new + %d existing, deduped) => data/doctolib_%s.json ===",
            city_key.upper(), len(deduped), len(new_records), len(existing), city_key,
        )
        grand_total += len(deduped)

        # Stats
        for slug_name, count in stats.items():
            logger.info("  %s: %d", slug_name, count)

        if city_key != cities[-1]:
            pause = 30 + random.uniform(0, 10)
            logger.info("Pausing %.0fs before next city...", pause)
            time.sleep(pause)

    # Merge all city files into combined doctolib.json
    all_records = []
    seen_all = set()
    for ck in CITIES:
        fp = os.path.join(DATA_DIR, f"doctolib_{ck}.json")
        if os.path.exists(fp):
            try:
                with open(fp, "r", encoding="utf-8") as fh:
                    city_data = json.load(fh)
                for rec in city_data:
                    key = rec.get("doctolib_id", "")
                    if not key:
                        key = f"{rec.get('raison_sociale', '')}|{rec.get('adresse', '')}"
                    if key not in seen_all:
                        seen_all.add(key)
                        all_records.append(rec)
            except Exception:
                pass
    combined_path = save_json(all_records, "doctolib.json")
    logger.info(
        "Combined file: %d unique records => %s", len(all_records), combined_path
    )
    logger.info("=== GRAND TOTAL: %d records across %d cities ===", grand_total, len(cities))


if __name__ == "__main__":
    main()
