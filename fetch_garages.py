#!/usr/bin/env python3
"""Fetch garage/auto repair legal data from the French government API."""

import json
import time
import urllib.request
import urllib.parse
import ssl

OUTPUT_FILE = "/home/user/Website01/scrape_environs_legal.json"

# Queries to run: (search_term, naf_code, department)
QUERIES = [
    # Department 54 - Meurthe-et-Moselle (Nancy)
    ("garage", "45.20A", "54"),
    ("garage", "45.11Z", "54"),
    ("garage", "45.20B", "54"),
    ("réparation automobile", "45.20A", "54"),
    ("réparation automobile", "45.20B", "54"),
    ("carrosserie", "45.20A", "54"),
    ("mécanique automobile", "45.20A", "54"),
    # Department 57 - Moselle (voisin Nancy, 15 km)
    ("garage", "45.20A", "57"),
    ("garage", "45.20B", "57"),
    ("réparation automobile", "45.20A", "57"),
    # Department 88 - Vosges (voisin Nancy, 15 km)
    ("garage", "45.20A", "88"),
    ("réparation automobile", "45.20A", "88"),
    # Department 55 - Meuse (voisin Nancy, 15 km)
    ("garage", "45.20A", "55"),
    # Department 93 - Seine-Saint-Denis (Saint-Denis)
    ("garage", "45.20A", "93"),
    ("garage", "45.11Z", "93"),
    ("garage", "45.20B", "93"),
    ("réparation automobile", "45.20A", "93"),
    ("réparation automobile", "45.20B", "93"),
    ("carrosserie", "45.20A", "93"),
    ("mécanique automobile", "45.20A", "93"),
    # Department 75 - Paris (voisin Saint-Denis, 15 km)
    ("garage", "45.20A", "75"),
    ("garage", "45.20B", "75"),
    ("réparation automobile", "45.20A", "75"),
    # Department 92 - Hauts-de-Seine (voisin Saint-Denis, 15 km)
    ("garage", "45.20A", "92"),
    ("réparation automobile", "45.20A", "92"),
    # Department 94 - Val-de-Marne (voisin Saint-Denis, 15 km)
    ("garage", "45.20A", "94"),
    ("réparation automobile", "45.20A", "94"),
    # Department 95 - Val-d'Oise (voisin Saint-Denis, 15 km)
    ("garage", "45.20A", "95"),
    ("réparation automobile", "45.20A", "95"),
    # Department 77 - Seine-et-Marne (voisin Saint-Denis, 15 km)
    ("garage", "45.20A", "77"),
]

# Also search without specific NAF to get broader results
BROAD_QUERIES = [
    ("garage automobile", "54"),
    ("réparation automobile", "54"),
    ("entretien automobile", "54"),
    ("garage automobile", "57"),
    ("garage automobile", "88"),
    ("garage automobile", "93"),
    ("réparation automobile", "93"),
    ("entretien automobile", "93"),
    ("garage automobile", "75"),
    ("garage automobile", "92"),
    ("garage automobile", "94"),
    ("garage automobile", "95"),
]

def fetch_url(url, max_retries=5):
    """Fetch JSON data from URL with retry logic."""
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 5 * (attempt + 1)
                print(f"  Rate limited (attempt {attempt+1}), waiting {wait}s...")
                time.sleep(wait)
                continue
            print(f"  HTTP Error {e.code}: {e.reason}")
            return None
        except Exception as e:
            print(f"  Error: {e}")
            return None
    print(f"  Max retries exceeded for {url}")
    return None


