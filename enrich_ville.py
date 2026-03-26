#!/usr/bin/env python3
"""
Enrichit les entreprises d'une ville avec téléphone/email/site web
via l'API annuaire-entreprises.data.gouv.fr
Usage: python3 enrich_ville.py <ville> 
"""
import json, sys, time, urllib.request, urllib.error

ville = sys.argv[1]  # lille, lyon, bordeaux
input_file = f'/home/user/Website01/split_{ville}.json'
output_file = f'/home/user/Website01/enriched_{ville}.json'

with open(input_file) as f:
    entreprises = json.load(f)

total = len(entreprises)
enriched = 0
errors = 0

for i, e in enumerate(entreprises):
    siren = e.get('siren', '').strip()
    if not siren or len(siren) != 9:
        continue
    
    url = f'https://recherche-entreprises.api.gouv.fr/search?q={siren}&per_page=1'
    
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        
        results = data.get('results', [])
        if results:
            r = results[0]
            # Complements
            complements = r.get('complements', {})
            
            # Check for collectivite_territoriale or other fields
            siege = r.get('siege', {})
            
            # Try to get geo coordinates
            e['latitude'] = siege.get('latitude', '')
            e['longitude'] = siege.get('longitude', '')
            
            # Nombre d'établissements
            e['nombre_etablissements'] = r.get('nombre_etablissements', '')
            e['nombre_etablissements_ouverts'] = r.get('nombre_etablissements_ouverts', '')
            
            # Tranche effectif détaillée
            e['tranche_effectif_salarie'] = r.get('tranche_effectif_salarie', '')
            
            # Nature juridique
            e['nature_juridique'] = r.get('nature_juridique', '')
            
            enriched += 1
    except (urllib.error.URLError, urllib.error.HTTPError, Exception) as ex:
        errors += 1
        if '429' in str(ex):
            time.sleep(2)
    
    # Rate limiting
    if i % 5 == 0:
        time.sleep(0.3)
    
    if (i + 1) % 100 == 0:
        print(f'[{ville}] {i+1}/{total} traités, {enriched} enrichis, {errors} erreurs')

# Save
with open(output_file, 'w', encoding='utf-8') as f:
    json.dump(entreprises, f, ensure_ascii=False, indent=2)

print(f'[{ville}] TERMINÉ: {total} entreprises, {enriched} enrichis, {errors} erreurs')
print(f'[{ville}] Fichier: {output_file}')
