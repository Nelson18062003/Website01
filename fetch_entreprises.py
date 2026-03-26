#!/usr/bin/env python3
"""
Fetch all automotive/motorcycle businesses within 15km of Bordeaux
using the French government API (near_point endpoint).
"""
import json
import time
import urllib.request
import urllib.error
import sys

BASE_URL = "https://recherche-entreprises.api.gouv.fr/near_point"
LAT = 44.8378
LONG = -0.5792
RADIUS = 15
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

all_results = []
summary = {}

for naf_code, category in NAF_CODES.items():
    page = 1
    total_for_naf = 0
    total_pages = None

    while True:
        url = f"{BASE_URL}?activite_principale={naf_code}&lat={LAT}&long={LONG}&radius={RADIUS}&per_page={PER_PAGE}&page={page}"

        retries = 0
        data = None
        while retries < 5:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode())
                break
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    retries += 1
                    wait = 15 * retries
                    print(f"  Rate limited on {naf_code} page {page}, waiting {wait}s... (retry {retries})", file=sys.stderr)
                    time.sleep(wait)
                else:
                    print(f"  HTTP {e.code} on {naf_code} page {page}", file=sys.stderr)
                    raise
            except Exception as e:
                retries += 1
                wait = 10 * retries
                print(f"  Error {e} on {naf_code} page {page}, waiting {wait}s... (retry {retries})", file=sys.stderr)
                time.sleep(wait)

        if data is None:
            print(f"  FAILED after retries: {naf_code} page {page}", file=sys.stderr)
            break

        if total_pages is None:
            total_pages = data.get("total_pages", 1)
            total_results_api = data.get("total_results", 0)
            print(f"NAF {naf_code} ({category}): {total_results_api} total results, {total_pages} pages", file=sys.stderr)

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

        if page >= total_pages:
            break

        page += 1
        time.sleep(2)

    summary[category] = total_for_naf
    print(f"  => Collected {total_for_naf} entries for {naf_code} ({category})", file=sys.stderr)
    time.sleep(3)

output = {
    "resume": {
        "rayon": "15km autour de Bordeaux (44.8378, -0.5792)",
        "par_categorie": summary,
        "total": len(all_results),
    },
    "entreprises": all_results,
}

with open("/home/user/Website01/entreprises_auto_moto_bordeaux.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"\nTotal: {len(all_results)} entreprises saved to entreprises_auto_moto_bordeaux.json", file=sys.stderr)
print(json.dumps(output["resume"], ensure_ascii=False, indent=2))
