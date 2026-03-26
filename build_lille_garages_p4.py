#!/usr/bin/env python3
"""Fetch missing page 4 of 45.20A and merge."""
import json, time, urllib.request, urllib.parse, ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def fetch(page):
    params = urllib.parse.urlencode({"activite_principale": "45.20A", "commune": "59350", "per_page": 25, "page": page})
    url = f"https://recherche-entreprises.api.gouv.fr/search?{params}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))

with open("/home/user/Website01/entreprises_auto_moto_lille.json", "r") as f:
    existing = json.load(f)

seen = {e["siren"] for e in existing["entreprises"]}

# Try page 4 with delays
for attempt in range(10):
    try:
        print(f"Attempt {attempt+1}...")
        data = fetch(4)
        results = data.get("results", [])
        count = 0
        for r in results:
            siege = r.get("siege", {})
            if siege.get("libelle_commune", "").upper() != "LILLE":
                continue
            siren = r.get("siren", "")
            if siren in seen:
                continue
            seen.add(siren)
            etat = r.get("etat_administratif", "")
            tranche = siege.get("tranche_effectif_salarie", r.get("tranche_effectif_salarie", ""))
            effectif_map = {"NN": "Non renseigne", "00": "0 salarie", "01": "1 ou 2 salaries",
                "02": "3 a 5 salaries", "03": "6 a 9 salaries", "11": "10 a 19 salaries",
                "12": "20 a 49 salaries", "21": "50 a 99 salaries"}
            existing["entreprises"].append({
                "nom": r.get("nom_complet", ""), "nom_raison_sociale": r.get("nom_raison_sociale", ""),
                "siren": siren, "siret": siege.get("siret", ""),
                "adresse": siege.get("adresse", ""), "code_postal": siege.get("code_postal", ""),
                "ville": "LILLE", "code_naf": siege.get("activite_principale", "45.20A") or "45.20A",
                "libelle_activite": "Entretien et reparation de vehicules automobiles legers",
                "categorie": "garage", "date_creation": r.get("date_creation", ""),
                "statut": {"A": "Actif", "C": "Cesse", "F": "Ferme"}.get(etat, etat),
                "etat_administratif": etat,
                "effectif": effectif_map.get(str(tranche), str(tranche) if tranche else "Non renseigne"),
                "tranche_effectif_code": str(tranche),
            })
            count += 1
        print(f"Got {len(results)} results, {count} new in Lille")
        break
    except Exception as e:
        print(f"Error: {e}, waiting 15s...")
        time.sleep(15)

existing["entreprises"].sort(key=lambda x: (x["categorie"], x["nom"]))
gc = sum(1 for e in existing["entreprises"] if e["categorie"] == "garage")
existing["metadata"]["total_entreprises"] = len(existing["entreprises"])
existing["metadata"]["total_par_categorie"]["garage"] = gc
existing["metadata"]["total_actives"] = sum(1 for e in existing["entreprises"] if e["statut"] == "Actif")
existing["metadata"]["total_cessees"] = sum(1 for e in existing["entreprises"] if e["statut"] != "Actif")

with open("/home/user/Website01/entreprises_auto_moto_lille.json", "w", encoding="utf-8") as f:
    json.dump(existing, f, ensure_ascii=False, indent=2)

print(f"Total: {len(existing['entreprises'])} (garages: {gc})")
