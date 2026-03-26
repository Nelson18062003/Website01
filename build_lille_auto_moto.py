#!/usr/bin/env python3
"""
Build complete JSON of auto/moto enterprises in Lille from API data.
Filters only companies with siege in Lille (libelle_commune=LILLE).
"""
import json
import time
import urllib.request
import urllib.parse
import ssl

# Disable SSL verification for simplicity
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

BASE_URL = "https://recherche-entreprises.api.gouv.fr/search"

CODES_NAF = {
    "45.20A": {"label": "Entretien et reparation de vehicules automobiles legers", "categorie": "garage"},
    "45.11Z": {"label": "Commerce de voitures et de vehicules automobiles legers", "categorie": "concession"},
    "45.20B": {"label": "Entretien et reparation d'autres vehicules automobiles", "categorie": "carrossier"},
    "45.40Z": {"label": "Commerce et reparation de motocycles", "categorie": "moto"},
}

def fetch_page(code_naf, page, per_page=25):
    params = urllib.parse.urlencode({
        "activite_principale": code_naf,
        "commune": "59350",
        "per_page": per_page,
        "page": page,
    })
    url = f"{BASE_URL}?{params}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data
    except Exception as e:
        print(f"  Error fetching page {page} for {code_naf}: {e}")
        return None

def extract_enterprise(result, code_naf, info):
    """Extract enterprise data from API result."""
    siege = result.get("siege", {})

    # Get commune from siege
    commune = siege.get("libelle_commune", "")
    if not commune:
        commune = result.get("nom_complet", "")

    # Only keep enterprises with siege in LILLE
    if commune.upper() != "LILLE":
        return None

    # Determine status
    etat = result.get("etat_administratif", "")
    if etat == "A":
        statut = "Actif"
    elif etat == "C":
        statut = "Cesse"
    elif etat == "F":
        statut = "Ferme"
    else:
        statut = etat

    # Effectif
    tranche = siege.get("tranche_effectif_salarie", result.get("tranche_effectif_salarie", ""))
    if not tranche:
        tranche = result.get("tranche_effectif_salarie", "")
    effectif_map = {
        "NN": "Non renseigne",
        "00": "0 salarie",
        "01": "1 ou 2 salaries",
        "02": "3 a 5 salaries",
        "03": "6 a 9 salaries",
        "11": "10 a 19 salaries",
        "12": "20 a 49 salaries",
        "21": "50 a 99 salaries",
        "22": "100 a 199 salaries",
        "31": "200 a 249 salaries",
        "32": "250 a 499 salaries",
        "41": "500 a 999 salaries",
        "42": "1000 a 1999 salaries",
        "51": "2000 a 4999 salaries",
        "52": "5000 a 9999 salaries",
        "53": "10000 salaries et plus",
    }
    effectif_label = effectif_map.get(str(tranche), str(tranche) if tranche else "Non renseigne")

    # Get activite principale
    act_code = siege.get("activite_principale", code_naf)
    if not act_code:
        act_code = code_naf

    return {
        "nom": result.get("nom_complet", ""),
        "nom_raison_sociale": result.get("nom_raison_sociale", ""),
        "siren": result.get("siren", ""),
        "siret": siege.get("siret", ""),
        "adresse": siege.get("adresse", ""),
        "code_postal": siege.get("code_postal", ""),
        "ville": commune,
        "code_naf": act_code,
        "libelle_activite": info["label"],
        "categorie": info["categorie"],
        "date_creation": result.get("date_creation", ""),
        "statut": statut,
        "etat_administratif": etat,
        "effectif": effectif_label,
        "tranche_effectif_code": str(tranche),
    }


def main():
    all_enterprises = []
    counts = {"garage": 0, "concession": 0, "carrossier": 0, "moto": 0}
    seen_siren = set()

    for code_naf, info in CODES_NAF.items():
        print(f"\n{'='*60}")
        print(f"Code NAF: {code_naf} - {info['label']} ({info['categorie']})")
        print(f"{'='*60}")

        page = 1
        total_pages = None
        total_results = None
        retries = 0

        while True:
            print(f"  Fetching page {page}...", end=" ")
            data = fetch_page(code_naf, page)

            if data is None:
                retries += 1
                if retries > 5:
                    print(f"  Too many retries, stopping at page {page}")
                    break
                print(f"  Retrying in 7s... (attempt {retries})")
                time.sleep(7)
                continue

            retries = 0

            if total_pages is None:
                total_results = data.get("total_results", 0)
                total_pages = data.get("total_pages", 1)
                print(f"Total results: {total_results}, Total pages: {total_pages}")

            results = data.get("results", [])
            if not results:
                print("No more results.")
                break

            page_lille_count = 0
            for r in results:
                ent = extract_enterprise(r, code_naf, info)
                if ent and ent["siren"] not in seen_siren:
                    seen_siren.add(ent["siren"])
                    all_enterprises.append(ent)
                    counts[info["categorie"]] += 1
                    page_lille_count += 1

            print(f"  Got {len(results)} results, {page_lille_count} in Lille (new)")

            if page >= total_pages:
                print(f"  Reached last page ({total_pages})")
                break

            page += 1
            time.sleep(1.5)  # Rate limiting

    # Sort by categorie then nom
    all_enterprises.sort(key=lambda x: (x["categorie"], x["nom"]))

    output = {
        "metadata": {
            "description": "Entreprises automobiles et moto avec siege social a Lille",
            "source": "API recherche-entreprises.api.gouv.fr",
            "commune_insee": "59350",
            "date_extraction": "2026-03-26",
            "codes_naf": {
                "45.20A": "Garages - Entretien et reparation vehicules legers",
                "45.11Z": "Concessions - Commerce de voitures",
                "45.20B": "Carrossiers - Entretien et reparation autres vehicules",
                "45.40Z": "Motos - Commerce et reparation de motocycles",
            },
            "total_entreprises": len(all_enterprises),
            "total_par_categorie": counts,
            "total_actives": sum(1 for e in all_enterprises if e["statut"] == "Actif"),
            "total_cessees": sum(1 for e in all_enterprises if e["statut"] != "Actif"),
        },
        "entreprises": all_enterprises,
    }

    output_path = "/home/user/Website01/entreprises_auto_moto_lille.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"RESUME")
    print(f"{'='*60}")
    print(f"Total entreprises (siege a Lille): {len(all_enterprises)}")
    print(f"  - Garages (45.20A):     {counts['garage']}")
    print(f"  - Concessions (45.11Z): {counts['concession']}")
    print(f"  - Carrossiers (45.20B): {counts['carrossier']}")
    print(f"  - Motos (45.40Z):       {counts['moto']}")
    print(f"  - Actives: {output['metadata']['total_actives']}")
    print(f"  - Cessees: {output['metadata']['total_cessees']}")
    print(f"\nFichier sauvegarde: {output_path}")


if __name__ == "__main__":
    main()
