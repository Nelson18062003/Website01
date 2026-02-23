#!/usr/bin/env python3
"""
Export all Pages Jaunes scraped garages to Excel with SIRET enrichment.

Loads the 24,223 garages from pagesjaunes_garages_cache/ JSON files,
queries the French government API for SIRET/SIREN, and exports to Excel.

Uses a persistent cache (pj_garages_siret_cache.json) so the process
can be interrupted and resumed without re-querying the API.

Usage:
    python3 export_pj_garages_with_siret.py
"""

import json
import os
import re
import sys
import time

import openpyxl
import requests

# =============================================================================
# Configuration
# =============================================================================

CACHE_DIR = "pagesjaunes_garages_cache"
SIRET_CACHE_FILE = "pj_garages_siret_cache.json"
OUTPUT_FILE = "pagesjaunes_garages_france.xlsx"

API_URL = "https://recherche-entreprises.api.gouv.fr/search"
API_DELAY = 0.15  # seconds between API calls

DEPT_NAMES = {
    "01": "Ain", "04": "Alpes-de-Haute-Provence", "13": "Bouches-du-Rhône",
    "14": "Calvados", "16": "Charente", "21": "Côte-d'Or",
    "22": "Côtes-d'Armor", "23": "Creuse", "25": "Doubs", "26": "Drôme",
    "27": "Eure", "28": "Eure-et-Loir", "29": "Finistère",
    "2B": "Haute-Corse", "30": "Gard", "31": "Haute-Garonne",
    "32": "Gers", "33": "Gironde", "34": "Hérault",
    "35": "Ille-et-Vilaine", "37": "Indre-et-Loire", "38": "Isère",
    "39": "Jura", "42": "Loire", "44": "Loire-Atlantique",
    "45": "Loiret", "46": "Lot", "49": "Maine-et-Loire",
    "50": "Manche", "53": "Mayenne", "56": "Morbihan", "57": "Moselle",
    "59": "Nord", "60": "Oise", "61": "Orne", "62": "Pas-de-Calais",
    "64": "Pyrénées-Atlantiques", "65": "Hautes-Pyrénées",
    "66": "Pyrénées-Orientales", "67": "Bas-Rhin", "68": "Haut-Rhin",
    "69": "Rhône", "70": "Haute-Saône", "71": "Saône-et-Loire",
    "73": "Savoie", "74": "Haute-Savoie", "75": "Paris",
    "76": "Seine-Maritime", "77": "Seine-et-Marne", "80": "Somme",
    "83": "Var", "85": "Vendée", "87": "Haute-Vienne", "88": "Vosges",
    "91": "Essonne", "92": "Hauts-de-Seine", "93": "Seine-Saint-Denis",
    "94": "Val-de-Marne", "95": "Val-d'Oise",
}

REGION_MAP = {
    "01": "Auvergne-Rhône-Alpes",
    "04": "Provence-Alpes-Côte d'Azur", "13": "Provence-Alpes-Côte d'Azur",
    "14": "Normandie", "27": "Normandie", "50": "Normandie", "61": "Normandie",
    "16": "Nouvelle-Aquitaine", "23": "Nouvelle-Aquitaine",
    "33": "Nouvelle-Aquitaine", "64": "Nouvelle-Aquitaine",
    "87": "Nouvelle-Aquitaine",
    "21": "Bourgogne-Franche-Comté", "25": "Bourgogne-Franche-Comté",
    "39": "Bourgogne-Franche-Comté", "70": "Bourgogne-Franche-Comté",
    "71": "Bourgogne-Franche-Comté",
    "22": "Bretagne", "29": "Bretagne", "35": "Bretagne", "56": "Bretagne",
    "2B": "Corse",
    "28": "Centre-Val de Loire", "37": "Centre-Val de Loire",
    "45": "Centre-Val de Loire",
    "30": "Occitanie", "31": "Occitanie", "32": "Occitanie",
    "34": "Occitanie", "46": "Occitanie", "65": "Occitanie",
    "66": "Occitanie",
    "26": "Auvergne-Rhône-Alpes", "38": "Auvergne-Rhône-Alpes",
    "42": "Auvergne-Rhône-Alpes", "69": "Auvergne-Rhône-Alpes",
    "73": "Auvergne-Rhône-Alpes", "74": "Auvergne-Rhône-Alpes",
    "44": "Pays de la Loire", "49": "Pays de la Loire",
    "53": "Pays de la Loire", "72": "Pays de la Loire",
    "85": "Pays de la Loire",
    "57": "Grand Est", "67": "Grand Est", "68": "Grand Est", "88": "Grand Est",
    "59": "Hauts-de-France", "60": "Hauts-de-France",
    "62": "Hauts-de-France", "80": "Hauts-de-France",
    "75": "Île-de-France", "77": "Île-de-France", "91": "Île-de-France",
    "92": "Île-de-France", "93": "Île-de-France",
    "94": "Île-de-France", "95": "Île-de-France",
    "76": "Normandie", "83": "Provence-Alpes-Côte d'Azur",
}

