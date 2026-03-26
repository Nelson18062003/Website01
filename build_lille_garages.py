#!/usr/bin/env python3
"""
Fetch 45.20A (Garages) for Lille and merge with existing JSON.
"""
import json
import time
import urllib.request
import urllib.parse
import ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

BASE_URL = "https://recherche-entreprises.api.gouv.fr/search"

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
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  Error: {e}")
        return None

def extract(result, code_naf):
    siege = result.get("siege", {})
    commune = siege.get("libelle_commune", "")
    if commune.upper() != "LILLE":
        return None

    etat = result.get("etat_administratif", "")
    statut = {"A": "Actif", "C": "Cesse", "F": "Ferme"}.get(etat, etat)

    tranche = siege.get("tranche_effectif_salarie", result.get("tranche_effectif_salarie", ""))
    effectif_map = {
        "NN": "Non renseigne", "00": "0 salarie", "01": "1 ou 2 salaries",
        "02": "3 a 5 salaries", "03": "6 a 9 salaries", "11": "10 a 19 salaries",
        "12": "20 a 49 salaries", "21": "50 a 99 salaries", "22": "100 a 199 salaries",
        "31": "200 a 249 salaries", "32": "250 a 499 salaries",
    }
    effectif_label = effectif_map.get(str(tranche), str(tranche) if tranche else "Non renseigne")

    return {
        "nom": result.get("nom_complet", ""),
        "nom_raison_sociale": result.get("nom_raison_sociale", ""),
        "siren": result.get("siren", ""),
        "siret": siege.get("siret", ""),
        "adresse": siege.get("adresse", ""),
        "code_postal": siege.get("code_postal", ""),
        "ville": commune,
        "code_naf": siege.get("activite_principale", code_naf) or code_naf,
        "libelle_activite": "Entretien et reparation de vehicules automobiles legers",
        "categorie": "garage",
        "date_creation": result.get("date_creation", ""),
        "statut": statut,
        "etat_administratif": etat,
        "effectif": effectif_label,
        "tranche_effectif_code": str(tranche),
    }

# Load existing
with open("/home/user/Website01/entreprises_auto_moto_lille.json", "r") as f:
    existing = json.load(f)

seen = {e["siren"] for e in existing["entreprises"]}
garages = []
page = 1
total_pages = None

while True:
    print(f"Fetching page {page}...", end=" ")
    data = fetch_page("45.20A", page)
    if data is None:
        print("Retrying in 10s...")
        time.sleep(10)
        data = fetch_page("45.20A", page)
        if data is None:
            print("Retrying in 15s...")
            time.sleep(15)
            data = fetch_page("45.20A", page)
            if data is None:
                print("Skipping page")
                page += 1
                if total_pages and page > total_pages:
                    break
                continue

    if total_pages is None:
        total_pages = data.get("total_pages", 1)
        print(f"Total pages: {total_pages}")

    results = data.get("results", [])
    if not results:
        break

    count = 0
    for r in results:
        ent = extract(r, "45.20A")
        if ent and ent["siren"] not in seen:
            seen.add(ent["siren"])
            garages.append(ent)
            count += 1
    print(f"{len(results)} results, {count} new in Lille")

    if page >= total_pages:
        break
    page += 1
    time.sleep(2)

# Merge
existing["entreprises"].extend(garages)
existing["entreprises"].sort(key=lambda x: (x["categorie"], x["nom"]))

garage_count = sum(1 for e in existing["entreprises"] if e["categorie"] == "garage")
concession_count = sum(1 for e in existing["entreprises"] if e["categorie"] == "concession")
carrossier_count = sum(1 for e in existing["entreprises"] if e["categorie"] == "carrossier")
moto_count = sum(1 for e in existing["entreprises"] if e["categorie"] == "moto")

existing["metadata"]["total_entreprises"] = len(existing["entreprises"])
existing["metadata"]["total_par_categorie"] = {
    "garage": garage_count,
    "concession": concession_count,
    "carrossier": carrossier_count,
    "moto": moto_count,
}
existing["metadata"]["total_actives"] = sum(1 for e in existing["entreprises"] if e["statut"] == "Actif")
existing["metadata"]["total_cessees"] = sum(1 for e in existing["entreprises"] if e["statut"] != "Actif")

with open("/home/user/Website01/entreprises_auto_moto_lille.json", "w", encoding="utf-8") as f:
    json.dump(existing, f, ensure_ascii=False, indent=2)

print(f"\nTotal: {len(existing['entreprises'])} entreprises")
print(f"  Garages: {garage_count}")
print(f"  Concessions: {concession_count}")
print(f"  Carrossiers: {carrossier_count}")
print(f"  Motos: {moto_count}")
print(f"  Actives: {existing['metadata']['total_actives']}")
print(f"  Cessees: {existing['metadata']['total_cessees']}")
