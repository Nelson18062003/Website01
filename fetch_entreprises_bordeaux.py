#!/usr/bin/env python3
"""
Fetches all automotive/motorcycle companies in Bordeaux (commune=33063)
from the French government API, for specified NAF codes.
"""

import json
import time
import urllib.request
import urllib.parse
import sys

BASE_URL = "https://recherche-entreprises.api.gouv.fr/search"
COMMUNE = "33063"
PER_PAGE = 25

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


def fetch_page(naf_code, page, max_retries=10):
    params = urllib.parse.urlencode({
        "activite_principale": naf_code,
        "commune": COMMUNE,
        "per_page": PER_PAGE,
        "page": page,
    })
    url = f"{BASE_URL}?{params}"

    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = min(3 + attempt * 2, 20)
                print(f"  Rate limited on {naf_code} page {page}, waiting {wait}s (attempt {attempt+1})...", file=sys.stderr)
                time.sleep(wait)
            else:
                raise
        except Exception as e:
            wait = min(3 + attempt * 2, 20)
            print(f"  Error {e} on {naf_code} page {page}, retrying in {wait}s...", file=sys.stderr)
            time.sleep(wait)

    raise Exception(f"Failed after {max_retries} retries: {naf_code} page {page}")


def extract_company(result, naf_code, category):
    siege = result.get("siege", {})

    # Get the matching etablissement in Bordeaux if siege is not in Bordeaux
    matching_etab = result.get("matching_etablissements", [])

    nom = result.get("nom_complet") or result.get("nom_raison_sociale") or ""
    siren = result.get("siren", "")

    # Siege info
    siege_siret = siege.get("siret", "")
    siege_adresse = siege.get("adresse", "")
    siege_cp = siege.get("code_postal", "")
    siege_commune = siege.get("libelle_commune", "")

    # Activity
    activite = siege.get("activite_principale", "") or result.get("activite_principale", "")

    date_creation = result.get("date_creation", "")
    etat = result.get("etat_administratif", "")
    statut = "Actif" if etat == "A" else ("Fermé" if etat == "F" else ("Cessé" if etat == "C" else etat))

    effectif = result.get("tranche_effectif_salarie", "")
    if not effectif or effectif == "NN":
        effectif = "Non renseigné"

    return {
        "nom": nom,
        "siret": siege_siret,
        "siren": siren,
        "adresse": siege_adresse,
        "code_postal": siege_cp,
        "ville": siege_commune,
        "code_naf": naf_code,
        "libelle_activite": NAF_LABELS.get(naf_code, ""),
        "date_creation": date_creation,
        "statut": statut,
        "effectif": effectif,
        "categorie": category,
    }


def main():
    all_companies = []
    summary = {}

    for naf_code, category in NAF_CODES.items():
        print(f"\n--- Fetching NAF {naf_code} ({category}) ---", file=sys.stderr)

        page = 1
        total = None
        count = 0

        while True:
            print(f"  Page {page}...", file=sys.stderr)
            data = fetch_page(naf_code, page)

            if total is None:
                total = data.get("total_results", 0)
                print(f"  Total results: {total}", file=sys.stderr)

            results = data.get("results", [])
            if not results:
                break

            for r in results:
                company = extract_company(r, naf_code, category)
                all_companies.append(company)
                count += 1

            if count >= total:
                break

            page += 1
            time.sleep(2.5)  # Be nice to the API - avoid rate limiting

        summary[category] = {"naf": naf_code, "total": total, "extracted": count}
        print(f"  Done: {count} companies extracted", file=sys.stderr)

    # Output
    output = {
        "resume": summary,
        "total_entreprises": len(all_companies),
        "entreprises": all_companies,
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