# Zones — seuls ces départements figurent dans le fichier final
TOP_ZONE_DEPTS = {"13", "30", "31", "33", "34", "35", "59", "60", "69", "74", "77", "91", "93", "95"}
MIDDLE_ZONE_DEPTS = {
    "01", "04", "14", "16", "21", "22", "23", "25", "26", "27", "28", "29",
    "2B", "32", "37", "38", "39", "42", "44", "45", "46", "49", "50", "53",
    "56", "57", "61", "62", "64", "65", "66", "67", "68", "70", "71", "73",
    "75", "76", "80", "83", "85", "87", "88", "92", "94",
}
ZONE_DEPTS = TOP_ZONE_DEPTS | MIDDLE_ZONE_DEPTS


def get_zone(dept):
    if dept in TOP_ZONE_DEPTS:
        return "Top Zone"
    if dept in MIDDLE_ZONE_DEPTS:
        return "Middle Zone"
    return ""


# =============================================================================
# Phone number cleaning
# =============================================================================

_PHONE_RE = re.compile(r'(?:0[1-9])(?:\s?\d{2}){4}')


def split_phones(raw):
    """Split concatenated French phone numbers and return (first, all_list)."""
    if not raw:
        return "", ""
    matches = _PHONE_RE.findall(str(raw))
    if not matches:
        return str(raw).strip(), ""
    # Normalize spacing: XX XX XX XX XX
    normalized = []
    for m in matches:
        digits = m.replace(" ", "")
        formatted = " ".join(digits[i:i+2] for i in range(0, 10, 2))
        normalized.append(formatted)
    first = normalized[0]
    all_phones = " / ".join(normalized) if len(normalized) > 1 else first
    return first, all_phones


def format_phone_international(phone):
    """Convert French phone (0X XX XX XX XX) to international +33 format."""
    if not phone:
        return ""
    p = str(phone).strip()
    # Take only first number if multiple separated by / or ,
    for sep in ["/", ","]:
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


# =============================================================================
# Data loading
# =============================================================================

def load_all_pj_garages():
    """Load garages from PJ cache JSON files — zones uniquement."""
    all_garages = []
    files = sorted(f for f in os.listdir(CACHE_DIR) if f.endswith('.json'))
    skipped = 0

    for fname in files:
        dept = fname.replace("dept_", "").replace(".json", "")
        if dept not in ZONE_DEPTS:
            skipped += 1
            continue
        filepath = os.path.join(CACHE_DIR, fname)
        with open(filepath, "r", encoding="utf-8") as f:
            garages = json.load(f)
        for g in garages:
            g["dept_num"] = dept
            g["dept_name"] = DEPT_NAMES.get(dept, "")
            g["region"] = REGION_MAP.get(dept, "")
            g["zone"] = get_zone(dept)
        all_garages.extend(garages)
        print(f"  {fname}: {len(garages)} garages ({get_zone(dept)})")

    if skipped:
        print(f"  ({skipped} fichiers hors-zones ignorés)")
    return all_garages


# =============================================================================
# SIRET lookup
# =============================================================================

def search_siret(company_name, postal_code, city):
    """Search for company SIRET/SIREN via the French government API."""
    if not company_name:
        return "", "", "", ""

    query = str(company_name).strip()
    # Clean up common PJ name patterns
    query = re.sub(r'\s*\(.*?\)\s*', ' ', query).strip()

    params = {
        "q": query,
        "per_page": 5,
    }

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

        # Fallback: search with city in query
        if city and str(city).strip() not in ("", "None"):
            params2 = {
                "q": f"{query} {city}",
                "per_page": 5,
            }
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
        print(f"  [ERROR] API request failed for '{company_name}': {e}")

    return "", "", "", ""


