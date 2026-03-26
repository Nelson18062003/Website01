#!/usr/bin/env python3
"""Fetch all automobile and motorcycle businesses in Lyon from the French government API."""

import json
import time
import urllib.request
import urllib.parse
import sys

BASE_URL = "https://recherche-entreprises.api.gouv.fr/search"

# Lyon arrondissements: 69381 (1er) to 69389 (9e)
LYON_COMMUNES = [str(c) for c in range(69381, 69390)]

NAF_CODES = {
    "45.20A": "garage",
    "45.11Z": "concession",
    "45.20B": "carrossier",
    "45.40Z": "moto",
}

NAF_LABELS = {
    "45.20A": "Entretien et réparation de véhicules automobiles légers",
    "45.11Z": "Commerce de voitures et de véhicules automobiles légers",
    "45.20B": "Entretien et réparation d'autres véhicules automobiles",
    "45.40Z": "Commerce de motocycles",
}

def fetch_page(naf_code, commune, page, retries=5):
    params = urllib.parse.urlencode({
        "activite_principale": naf_code,
        "commune": commune,
        "per_page": 25,
        "page": page,
    })
    url = f"{BASE_URL}?{params}"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
                return data
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 2 ** attempt + 1
                print(f"  Rate limited, waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
            else:
                print(f"  HTTP error {e.code} for {url}", file=sys.stderr)
                return None
        except Exception as e:
            print(f"  Error: {e}", file=sys.stderr)
            time.sleep(2)
    return None


def extract_enterprise(result, naf_code, category):
    siege = result.get("siege", {})
    matching = result.get("matching_etablissements", [])

    # Use siege address; if siege is not in Lyon, check matching establishments
    adresse = siege.get("adresse", "")
    code_postal = siege.get("code_postal", "")
    ville = siege.get("libelle_commune", "")
    siret = siege.get("siret", "")

    return {
        "nom": result.get("nom_complet", result.get("nom_raison_sociale", "")),
        "nom_raison_sociale": result.get("nom_raison_sociale", ""),
        "siren": result.get("siren", ""),
        "siret": siret,
        "adresse": adresse,
        "code_postal": code_postal,
        "ville": ville,
        "code_naf": naf_code,
        "libelle_activite": NAF_LABELS.get(naf_code, ""),
        "date_creation": result.get("date_creation", ""),
        "statut": "actif" if result.get("etat_administratif") == "A" else "non actif",
        "effectif": siege.get("tranche_effectif_salarie", result.get("tranche_effectif_salarie", "")),
        "categorie": category,
    }


def main():
    all_enterprises = {}
    counts = {cat: 0 for cat in NAF_CODES.values()}

    for naf_code, category in NAF_CODES.items():
        print(f"\n=== NAF {naf_code} ({category}) ===", file=sys.stderr)
        for commune in LYON_COMMUNES:
            page = 1
            while True:
                print(f"  Commune {commune}, page {page}...", file=sys.stderr)
                data = fetch_page(naf_code, commune, page)
                if data is None:
                    break
                total = data.get("total_results", 0)
                total_pages = data.get("total_pages", 0)
                results = data.get("results", [])
                if not results:
                    break
                for r in results:
                    siren = r.get("siren", "")
                    if siren and siren not in all_enterprises:
                        ent = extract_enterprise(r, naf_code, category)
                        all_enterprises[siren] = ent
                        counts[category] += 1
                if page >= total_pages:
                    break
                page += 1
                time.sleep(0.3)
            time.sleep(0.3)

    # Output
    enterprises_list = list(all_enterprises.values())
    output = {
        "resume": {
            "total": len(enterprises_list),
            "par_categorie": counts,
        },
        "entreprises": enterprises_list,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
