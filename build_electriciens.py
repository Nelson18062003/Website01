#!/usr/bin/env python3
"""
Scrape Pages Jaunes for Artisans Électriciens & Entreprises d'Électricité,
enrich with SIRET, and export to formatted Excel.

Usage:
    python3 build_electriciens.py                    # Full pipeline (all departments)
    python3 build_electriciens.py scrape 69          # Scrape one department only
    python3 build_electriciens.py scrape 69 33 77    # Scrape specific departments
    python3 build_electriciens.py export             # SIRET enrichment + Excel export

Output: pagesjaunes_electriciens_france.xlsx
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
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
import requests

# =============================================================================
# Configuration
# =============================================================================

CACHE_DIR = "pagesjaunes_electriciens_cache"
SIRET_CACHE_FILE = "electriciens_siret_cache.json"
OUTPUT_FILE = "pagesjaunes_electriciens_france.xlsx"

RESULTS_PER_PAGE = 20
MAX_PAGES_PER_DEPT = 80
DELAY_BETWEEN_PAGES = 3.5
DELAY_BETWEEN_DEPTS = 8.0

API_URL = "https://recherche-entreprises.api.gouv.fr/search"
API_DELAY = 0.15

SEARCH_QUERIES = [
    "artisan électricien",
    "entreprise d'électricité",
    "électricien bâtiment",
    "installation électrique",
]

ALL_DEPTS = ["33", "69", "74", "77", "93"]

DEPT_NAMES = {
    "33": "Gironde",
    "69": "Rhône",
    "74": "Haute-Savoie",
    "77": "Seine-et-Marne",
    "93": "Seine-Saint-Denis",
}

REGION_MAP = {
    "33": "Nouvelle-Aquitaine",
    "69": "Auvergne-Rhône-Alpes",
    "74": "Auvergne-Rhône-Alpes",
    "77": "Île-de-France",
    "93": "Île-de-France",
}

_PHONE_RE = re.compile(r'(?:0[1-9])(?:\s?\d{2}){4}')


# =============================================================================
# Phone & Address parsing
# =============================================================================

def clean_phone(text):
    """Extract and clean phone number from raw text."""
    if not text:
        return ""
    text = re.sub(r'Opposé aux opérations de marketing\s*', '', text)
    text = re.sub(r'Tél\s*:\s*', '', text)
    text = text.strip()
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
    if len(digits) == 9 and not digits.startswith('0'):
        return f"+33 {digits[0]} {digits[1:3]} {digits[3:5]} {digits[5:7]} {digits[7:9]}"
    return p


def split_phones(raw):
    """Split concatenated French phone numbers and return (first, all_list)."""
    if not raw:
        return "", ""
    matches = _PHONE_RE.findall(str(raw))
    if not matches:
        return str(raw).strip(), ""
    normalized = []
    for m in matches:
        digits = m.replace(" ", "")
        formatted = " ".join(digits[i:i+2] for i in range(0, 10, 2))
        normalized.append(formatted)
    first = normalized[0]
    all_phones = " / ".join(normalized) if len(normalized) > 1 else first
    return first, all_phones


def extract_postal_city(address_text):
    """Extract postal code and city from address string."""
    if not address_text:
        return "", "", address_text or ""
    text = address_text.strip()
    match = re.search(r'(\d{5})\s+(.+?)$', text)
    if match:
        postal = match.group(1)
        city = match.group(2).strip()
        city = re.sub(r'\s*Site web\s*$', '', city).strip()
        street = text[:match.start()].strip()
        return postal, city, street
    return "", "", text


# =============================================================================
# HTML Parsing
# =============================================================================

def parse_listings(html):
    """Parse Pages Jaunes HTML and extract business listings."""
    soup = BeautifulSoup(html, 'lxml')
    listings = soup.select('li.bi')
    results = []

    for li in listings:
        name_el = li.select_one('h3')
        name = name_el.get_text(strip=True) if name_el else ''
        if not name:
            continue

        addr_el = li.select_one('.bi-address')
        addr_text = ''
        if addr_el:
            addr_text = addr_el.get_text(separator=' ', strip=True)
            addr_text = addr_text.replace('Voir le plan', '').strip()
            addr_text = re.sub(r'\s+', ' ', addr_text)

        postal_code, city, street = extract_postal_city(addr_text)

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

        activity_el = li.select_one('.bi-activity-unit')
        activity = activity_el.get_text(strip=True) if activity_el else ''

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

def _new_session():
    """Create a fresh curl_cffi session with chrome100 impersonation."""
    return curl_requests.Session(impersonate='chrome100')


def scrape_department(dept_num, session, query="artisan électricien"):
    """Scrape all pages of listings for a department."""
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
                if consecutive_errors >= 5:
                    print(f"      [WARN] 5x 403 at page {page}, stopping")
                    break
                # Exponential backoff + new session
                wait = 5 * (2 ** (consecutive_errors - 1))
                print(f"      [RETRY] 403 at page {page}, wait {wait}s (attempt {consecutive_errors}/5)")
                time.sleep(wait)
                session = _new_session()
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

            if len(listings) < RESULTS_PER_PAGE:
                break

            page += 1
            time.sleep(DELAY_BETWEEN_PAGES)

        except Exception as e:
            print(f"      [ERROR] Page {page}: {e}")
            consecutive_errors += 1
            if consecutive_errors >= 5:
                break
            time.sleep(5)
            session = _new_session()

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


# =============================================================================
# Cache
# =============================================================================

def load_scrape_cache(dept_num):
    """Load cached scrape results for a department."""
    filepath = os.path.join(CACHE_DIR, f"dept_{dept_num}.json")
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_scrape_cache(dept_num, data):
    """Save scrape results to cache."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    filepath = os.path.join(CACHE_DIR, f"dept_{dept_num}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_siret_cache():
    """Load SIRET enrichment cache."""
    if os.path.exists(SIRET_CACHE_FILE):
        try:
            with open(SIRET_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_siret_cache(cache):
    """Save SIRET enrichment cache."""
    with open(SIRET_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)


# =============================================================================
# SIRET Enrichment
# =============================================================================

def search_siret(company_name, postal_code, city):
    """Search for company SIRET/SIREN via the French government API."""
    if not company_name:
        return "", "", "", ""

    query = str(company_name).strip()
    params = {"q": query, "per_page": 5}

    if postal_code:
        pc = str(postal_code).strip()
        if pc and pc != "None":
            params["code_postal"] = pc

    try:
        resp = requests.get(API_URL, params=params, timeout=15)
        if resp.status_code == 429:
            time.sleep(3)
            resp = requests.get(API_URL, params=params, timeout=15)

        if resp.status_code == 200:
            data = resp.json()
            results = data.get("results", [])
            if results:
                best = results[0]
                siren = best.get("siren", "")
                siege = best.get("siege", {})
                siret = siege.get("siret", "")
                matched_name = best.get("nom_complet", "")
                naf = best.get("activite_principale", "")
                return siren, siret, matched_name, naf

        # Fallback: search with city
        if city and str(city).strip() != "None":
            params2 = {"q": f"{query} {city}", "per_page": 5}
            resp2 = requests.get(API_URL, params=params2, timeout=15)
            if resp2.status_code == 200:
                data2 = resp2.json()
                results2 = data2.get("results", [])
                if results2:
                    best = results2[0]
                    siren = best.get("siren", "")
                    siege = best.get("siege", {})
                    siret = siege.get("siret", "")
                    matched_name = best.get("nom_complet", "")
                    naf = best.get("activite_principale", "")
                    return siren, siret, matched_name, naf

    except requests.exceptions.RequestException as e:
        print(f"  [ERROR] API request failed: {e}")

    return "", "", "", ""


# =============================================================================
# Data loading
# =============================================================================

def load_all_data():
    """Load all electrician data from cached JSON files and add metadata."""
    all_companies = []

    for dept in sorted(ALL_DEPTS):
        cached = load_scrape_cache(dept)
        if cached is None:
            print(f"  [WARN] No cache for dept {dept} — skipping")
            continue

        dept_name = DEPT_NAMES.get(dept, dept)
        region = REGION_MAP.get(dept, "")

        for entry in cached:
            entry["dept_num"] = dept
            entry["dept_name"] = dept_name
            entry["region"] = region
            all_companies.append(entry)

        print(f"  Loaded dept {dept} ({dept_name}): {len(cached)} entreprises")

    # Global deduplication
    before = len(all_companies)
    all_companies = deduplicate_results(all_companies)
    after = len(all_companies)
    if before != after:
        print(f"  Déduplication: {before} → {after} (supprimé {before - after} doublons)")

    return all_companies


# =============================================================================
# Excel Output
# =============================================================================

def write_excel(companies, filename):
    """Write companies to a formatted Excel file."""
    print(f"\nÉcriture de {len(companies):,} entreprises dans {filename}...")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Électriciens Pages Jaunes"

    headers = [
        ("N°", 7),
        ("Nom", 45),
        ("Téléphone (International)", 28),
        ("Téléphone (Original)", 22),
        ("Adresse", 40),
        ("Code Postal", 12),
        ("Ville", 25),
        ("Département N°", 14),
        ("Département", 20),
        ("Région", 28),
        ("SIREN", 15),
        ("SIRET", 18),
        ("Nom API", 40),
        ("Code NAF", 12),
        ("ID Pages Jaunes", 16),
        ("Source", 15),
    ]

    # Styles
    header_font = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="1A5276", end_color="1A5276", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )
    data_font = Font(name="Calibri", size=10)
    data_alignment = Alignment(vertical="center", wrap_text=False)
    alt_row_fill = PatternFill(start_color="EBF5FB", end_color="EBF5FB", fill_type="solid")

    # Write headers
    for col, (header_text, width) in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header_text)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border
        ws.column_dimensions[get_column_letter(col)].width = width

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}1"

    # Sort: Department → City → Name
    companies.sort(key=lambda x: (
        x.get("dept_num", "").zfill(3),
        (x.get("city") or "").lower(),
        (x.get("name") or "").lower(),
    ))

    for idx, company in enumerate(companies, 1):
        row = idx + 1
        first_phone, all_phones = split_phones(company.get("phone", ""))
        phone_intl = format_phone_international(first_phone)

        values = [
            idx,
            company.get("name", ""),
            phone_intl,
            all_phones,
            company.get("address", ""),
            str(company.get("postal_code", "")),
            company.get("city", ""),
            company.get("dept_num", ""),
            company.get("dept_name", ""),
            company.get("region", ""),
            str(company.get("siren", "")),
            str(company.get("siret", "")),
            company.get("nom_api", ""),
            company.get("naf", ""),
            company.get("pj_id", ""),
            "Pages Jaunes",
        ]

        row_fill = alt_row_fill if idx % 2 == 0 else PatternFill(fill_type=None)

        for col, val in enumerate(values, 1):
            cell = ws.cell(row=row, column=col, value=val)
            cell.font = data_font
            cell.alignment = data_alignment
            cell.border = thin_border
            cell.fill = row_fill

        # Text format for Code Postal, SIREN, SIRET
        ws.cell(row=row, column=6).number_format = '@'
        ws.cell(row=row, column=11).number_format = '@'
        ws.cell(row=row, column=12).number_format = '@'

    # ---- Summary sheet ----
    ws_s = wb.create_sheet("Résumé")
    ws_s.column_dimensions["A"].width = 45
    ws_s.column_dimensions["B"].width = 15

    summary = [
        ("=== STATISTIQUES GÉNÉRALES ===", ""),
        ("Total entreprises Électriciens", len(companies)),
        ("Avec téléphone (international)",
         sum(1 for c in companies if format_phone_international(
             split_phones(c.get("phone", ""))[0]))),
        ("Avec SIRET", sum(1 for c in companies if c.get("siret"))),
        ("Avec SIREN", sum(1 for c in companies if c.get("siren"))),
        ("", ""),
        ("=== PAR DÉPARTEMENT ===", ""),
    ]

    dept_counts = {}
    for c in companies:
        d = f"{c.get('dept_num', '??')} - {c.get('dept_name', '??')}"
        dept_counts[d] = dept_counts.get(d, 0) + 1
    for d, count in sorted(dept_counts.items()):
        summary.append((f"  {d}", count))

    summary.extend([("", ""), ("=== PAR RÉGION ===", "")])
    region_counts = {}
    for c in companies:
        r = c.get("region") or "Inconnu"
        region_counts[r] = region_counts.get(r, 0) + 1
    for r, count in sorted(region_counts.items()):
        summary.append((f"  {r}", count))

    summary_header_font = Font(name="Calibri", bold=True, size=12, color="1A5276")
    summary_data_font = Font(name="Calibri", size=11)

    for row_idx, (label, value) in enumerate(summary, 1):
        cell_a = ws_s.cell(row=row_idx, column=1, value=label)
        if "===" in str(label):
            cell_a.font = summary_header_font
        else:
            cell_a.font = summary_data_font
        if value != "":
            cell_b = ws_s.cell(row=row_idx, column=2, value=value)
            cell_b.font = summary_data_font
            cell_b.alignment = Alignment(horizontal="right")

    wb.save(filename)
    print(f"  Fichier sauvegardé: {filename}")


