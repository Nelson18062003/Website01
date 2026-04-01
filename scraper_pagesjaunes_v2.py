#!/usr/bin/env python3
"""
Pages Jaunes scraper using curl_cffi to bypass Cloudflare protection.
Adapted from existing working scraper on claude/auto-repair-shop-scraper-PJuRs branch.
"""
import json
import time
import re
import sys
import random
from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup
from scraper_utils import (
    setup_logging, save_json, format_phone, format_postal_code
)

logger = setup_logging("pagesjaunes_v2")

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

# Medical search categories: (search_query, category_label, naf_code)
MEDICAL_CATEGORIES = [
    ("laboratoire-d-analyses-medicales", "Laboratoire d'analyses médicales", "86.90B"),
    ("hopital", "Hôpital", "86.10Z"),
    ("clinique", "Clinique privée", "86.10Z"),
    ("dentiste", "Cabinet dentaire", "86.23Z"),
    ("chirurgien-dentiste", "Cabinet dentaire", "86.23Z"),
    ("medecin-generaliste", "Cabinet médical / Médecin généraliste", "86.21Z"),
    ("medecin-specialiste", "Cabinet de médecin spécialiste", "86.22C"),
    ("centre-de-sante", "Centre de santé", "86.21Z"),
    ("maison-de-sante", "Maison de santé pluridisciplinaire", "86.21Z"),
    ("radiologue", "Centre de radiologie / Imagerie médicale", "86.22A"),
    ("centre-d-imagerie-medicale", "Centre de radiologie / Imagerie médicale", "86.22A"),
    ("kinesitherapeute", "Cabinet de kinésithérapie / Rééducation", "86.90E"),
    ("ophtalmologue", "Cabinet d'ophtalmologie", "86.22C"),
    ("dermatologue", "Cabinet de dermatologie", "86.22C"),
    ("cardiologue", "Cabinet de cardiologie", "86.22C"),
    ("gynecologue", "Cabinet de gynécologie", "86.22C"),
    ("medecine-du-travail", "Centre de médecine du travail", "86.22C"),
    ("centre-de-dialyse", "Centre de dialyse", "86.10Z"),
    ("infirmier", "Infirmier", "86.90D"),
    ("orthophoniste", "Orthophoniste", "86.90E"),
    ("sage-femme", "Sage-femme", "86.90F"),
]

# Cities to scrape with their PJ location format
CITIES = {
    "paris": [
        ("paris-75", "75000", "Paris"),
    ],
    "marseille": [
        ("marseille-13", "13000", "Marseille"),
    ],
    "lille": [
        ("lille-59", "59000", "Lille"),
        ("roubaix-59100", "59100", "Roubaix"),
        ("tourcoing-59200", "59200", "Tourcoing"),
    ],
}

MAX_PAGES = 30
DELAY_MIN = 2.5
DELAY_MAX = 5.0


def extract_json_ld(soup):
    """Extract business data from JSON-LD structured data."""
    results = []
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string or '')
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_type = item.get('@type', '')
                if item_type in ('LocalBusiness', 'MedicalBusiness', 'Dentist', 'Hospital',
                                 'Physician', 'MedicalClinic', 'Pharmacy', 'Organization',
                                 'DiagnosticLab', 'MedicalOrganization', 'HealthClub',
                                 'Optician', 'Store', 'ProfessionalService'):
                    name = item.get('name', '')
                    phone = item.get('telephone', '')
                    addr = item.get('address', {})
                    if isinstance(addr, dict):
                        street = addr.get('streetAddress', '')
                        cp = addr.get('postalCode', '')
                        city = addr.get('addressLocality', '')
                    else:
                        street, cp, city = '', '', ''
                    url = item.get('url', '')
                    if name:
                        results.append({
                            'raison_sociale': name,
                            'telephone': format_phone(phone),
                            'adresse': street,
                            'code_postal': format_postal_code(cp),
                            'ville': city,
                            'site_web': url if url and not 'pagesjaunes' in url else '',
                        })
        except Exception:
            pass
    return results


