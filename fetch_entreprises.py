import urllib.request
import json
import time
import sys

BASE_URL = "https://recherche-entreprises.api.gouv.fr/search"
COMMUNE = "59350"  # Lille
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
counts = {}

for naf_code, categorie in NAF_CODES.items():
    page = 1
    total_for_naf = 0
    while True:
        url = f"{BASE_URL}?activite_principale={naf_code}&commune={COMMUNE}&per_page={PER_PAGE}&page={page}"
        print(f"Fetching {naf_code} page {page}...", file=sys.stderr)

        retries = 0
        while retries < 5:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode())
                break
            except Exception as e:
                retries += 1
                wait = 5 * retries
                print(f"  Retry {retries}, waiting {wait}s... ({e})", file=sys.stderr)
                time.sleep(wait)
        else:
            print(f"  Failed after 5 retries for {naf_code} page {page}", file=sys.stderr)
            break

        results = data.get("results", [])
        total_results = data.get("total_results", 0)
        total_pages = data.get("total_pages", 1)

        if page == 1:
            print(f"  Total results for {naf_code}: {total_results}, pages: {total_pages}", file=sys.stderr)

        for r in results:
            siege = r.get("siege", {})
            # Only keep if siege is actually in Lille (commune 59350)
            commune_siege = siege.get("commune", "")

            entry = {
                "nom": r.get("nom_complet") or r.get("nom_raison_sociale", ""),
                "nom_raison_sociale": r.get("nom_raison_sociale", ""),
                "siren": r.get("siren", ""),
                "siret": siege.get("siret", ""),
                "adresse": siege.get("adresse", ""),
                "code_postal": siege.get("code_postal", ""),
                "ville": siege.get("libelle_commune", ""),
                "code_naf": naf_code,
                "libelle_activite": NAF_LABELS.get(naf_code, siege.get("activite_principale", "")),
                "date_creation": r.get("date_creation", ""),
                "statut": "Actif" if r.get("etat_administratif") == "A" else "Non actif",
                "effectif": siege.get("tranche_effectif_salarie", "Non renseigné"),
                "categorie": categorie,
                "commune_siege": commune_siege,
            }
            all_results.append(entry)
            total_for_naf += 1

        if page >= total_pages or len(results) == 0:
            break
        page += 1
        time.sleep(2)  # rate limit

    counts[categorie] = {"naf": naf_code, "count": total_for_naf}
    time.sleep(3)  # pause between NAF codes

# Filter: only keep entries whose siege commune is 59350 (Lille)
lille_results = [r for r in all_results if r["commune_siege"] == "59350"]
# Remove the helper field
for r in lille_results:
    del r["commune_siege"]

# Also remove from non-lille
non_lille = [r for r in all_results if r["commune_siege"] != "59350"]

# Recount
lille_counts = {}
for r in lille_results:
    cat = r["categorie"]
    lille_counts[cat] = lille_counts.get(cat, 0) + 1

output = {
    "resume": {
        "total_entreprises": len(lille_results),
        "par_categorie": lille_counts,
        "note": "Entreprises dont le siège est à Lille (commune INSEE 59350)",
        "entreprises_hors_lille_siege": len(non_lille),
    },
    "entreprises": lille_results,
}

# Also for non-lille
for r in non_lille:
    del r["commune_siege"]

print(json.dumps(output, ensure_ascii=False, indent=2))
