#!/usr/bin/env python3
"""
Fetch all automotive/motorcycle businesses within 15km of Bordeaux
using the French government API (near_point endpoint).
Saves results incrementally to avoid data loss.
"""
import json
import time
import urllib.request
import urllib.error
import sys
import os

BASE_URL = "https://recherche-entreprises.api.gouv.fr/near_point"
LAT = 44.8378
LONG = -0.5792
RADIUS = 15
PER_PAGE = 25
OUTPUT_FILE = "/home/user/Website01/entreprises_auto_moto_bordeaux.json"
PROGRESS_FILE = "/home/user/Website01/fetch_progress.json"

NAF_CODES = [
    ("45.20A", "garage"),
    ("45.11Z", "concession"),
    ("45.20B", "carrossier"),
    ("45.40Z", "moto"),
]

NAF_LABELS = {
    "45.20A": "Entretien et réparation de véhicules automobiles légers",
    "45.11Z": "Commerce de voitures et de véhicules automobiles légers",
    "45.20B": "Entretien et réparation d'autres véhicules automobiles",
    "45.40Z": "Commerce de motocycles",
}

# Load progress if exists
if os.path.exists(PROGRESS_FILE):
    with open(PROGRESS_FILE, "r") as f:
        progress = json.load(f)
    all_results = progress.get("entreprises", [])
    summary = progress.get("summary", {})
    completed_naf = set(progress.get("completed_naf", []))
    print(f"Resuming: {len(all_results)} results already collected, completed NAFs: {completed_naf}", file=sys.stderr)
else:
    all_results = []
    summary = {}
    completed_naf = set()

def save_progress():
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "summary": summary,
            "completed_naf": list(completed_naf),
            "entreprises": all_results,
        }, f, ensure_ascii=False)

def fetch_with_retry(url, max_retries=8):
    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = min(10 * attempt, 60)
                print(f"    429 retry {attempt}, wait {wait}s", file=sys.stderr)
                time.sleep(wait)
            else:
                print(f"    HTTP {e.code}", file=sys.stderr)
                if attempt == max_retries:
                    return None
                time.sleep(5)
        except Exception as e:
            print(f"    Error: {e}, retry {attempt}", file=sys.stderr)
            time.sleep(5 * attempt)
    return None

for naf_code, category in NAF_CODES:
    if naf_code in completed_naf:
        print(f"Skipping {naf_code} ({category}) - already completed", file=sys.stderr)
        continue

    page = 1
    total_for_naf = 0
    total_pages = None

    while True:
        url = f"{BASE_URL}?activite_principale={naf_code}&lat={LAT}&long={LONG}&radius={RADIUS}&per_page={PER_PAGE}&page={page}"

        data = fetch_with_retry(url)
        if data is None:
            print(f"  FAILED: {naf_code} page {page}", file=sys.stderr)
            save_progress()
            break

        if total_pages is None:
            total_pages = data.get("total_pages", 1)
            total_results_api = data.get("total_results", 0)
            print(f"NAF {naf_code} ({category}): {total_results_api} results, {total_pages} pages", file=sys.stderr)

        results = data.get("results", [])
        if not results:
            break

        for r in results:
            s = r.get("siege", {})
            matching = r.get("matching_etablissements", [])

            local_addr = s.get("adresse", "")
            local_cp = s.get("code_postal", "")
            local_ville = s.get("libelle_commune", "")
            local_siret = s.get("siret", "")

            if matching:
                m = matching[0]
                local_addr = m.get("adresse", local_addr)
                local_cp = m.get("code_postal", local_cp)
                local_ville = m.get("libelle_commune", local_ville)
                local_siret = m.get("siret", local_siret)

            entry = {
                "nom": r.get("nom_complet", ""),
                "siren": r.get("siren", ""),
                "siret": local_siret,
                "adresse": local_addr,
                "code_postal": local_cp,
                "ville": local_ville,
                "code_naf": naf_code,
                "libelle_activite": NAF_LABELS.get(naf_code, ""),
                "date_creation": r.get("date_creation", ""),
                "statut": "actif" if s.get("etat_administratif") == "A" else "cessé",
                "effectif": r.get("tranche_effectif_salarie", ""),
                "categorie": category,
            }
            all_results.append(entry)
            total_for_naf += 1

        # Save progress every 5 pages
        if page % 5 == 0:
            save_progress()
            print(f"  Page {page}/{total_pages} done, {total_for_naf} entries so far", file=sys.stderr)

        if page >= total_pages:
            break

        page += 1
        time.sleep(4)  # Longer pause between pages

    summary[category] = total_for_naf
    completed_naf.add(naf_code)
    save_progress()
    print(f"  => {total_for_naf} entries for {naf_code} ({category})", file=sys.stderr)
    time.sleep(5)

# Final output
output = {
    "resume": {
        "rayon": "15km autour de Bordeaux (44.8378, -0.5792)",
        "par_categorie": summary,
        "total": len(all_results),
    },
    "entreprises": all_results,
}

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

# Clean up progress file
if os.path.exists(PROGRESS_FILE):
    os.remove(PROGRESS_FILE)

print(f"\nDONE: {len(all_results)} entreprises saved to {OUTPUT_FILE}", file=sys.stderr)
print(json.dumps(output["resume"], ensure_ascii=False, indent=2))