def parse_listing(article, cp_default, ville_default, category, naf_code):
    """Parse a single listing from a PJ result page."""
    record = {
        "raison_sociale": "",
        "categorie": category,
        "code_naf": naf_code,
        "libelle_naf": "",
        "telephone": "",
        "adresse": "",
        "code_postal": cp_default,
        "ville": ville_default,
        "siret": "",
        "siren": "",
        "site_web": "",
        "email": "",
        "effectif": "",
        "date_creation": "",
        "source": "Pages Jaunes",
    }

    # Business name
    name_el = article.find(attrs={"data-denomination": True})
    if name_el:
        record["raison_sociale"] = name_el.get("data-denomination", "").strip()
    if not record["raison_sociale"]:
        for sel in [".bi-denomination a", "h3.bi-title a", ".denomination a", ".bi-header-title a", "h3 a"]:
            el = article.select_one(sel)
            if el:
                record["raison_sociale"] = el.get_text(strip=True)
                break
    if not record["raison_sociale"]:
        h3 = article.find("h3")
        if h3:
            record["raison_sociale"] = h3.get_text(strip=True)

    if not record["raison_sociale"]:
        return None

    # Clean name
    record["raison_sociale"] = re.sub(r'\s+', ' ', record["raison_sociale"]).strip()

    # Phone number
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
            if el.get("href", "").startswith("tel:"):
                phone = el["href"].replace("tel:", "").strip()
                break
    # Method 3: data-phone-number attribute
    if not phone:
        phone_el = article.select_one("[data-phone-number]")
        if phone_el:
            phone = phone_el.get("data-phone-number", "")
    # Method 4: phone class elements
    if not phone:
        for el in article.find_all(class_=re.compile(r'phone|tel|numero', re.I)):
            for attr in el.attrs:
                val = el.attrs[attr]
                if isinstance(val, str) and "tel:" in val:
                    phone = val.replace("tel:", "").strip()
                    break
            if phone:
                break
            text = el.get_text(strip=True)
            if re.match(r'^[0-9\s\.\-\+]{10,}$', text):
                phone = text

    if phone:
        record["telephone"] = format_phone(phone)

    # Address
    addr_el = article.select_one(".bi-address, .address, .bi-adresse")
    if addr_el:
        addr_text = addr_el.get_text(strip=True)
        cp_match = re.search(r'(\d{5})\s*(.+?)$', addr_text)
        if cp_match:
            record["code_postal"] = format_postal_code(cp_match.group(1))
            record["ville"] = cp_match.group(2).strip()
            record["adresse"] = addr_text[:cp_match.start()].strip().rstrip(',')
        else:
            record["adresse"] = addr_text

    # Website
    for a in article.find_all("a", href=True):
        href = a.get("href", "")
        if "site-internet" in href or (a.get("class") and any("website" in c for c in a.get("class", []))):
            # PJ redirect links contain the actual URL
            record["site_web"] = href
            break

    # SIRET (sometimes visible on PJ)
    siret_match = re.search(r'(\d{14})', str(article))
    if siret_match:
        record["siret"] = siret_match.group(1)
        record["siren"] = siret_match.group(1)[:9]

    return record


