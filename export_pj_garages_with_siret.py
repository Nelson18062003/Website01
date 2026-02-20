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
    "06": "Alpes-Maritimes", "17": "Charente-Maritime", "24": "Dordogne",
    "27": "Eure", "28": "Eure-et-Loir", "30": "Gard", "31": "Haute-Garonne",
    "33": "Gironde", "35": "Ille-et-Vilaine", "38": "Isère", "40": "Landes",
    "41": "Loir-et-Cher", "42": "Loire", "44": "Loire-Atlantique",
    "45": "Loiret", "46": "Lot", "57": "Moselle", "59": "Nord",
    "60": "Oise", "62": "Pas-de-Calais", "67": "Bas-Rhin", "72": "Sarthe",
    "73": "Savoie", "76": "Seine-Maritime", "77": "Seine-et-Marne",
    "78": "Yvelines", "79": "Deux-Sèvres", "80": "Somme", "83": "Var",
    "86": "Vienne", "88": "Vosges", "91": "Essonne",
    "93": "Seine-Saint-Denis", "95": "Val-d'Oise",
    "971": "Guadeloupe", "973": "Guyane",
}

REGION_MAP = {
    "06": "Provence-Alpes-Côte d'Azur", "83": "Provence-Alpes-Côte d'Azur",
    "17": "Nouvelle-Aquitaine", "24": "Nouvelle-Aquitaine", "33": "Nouvelle-Aquitaine",
    "40": "Nouvelle-Aquitaine", "79": "Nouvelle-Aquitaine", "86": "Nouvelle-Aquitaine",
    "27": "Normandie", "76": "Normandie",
    "28": "Centre-Val de Loire", "41": "Centre-Val de Loire", "45": "Centre-Val de Loire",
    "30": "Occitanie", "31": "Occitanie", "46": "Occitanie",
    "35": "Bretagne",
    "38": "Auvergne-Rhône-Alpes", "42": "Auvergne-Rhône-Alpes", "73": "Auvergne-Rhône-Alpes",
    "44": "Pays de la Loire", "72": "Pays de la Loire",
    "57": "Grand Est", "67": "Grand Est", "88": "Grand Est",
    "59": "Hauts-de-France", "60": "Hauts-de-France", "62": "Hauts-de-France", "80": "Hauts-de-France",
    "77": "Île-de-France", "78": "Île-de-France", "91": "Île-de-France",
    "93": "Île-de-France", "95": "Île-de-France",
    "971": "Guadeloupe", "973": "Guyane",
}


# =============================================================================
# Data loading
# =============================================================================

def load_all_pj_garages():
    """Load all garages from PJ cache JSON files."""
    all_garages = []
    files = sorted(f for f in os.listdir(CACHE_DIR) if f.endswith('.json'))

    for fname in files:
        filepath = os.path.join(CACHE_DIR, fname)
        with open(filepath, "r", encoding="utf-8") as f:
            garages = json.load(f)
        # Extract dept number from filename (dept_59.json -> 59)
        dept = fname.replace("dept_", "").replace(".json", "")
        for g in garages:
            g["dept_num"] = dept
            g["dept_name"] = DEPT_NAMES.get(dept, "")
            g["region"] = REGION_MAP.get(dept, "")
        all_garages.extend(garages)
        print(f"  {fname}: {len(garages)} garages")

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
        "N°", "Nom", "Téléphone", "Téléphone (Intl)", "Adresse",
        "Code Postal", "Ville", "Département N°", "Département",
        "Région", "Activité PJ", "SIREN", "SIRET", "Nom API",
        "Code NAF", "ID Pages Jaunes", "Source",
    ]
    for col, h in enumerate(headers, 1):
        ws.cell(row=1, column=col, value=h)

    for i, g in enumerate(garages):
        row = i + 2
        ws.cell(row=row, column=1, value=i + 1)
        ws.cell(row=row, column=2, value=g.get("name", ""))
        ws.cell(row=row, column=3, value=g.get("phone", ""))
        ws.cell(row=row, column=4, value=g.get("phone_intl", ""))
        ws.cell(row=row, column=5, value=g.get("address", ""))
        ws.cell(row=row, column=6, value=g.get("postal_code", ""))
        ws.cell(row=row, column=7, value=g.get("city", ""))
        ws.cell(row=row, column=8, value=g.get("dept_num", ""))
        ws.cell(row=row, column=9, value=g.get("dept_name", ""))
        ws.cell(row=row, column=10, value=g.get("region", ""))
        ws.cell(row=row, column=11, value=g.get("activity", ""))
        ws.cell(row=row, column=12, value=g.get("siren", ""))
        ws.cell(row=row, column=13, value=g.get("siret", ""))
        ws.cell(row=row, column=14, value=g.get("nom_api", ""))
        ws.cell(row=row, column=15, value=g.get("naf", ""))
        ws.cell(row=row, column=16, value=g.get("pj_id", ""))
        ws.cell(row=row, column=17, value="Pages Jaunes")

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