# =============================================================================
# Pipeline functions
# =============================================================================

def do_scrape(dept_list):
    """Phase 1: Scrape Pages Jaunes for Electrician companies."""
    print("=" * 70)
    print("  SCRAPING PAGES JAUNES — ARTISANS ÉLECTRICIENS & ENTREPRISES D'ÉLECTRICITÉ")
    print("  (curl_cffi + Cloudflare bypass)")
    print("=" * 70)

    grand_total = 0
    grand_with_phone = 0

    for i, dept in enumerate(dept_list, 1):
        dept_name = DEPT_NAMES.get(dept, dept)

        # Check cache
        cached = load_scrape_cache(dept)
        if cached is not None:
            total = len(cached)
            with_phone = sum(1 for r in cached if r.get('phone'))
            print(f"  [{i}/{len(dept_list)}] {dept} - {dept_name}: "
                  f"{total} entreprises, {with_phone} avec tél (CACHE)")
            grand_total += total
            grand_with_phone += with_phone
            continue

        print(f"  [{i}/{len(dept_list)}] {dept} - {dept_name}...",
              end=" ", flush=True)

        # Fresh session per department to avoid stale cookies
        session = _new_session()

        all_results = []
        for q_idx, query in enumerate(SEARCH_QUERIES):
            results = scrape_department(dept, session, query=query)
            all_results.extend(results)
            if q_idx < len(SEARCH_QUERIES) - 1:
                time.sleep(DELAY_BETWEEN_PAGES)

        all_results = deduplicate_results(all_results)
        with_phone = sum(1 for r in all_results if r.get('phone'))
        print(f"{len(all_results)} entreprises, {with_phone} avec tél")

        save_scrape_cache(dept, all_results)
        grand_total += len(all_results)
        grand_with_phone += with_phone

        if i < len(dept_list):
            time.sleep(DELAY_BETWEEN_DEPTS)

    print(f"\n  Total: {grand_total:,} entreprises, {grand_with_phone:,} avec tél")


