#!/usr/bin/env python3
"""Fetch all auto/moto enterprises for Evry, Toulouse, Colomiers, Blagnac, Muret"""
import json, time, urllib.request, urllib.error

CITIES = {
    "Evry": "91228",
    "Toulouse": "31555",
}

NAF_CODES = {
    "45.20A": "garage",
    "45.11Z": "concession",
    "45.20B": "carrossier",
    "45.40Z": "moto",
}

BASE_URL = "https://recherche-entreprises.api.gouv.fr/search"

def fetch_page(naf, commune, page):
    url = f"{BASE_URL}?activite_principale={naf}&commune={commune}&per_page=25&page={page}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())

def extract_enterprise(r, naf, categorie, ville_recherche):
    siege = r.get('siege', {})
    matching = r.get('matching_etablissements', [])
    
    # Use matching establishment if siege is in different city
    etab = matching[0] if matching else siege
    
    if siege.get('etat_administratif') != 'A' and not matching:
        return None
    
    return {
        "nom": r.get('nom_complet', ''),
        "siret": etab.get('siret', siege.get('siret', '')),
        "siren": r.get('siren', ''),
        "adresse": etab.get('adresse', siege.get('adresse', '')),
        "code_postal": etab.get('code_postal', siege.get('code_postal', '')),
        "ville": etab.get('libelle_commune', siege.get('libelle_commune', '')),
        "code_naf": naf,
        "libelle_activite": etab.get('libelle_activite_principale', ''),
        "date_creation": r.get('date_creation', ''),
        "statut": "Actif",
        "effectif": str(r.get('tranche_effectif_salarie', siege.get('tranche_effectif_salarie', ''))),
        "categorie": categorie,
        "zone_recherche": ville_recherche
    }

for ville, commune in CITIES.items():
    all_entries = []
    for naf, cat in NAF_CODES.items():
        page = 1
        total_pages = 1
        while page <= total_pages:
            try:
                data = fetch_page(naf, commune, page)
                total_pages = data.get('total_pages', 1)
                total_results = data.get('total_results', 0)
                if page == 1:
                    print(f"[{ville}] {naf} ({cat}): {total_results} résultats, {total_pages} pages")
                for r in data.get('results', []):
                    entry = extract_enterprise(r, naf, cat, ville)
                    if entry:
                        all_entries.append(entry)
                page += 1
                time.sleep(0.2)
            except Exception as e:
                print(f"  Erreur page {page}: {e}")
                time.sleep(1)
                page += 1
    
    # Deduplicate by SIRET
    seen = set()
    unique = []
    for e in all_entries:
        if e['siret'] not in seen:
            seen.add(e['siret'])
            unique.append(e)
    
    outfile = f"/home/user/Website01/api_{ville.lower()}.json"
    with open(outfile, 'w', encoding='utf-8') as f:
        json.dump(unique, f, ensure_ascii=False, indent=2)
    print(f"[{ville}] TOTAL: {len(unique)} entreprises actives -> {outfile}\n")

print("DONE")