def load_siret_cache():
    """Load SIRET cache for resume capability."""
    if os.path.exists(SIRET_CACHE_FILE):
        with open(SIRET_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_siret_cache(cache):
    """Save SIRET cache to disk."""
    with open(SIRET_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)


# =============================================================================
# Main
# =============================================================================

def main():
    print("=" * 70)
    print("  EXPORT GARAGES PAGES JAUNES → EXCEL + SIRET")
    print("=" * 70)

    # Load all PJ garages
    print(f"\nLoading garages from {CACHE_DIR}/...")
    garages = load_all_pj_garages()
    total = len(garages)
    with_phone = sum(1 for g in garages if g.get("phone"))
    print(f"\nTotal: {total} garages, {with_phone} avec téléphone ({100*with_phone/total:.1f}%)")

    # Load SIRET cache
    cache = load_siret_cache()
    print(f"SIRET cache: {len(cache)} entries")

    # Enrich with SIRET
    print(f"\nRecherche SIRET via API gouvernementale...")
    print(f"  (estimé ~{(total - len(cache)) * API_DELAY / 60:.0f} min pour {total - len(cache)} requêtes restantes)\n")

    found_count = 0
    not_found_count = 0
    cached_count = 0

    for i, g in enumerate(garages):
        name = g.get("name", "")
        postal = g.get("postal_code", "")
        city = g.get("city", "")
        cache_key = f"{name}|{postal}|{city}"

        if cache_key in cache:
            siren, siret, matched_name, naf = cache[cache_key]
            cached_count += 1
        else:
            siren, siret, matched_name, naf = search_siret(name, postal, city)
            cache[cache_key] = [siren, siret, matched_name, naf]
            time.sleep(API_DELAY)

        g["siren"] = siren
        g["siret"] = siret
        g["nom_api"] = matched_name
        g["naf"] = naf

        if siren:
            found_count += 1
        else:
            not_found_count += 1

        current = i + 1
        if current % 100 == 0 or current == total:
            pct = 100 * current / total
            print(f"  [{current:>6}/{total}] ({pct:5.1f}%) | "
                  f"SIRET trouvé: {found_count} | Non trouvé: {not_found_count} | "
                  f"Cache: {cached_count}")
            save_siret_cache(cache)

    # Final cache save
    save_siret_cache(cache)

    # Export to Excel
    print(f"\nCréation du fichier Excel: {OUTPUT_FILE}...")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Garages Pages Jaunes"

    headers = [
        "N°", "Nom", "Téléphone (International)", "Téléphone (Original)", "Adresse",
        "Code Postal", "Ville", "Département N°", "Département",
        "Région", "Zone", "Activité PJ", "SIREN", "SIRET", "Nom API",
        "Code NAF", "ID Pages Jaunes", "Source",
    ]
    for col, h in enumerate(headers, 1):
        ws.cell(row=1, column=col, value=h)

    for i, g in enumerate(garages):
        row = i + 2
        first_phone, all_phones = split_phones(g.get("phone", ""))
        phone_intl = format_phone_international(first_phone)
        ws.cell(row=row, column=1, value=i + 1)
        ws.cell(row=row, column=2, value=g.get("name", ""))
        ws.cell(row=row, column=3, value=phone_intl)
        ws.cell(row=row, column=4, value=all_phones)
        ws.cell(row=row, column=5, value=g.get("address", ""))
        c6 = ws.cell(row=row, column=6, value=str(g.get("postal_code", "")))
        c6.number_format = '@'
        ws.cell(row=row, column=7, value=g.get("city", ""))
        ws.cell(row=row, column=8, value=g.get("dept_num", ""))
        ws.cell(row=row, column=9, value=g.get("dept_name", ""))
        ws.cell(row=row, column=10, value=g.get("region", ""))
        ws.cell(row=row, column=11, value=g.get("zone", ""))
        ws.cell(row=row, column=12, value=g.get("activity", ""))
        c13 = ws.cell(row=row, column=13, value=str(g.get("siren", "")))
        c13.number_format = '@'
        c14 = ws.cell(row=row, column=14, value=str(g.get("siret", "")))
        c14.number_format = '@'
        ws.cell(row=row, column=15, value=g.get("nom_api", ""))
        ws.cell(row=row, column=16, value=g.get("naf", ""))
        ws.cell(row=row, column=17, value=g.get("pj_id", ""))
        ws.cell(row=row, column=18, value="Pages Jaunes")

    wb.save(OUTPUT_FILE)

    # Summary
    print(f"\n{'=' * 70}")
    print(f"  RÉSUMÉ")
    print(f"{'=' * 70}")
    print(f"  Total garages:              {total:,}")
    print(f"  Avec téléphone:             {with_phone:,} ({100*with_phone/total:.1f}%)")
    print(f"  SIRET trouvé:               {found_count:,} ({100*found_count/total:.1f}%)")
    print(f"  SIRET non trouvé:           {not_found_count:,}")
    print(f"  Fichier:                    {OUTPUT_FILE}")
    print(f"\nTerminé!")


if __name__ == "__main__":
    main()