def do_export():
    """Phase 2+3: SIRET enrichment + Excel export."""
    print("=" * 70)
    print("  EXPORT ÉLECTRICIENS → EXCEL + SIRET")
    print("=" * 70)

    # Load all cached data
    print("\nChargement des données...")
    companies = load_all_data()
    total = len(companies)

    if total == 0:
        print("ERREUR: Aucune donnée trouvée. Lancez d'abord le scraping.")
        sys.exit(1)

    # SIRET enrichment
    print(f"\nEnrichissement SIRET ({total} entreprises)...")
    cache = load_siret_cache()
    print(f"  Cache SIRET: {len(cache)} entrées existantes")

    found_count = 0
    not_found_count = 0

    for i, company in enumerate(companies):
        name = company.get("name", "")
        postal_code = company.get("postal_code", "")
        city = company.get("city", "")
        cache_key = f"{name}|{postal_code}|{city}"

        if cache_key in cache:
            siren, siret, matched_name, naf = cache[cache_key]
        else:
            siren, siret, matched_name, naf = search_siret(name, postal_code, city)
            cache[cache_key] = [siren, siret, matched_name, naf]
            time.sleep(API_DELAY)

        company["siren"] = siren
        company["siret"] = siret
        company["nom_api"] = matched_name
        company["naf"] = naf

        if siren:
            found_count += 1
        else:
            not_found_count += 1

        current = i + 1
        if current % 100 == 0 or current == total:
            pct = current / total * 100
            print(f"  [{current:>5}/{total}] ({pct:5.1f}%) | "
                  f"SIRET trouvé: {found_count} | Non trouvé: {not_found_count}")
            save_siret_cache(cache)

    save_siret_cache(cache)

    # Excel generation
    print(f"\nGénération Excel...")
    write_excel(companies, OUTPUT_FILE)

    # Summary
    with_phone = sum(1 for c in companies if c.get("phone"))
    print(f"\n{'=' * 70}")
    print(f"  RÉSUMÉ")
    print(f"{'=' * 70}")
    print(f"  Total entreprises Électriciens: {total:,}")
    print(f"  Avec téléphone:                 {with_phone:,} ({100*with_phone/total:.1f}%)")
    print(f"  SIRET trouvé:                   {found_count:,} ({100*found_count/total:.1f}%)")
    print(f"  SIRET non trouvé:               {not_found_count:,}")
    print(f"  Fichier:                         {OUTPUT_FILE}")
    print(f"\nTerminé!")


# =============================================================================
# Main
# =============================================================================

def main():
    args = sys.argv[1:]

    if not args:
        # Full pipeline
        do_scrape(ALL_DEPTS)
        do_export()

    elif args[0] == "scrape":
        dept_list = args[1:] if len(args) > 1 else ALL_DEPTS
        invalid = [d for d in dept_list if d not in ALL_DEPTS]
        if invalid:
            print(f"ERREUR: Départements inconnus: {invalid}")
            print(f"Valides: {ALL_DEPTS}")
            sys.exit(1)
        do_scrape(dept_list)

    elif args[0] == "export":
        do_export()

    else:
        print("Usage:")
        print("  python3 build_electriciens.py              # Pipeline complet")
        print("  python3 build_electriciens.py scrape 69     # Scrape dept 69")
        print("  python3 build_electriciens.py export        # Export Excel + SIRET")
        sys.exit(1)


if __name__ == "__main__":
    main()
