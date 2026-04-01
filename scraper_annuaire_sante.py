#!/usr/bin/env python3
"""Scraper: Annuaire Santé (annuaire.sante.fr) — Official health professionals directory."""
import sys
import time
import re
import json
import requests
from bs4 import BeautifulSoup
from scraper_utils import (
    HEADERS, setup_logging, save_json, format_phone, format_postal_code
)

logger = setup_logging("annuaire_sante")

# The annuaire.sante.fr has an API endpoint
API_BASE = "https://annuaire.sante.fr"

# Professional types to search
PROF_TYPES = [
    ("medecin", "Cabinet médical / Médecin généraliste", "86.21Z"),
    ("chirurgien-dentiste", "Cabinet dentaire", "86.23Z"),
    ("masseur-kinesitherapeute", "Cabinet de kinésithérapie / Rééducation", "86.90E"),
    ("laboratoire-de-biologie-medicale", "Laboratoire d'analyses médicales", "86.90B"),
    ("centre-de-sante", "Centre de santé", "86.21Z"),
    ("hopital", "Hôpital", "86.10Z"),
]

CITY_SEARCH = {
    "paris": {"city": "Paris", "dept": "75"},
    "marseille": {"city": "Marseille", "dept": "13"},
    "lille": {"city": "Lille", "dept": "59"},
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def search_annuaire_api(prof_type, dept, page=1):
    """Search annuaire.sante.fr for professionals."""
    # Try the JSON API endpoint
    url = f"{API_BASE}/api/ps/recherche"
    params = {
        "type": prof_type,
        "departement": dept,
        "page": page,
        "size": 50,
    }

    try:
        r = SESSION.get(url, params=params, timeout=30)
        if r.status_code == 200:
            try:
                return r.json()
            except json.JSONDecodeError:
                pass
    except Exception:
        pass

    return None


def scrape_annuaire_html(prof_type, city, page=1):
    """Scrape annuaire.sante.fr HTML pages."""
    url = f"{API_BASE}/recherche/{prof_type}/{city}/{page}"

    try:
        r = SESSION.get(url, timeout=30)
        if r.status_code != 200:
            return [], False

        soup = BeautifulSoup(r.text, 'lxml')
        results = []

        # Find professional cards
        cards = soup.select('.card-ps, .card, .result-item, .annuaire-ps-card')
        if not cards:
            cards = soup.find_all('div', class_=re.compile(r'card|result'))

        for card in cards:
            name_el = card.select_one('h2, h3, .card-title, .ps-name, .name')
            if not name_el:
                continue

            name = name_el.get_text(strip=True)
            if not name:
                continue

            record = {
                "raison_sociale": name,
                "telephone": "",
                "adresse": "",
                "code_postal": "",
                "ville": "",
            }

            # Address
            addr_el = card.select_one('.address, .adresse, .card-address')
            if addr_el:
                addr_text = addr_el.get_text(strip=True)
                cp_match = re.search(r'(\d{5})\s+(.+)', addr_text)
                if cp_match:
                    record["code_postal"] = cp_match.group(1)
                    record["ville"] = cp_match.group(2)
                    record["adresse"] = addr_text[:cp_match.start()].strip()
                else:
                    record["adresse"] = addr_text

            # Phone
            phone_el = card.select_one('.phone, .tel, [href^="tel:"]')
            if phone_el:
                record["telephone"] = format_phone(phone_el.get_text(strip=True))

            results.append(record)

        # Check for next page
        has_next = bool(soup.select('.pagination .next a, a.next-page, .page-next'))

        return results, has_next

    except Exception as e:
        logger.error(f"Annuaire santé error: {prof_type}/{city} p{page}: {e}")
        return [], False


def scrape_zone(zone_name):
    """Scrape all professional types for a zone."""
    zone_info = CITY_SEARCH.get(zone_name, {})
    city = zone_info.get("city", zone_name)
    dept = zone_info.get("dept", "")
    all_results = []

    for prof_type, category, naf_code in PROF_TYPES:
        logger.info(f"Annuaire Santé: {prof_type} in {city}...")
        page = 1
        type_results = []

        while page <= 100:
            # Try API first
            api_data = search_annuaire_api(prof_type, dept, page)
            if api_data and isinstance(api_data, dict):
                items = api_data.get("results", []) or api_data.get("data", []) or api_data.get("items", [])
                if items:
                    for item in items:
                        record = {
                            "raison_sociale": item.get("nom", "") or item.get("name", ""),
                            "categorie": category,
                            "code_naf": naf_code,
                            "libelle_naf": "",
                            "telephone": format_phone(item.get("telephone", "")),
                            "adresse": item.get("adresse", "") or item.get("address", ""),
                            "code_postal": format_postal_code(item.get("code_postal", "")),
                            "ville": item.get("ville", "") or item.get("city", ""),
                            "siret": "",
                            "siren": "",
                            "site_web": "",
                            "email": "",
                            "effectif": "",
                            "date_creation": "",
                            "source": "Annuaire Santé",
                        }
                        if record["raison_sociale"]:
                            type_results.append(record)

                    total = api_data.get("total", 0) or api_data.get("totalCount", 0)
                    if page * 50 >= total:
                        break
                    page += 1
                    time.sleep(1)
                    continue
                else:
                    break

            # Fall back to HTML scraping
            results, has_next = scrape_annuaire_html(prof_type, city, page)
            for r in results:
                r["categorie"] = category
                r["code_naf"] = naf_code
                r["libelle_naf"] = ""
                r["source"] = "Annuaire Santé"
                r.setdefault("siret", "")
                r.setdefault("siren", "")
                r.setdefault("site_web", "")
                r.setdefault("email", "")
                r.setdefault("effectif", "")
                r.setdefault("date_creation", "")
            type_results.extend(results)

            if not has_next or not results:
                break
            page += 1
            time.sleep(1.5)

        logger.info(f"  {prof_type} in {city}: {len(type_results)} results")
        all_results.extend(type_results)

    return all_results


def main():
    zone = sys.argv[1] if len(sys.argv) > 1 else "all"

    if zone == "all":
        zones = ["paris", "marseille", "lille"]
    else:
        zones = [zone]

    all_results = []
    for z in zones:
        logger.info(f"=== Annuaire Santé: {z.upper()} ===")
        results = scrape_zone(z)
        all_results.extend(results)
        logger.info(f"Annuaire Santé {z.upper()}: {len(results)} results")

    filename = f"annuaire_sante_{zone}.json"
    save_json(all_results, filename)
    logger.info(f"Saved to data/{filename}")
    return all_results


if __name__ == "__main__":
    main()