def extract_enterprises(data):
    """Extract enterprise info from API response."""
    results = []
    if not data or "results" not in data:
        return results

    for ent in data["results"]:
        siege = ent.get("siege", {})

        # Extract directors
        dirigeants = ent.get("dirigeants", [])
        director_parts = []
        for d in dirigeants:
            nom = d.get("nom", "")
            prenom = d.get("prenom", "")
            qualite = d.get("qualite", "")
            if nom:
                name = f"{prenom} {nom}".strip()
                if qualite:
                    name += f" ({qualite})"
                director_parts.append(name)
        director = "; ".join(director_parts) if director_parts else ""

        # Build address
        adresse = siege.get("adresse", "") or ""
        code_postal = siege.get("code_postal", "") or ""
        commune = siege.get("libelle_commune", "") or siege.get("commune", "") or ""

        # Status
        etat = ent.get("etat_administratif", "")
        status = "Active" if etat == "A" else "Radiée" if etat == "C" else etat

        # Effectif
        effectif = ent.get("tranche_effectif_salarie", "") or siege.get("tranche_effectif_salarie", "") or ""

        record = {
            "name": ent.get("nom_complet", "") or ent.get("nom_raison_sociale", ""),
            "siren": ent.get("siren", ""),
            "siret": siege.get("siret", ""),
            "address": adresse,
            "postal_code": code_postal,
            "city": commune,
            "naf_code": ent.get("activite_principale", "") or siege.get("activite_principale", ""),
            "director": director,
            "creation_date": ent.get("date_creation", ""),
            "status": status,
            "employees": effectif,
            "source": "API Gouv"
        }
        results.append(record)

    return results


def main():
    all_enterprises = {}  # keyed by SIREN to deduplicate
    total_fetched = 0

    # NAF-specific queries
    for q, naf, dept in QUERIES:
        page = 1
        while True:
            encoded_q = urllib.parse.quote(q)
            url = f"https://recherche-entreprises.api.gouv.fr/search?q={encoded_q}&activite_principale={naf}&departement={dept}&page={page}&per_page=25"
            print(f"Fetching: q={q}, naf={naf}, dept={dept}, page={page}")
            data = fetch_url(url)
            if not data:
                break

            enterprises = extract_enterprises(data)
            if not enterprises:
                break

            for ent in enterprises:
                siren = ent["siren"]
                if siren and siren not in all_enterprises:
                    all_enterprises[siren] = ent
                    total_fetched += 1

            total_results = data.get("total_results", 0)
            total_pages = data.get("total_pages", 1)
            print(f"  Got {len(enterprises)} results (total: {total_results}, page {page}/{total_pages})")

            if page >= total_pages or page >= 6:
                break
            page += 1
            time.sleep(3)  # Respect rate limits

        time.sleep(3)

    # Broad queries (no NAF filter)
    for q, dept in BROAD_QUERIES:
        page = 1
        while True:
            encoded_q = urllib.parse.quote(q)
            url = f"https://recherche-entreprises.api.gouv.fr/search?q={encoded_q}&departement={dept}&page={page}&per_page=25"
            print(f"Fetching broad: q={q}, dept={dept}, page={page}")
            data = fetch_url(url)
            if not data:
                break

            enterprises = extract_enterprises(data)
            if not enterprises:
                break

            for ent in enterprises:
                siren = ent["siren"]
                if siren and siren not in all_enterprises:
                    all_enterprises[siren] = ent
                    total_fetched += 1

            total_results = data.get("total_results", 0)
            total_pages = data.get("total_pages", 1)
            print(f"  Got {len(enterprises)} results (total: {total_results}, page {page}/{total_pages})")

            # For broad queries, limit to 3 pages to avoid too many irrelevant results
            if page >= min(total_pages, 3):
                break
            page += 1
            time.sleep(3)

        time.sleep(3)

    # Convert to list and save
    result_list = list(all_enterprises.values())

    # Sort by department (postal code) then name
    result_list.sort(key=lambda x: (x.get("postal_code", ""), x.get("name", "")))

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result_list, f, ensure_ascii=False, indent=2)

    print(f"\n=== DONE ===")
    print(f"Total unique enterprises saved: {len(result_list)}")
    print(f"Output: {OUTPUT_FILE}")

    # Summary by department
    dept54 = [e for e in result_list if e.get("postal_code", "").startswith("54")]
    dept93 = [e for e in result_list if e.get("postal_code", "").startswith("93")]
    other = [e for e in result_list if not e.get("postal_code", "").startswith(("54", "93"))]
    print(f"  Dept 54 (Meurthe-et-Moselle): {len(dept54)}")
    print(f"  Dept 93 (Seine-Saint-Denis): {len(dept93)}")
    if other:
        print(f"  Other departments: {len(other)}")


if __name__ == "__main__":
    main()