def scrape_page(query, location, page):
    """Scrape a single page of PJ results using curl_cffi."""
    url = f"https://www.pagesjaunes.fr/annuaire/chercherlespros?quoiqui={query}&ou={location}&page={page}"

    try:
        r = cffi_requests.get(url, impersonate="chrome120", timeout=30)

        if r.status_code == 403:
            logger.warning(f"PJ 403 for {query}/{location} page {page}")
            return [], False
        if r.status_code == 429:
            logger.warning(f"PJ 429 rate limited, waiting 60s")
            time.sleep(60)
            return [], True  # has_next=True to retry
        if r.status_code != 200:
            logger.warning(f"PJ HTTP {r.status_code} for {query}/{location} page {page}")
            return [], False

        soup = BeautifulSoup(r.text, 'lxml')

        # Check for Cloudflare challenge
        if "challenge" in r.text.lower() and "enable javascript" in r.text.lower():
            logger.warning(f"Cloudflare challenge detected for {query}/{location}")
            return [], False

        results = []

        # Method 1: Parse listing articles
        articles = soup.select("li.bi")
        if not articles:
            articles = soup.find_all("article")

        for article in articles:
            record = parse_listing(article, "", "", "", "")
            if record:
                results.append(record)

        # Method 2: Also try JSON-LD
        json_ld_records = extract_json_ld(soup)
        # Merge JSON-LD data into existing records or add new ones
        for jl in json_ld_records:
            # Check if we already have this record
            found = False
            for r in results:
                if r["raison_sociale"] and jl["raison_sociale"] and \
                   r["raison_sociale"].upper()[:20] == jl["raison_sociale"].upper()[:20]:
                    # Enrich existing record
                    if not r["telephone"] and jl.get("telephone"):
                        r["telephone"] = jl["telephone"]
                    if not r["adresse"] and jl.get("adresse"):
                        r["adresse"] = jl["adresse"]
                    if not r["code_postal"] and jl.get("code_postal"):
                        r["code_postal"] = jl["code_postal"]
                    if not r["site_web"] and jl.get("site_web"):
                        r["site_web"] = jl["site_web"]
                    found = True
                    break
            if not found and jl.get("raison_sociale"):
                results.append({
                    "raison_sociale": jl["raison_sociale"],
                    "categorie": "", "code_naf": "", "libelle_naf": "",
                    "telephone": jl.get("telephone", ""),
                    "adresse": jl.get("adresse", ""),
                    "code_postal": jl.get("code_postal", ""),
                    "ville": jl.get("ville", ""),
                    "siret": "", "siren": "", "site_web": jl.get("site_web", ""),
                    "email": "", "effectif": "", "date_creation": "",
                    "source": "Pages Jaunes",
                })

        # Check for next page
        has_next = len(articles) >= 15 or bool(soup.select(".pagination-next a, a.next"))

        return results, has_next

    except Exception as e:
        logger.error(f"PJ error: {query}/{location} page {page}: {e}")
        return [], False


def scrape_category_city(query, location, cp_default, ville_default, category, naf_code):
    """Scrape all pages for one category in one city."""
    all_results = []
    seen_names = set()

    for page in range(1, MAX_PAGES + 1):
        records, has_next = scrape_page(query, location, page)

        new_count = 0
        for r in records:
            r["categorie"] = r.get("categorie") or category
            r["code_naf"] = r.get("code_naf") or naf_code
            r["code_postal"] = r.get("code_postal") or format_postal_code(cp_default)
            r["ville"] = r.get("ville") or ville_default
            r["source"] = "Pages Jaunes"

            # Dedup within this scrape
            dedup_key = r["raison_sociale"].upper()[:30] + "_" + (r["code_postal"] or "")
            if dedup_key not in seen_names:
                seen_names.add(dedup_key)
                all_results.append(r)
                new_count += 1

        if records:
            logger.info(f"  PJ: {query}/{location} page {page}: {new_count} new ({len(records)} raw)")

        if not has_next or not records:
            break

        delay = random.uniform(DELAY_MIN, DELAY_MAX)
        time.sleep(delay)

    return all_results


def scrape_zone(zone_name):
    """Scrape all medical categories for a zone."""
    cities = CITIES.get(zone_name, [])
    all_results = []

    for location, cp, ville in cities:
        for query, category, naf_code in MEDICAL_CATEGORIES:
            logger.info(f"PJ: {query} in {location}...")
            results = scrape_category_city(query, location, cp, ville, category, naf_code)
            all_results.extend(results)

            if results:
                logger.info(f"  => {len(results)} records for {query}/{location}")

            # Delay between categories
            time.sleep(random.uniform(3, 6))

    return all_results


def main():
    zone = sys.argv[1] if len(sys.argv) > 1 else "all"

    if zone == "all":
        zones = ["paris", "marseille", "lille"]
    else:
        zones = [zone]

    all_results = []
    for z in zones:
        logger.info(f"=== Pages Jaunes V2: Starting {z.upper()} ===")
        results = scrape_zone(z)
        all_results.extend(results)
        logger.info(f"=== PJ V2 {z.upper()}: {len(results)} results ===")

        # Save intermediate per zone
        save_json(results, f"pagesjaunes_v2_{z}.json")

    # Save combined
    if zone == "all":
        save_json(all_results, "pagesjaunes_v2_all.json")

    logger.info(f"Pages Jaunes V2 total: {len(all_results)} results")

    # Print summary
    phone_count = sum(1 for r in all_results if r.get("telephone"))
    print(f"\nPages Jaunes V2 Summary:")
    print(f"  Total: {len(all_results)}")
    print(f"  With phone: {phone_count} ({phone_count*100//max(len(all_results),1)}%)")


if __name__ == "__main__":
    main()
