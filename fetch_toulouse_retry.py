#!/usr/bin/env python3
"""Retry fetch for Toulouse with better rate limiting"""
import json, time, urllib.request, urllib.error

NAF_CODES = {"45.20A": "garage", "45.11Z": "concession", "45.20B": "carrossier", "45.40Z": "moto"}
BASE_URL = "https://recherche-entreprises.api.gouv.fr/search"

def fetch_page(naf, commune, page, retries=3):
    url = f"{BASE_URL}?activite_principale={naf}&commune={commune}&per_page=25&page={page}"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 2 ** (attempt + 1)
                time.sleep(wait)
            else:
                raise
    return None

def extract(r, naf, cat):
    siege = r.get('siege', {})
    matching = r.get('matching_etablissements', [])
    etab = matching[0] if matching else siege
    if siege.get('etat_administratif') != 'A' and not matching:
        return None
    return {
        "nom": r.get('nom_complet', ''), "siret": etab.get('siret', siege.get('siret', '')),
        "siren": r.get('siren', ''), "adresse": etab.get('adresse', siege.get('adresse', '')),
        "code_postal": etab.get('code_postal', siege.get('code_postal', '')),
        "ville": etab.get('libelle_commune', siege.get('libelle_commune', '')),
        "code_naf": naf, "libelle_activite": etab.get('libelle_activite_principale', ''),
        "date_creation": r.get('date_creation', ''), "statut": "Actif",
        "effectif": str(r.get('tranche_effectif_salarie', siege.get('tranche_effectif_salarie', ''))),
        "categorie": cat, "zone_recherche": "Toulouse"
    }

all_entries = []
for naf, cat in NAF_CODES.items():
    page = 1; total_pages = 1
    while page <= total_pages:
        data = fetch_page(naf, "31555", page)
        if data:
            total_pages = data.get('total_pages', 1)
            if page == 1:
                print(f"{naf} ({cat}): {data.get('total_results',0)} résultats, {total_pages} pages")
            for r in data.get('results', []):
                entry = extract(r, naf, cat)
                if entry: all_entries.append(entry)
        else:
            print(f"  SKIP page {page}")
        page += 1
        time.sleep(0.5)
    print(f"  -> {cat} done")

seen = set(); unique = []
for e in all_entries:
    if e['siret'] not in seen:
        seen.add(e['siret']); unique.append(e)

with open('/home/user/Website01/api_toulouse.json', 'w', encoding='utf-8') as f:
    json.dump(unique, f, ensure_ascii=False, indent=2)
print(f"\nTOTAL: {len(unique)} entreprises actives")
