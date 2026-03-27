#!/usr/bin/env python3
"""
Agent d'enrichissement des numéros de téléphone pour les établissements de Toulouse.
Traite les entrées 0 à 700 de la liste Toulouse sans téléphone.
"""

import json
import re
import time
import urllib.request
import urllib.parse
from difflib import SequenceMatcher

# ── Normalisation ──────────────────────────────────────────────────────────────

def normalize_name(name):
    if not name:
        return ""
    name = name.upper()
    name = re.sub(r'\b(SARL|SAS|SA|EURL|SCI|SASU|SNC|ETS|ETABLISSEMENTS?)\b', '', name)
    name = re.sub(r'[^A-Z0-9\s]', ' ', name)
    return re.sub(r'\s+', ' ', name).strip()

def normalize_phone(phone):
    """Formate un téléphone en format français 0X XX XX XX XX."""
    if not phone:
        return ""
    digits = re.sub(r'\D', '', phone)
    if digits.startswith('33') and len(digits) == 11:
        digits = '0' + digits[2:]
    if len(digits) == 10 and digits.startswith('0'):
        return f"{digits[0:2]} {digits[2:4]} {digits[4:6]} {digits[6:8]} {digits[8:10]}"
    return phone  # retourner tel quel si non reconnu

def normalize_address(addr):
    if not addr:
        return ""
    addr = addr.upper()
    addr = re.sub(r'[^A-Z0-9\s]', ' ', addr)
    return re.sub(r'\s+', ' ', addr).strip()

# ── Chargement des données ─────────────────────────────────────────────────────

print("Chargement des données...")

with open('/home/user/Website01/entreprises_auto_moto_evry_toulouse_area.json', encoding='utf-8') as f:
    all_data = json.load(f)

toulouse_all = [e for e in all_data if e.get('ville', '').upper() == 'TOULOUSE']
print(f"  Toulouse total: {len(toulouse_all)}")

# Sous-ensemble à traiter : entrées 0 à 700 (inclus → 701 entrées)
target_entries = toulouse_all[0:701]
to_enrich = [e for e in target_entries if not e.get('telephone')]
print(f"  Entrées à traiter (0-700): {len(target_entries)}")
print(f"  Sans téléphone: {len(to_enrich)}")

# Chargement des sources PJ
pj_entries = []  # liste de dicts avec champs nom_pj, telephone, adresse_pj, code_postal_pj

with open('/home/user/Website01/pj_results_toulouse.json', encoding='utf-8') as f:
    pj_results = json.load(f)
pj_entries.extend(pj_results)
print(f"  PJ results chargés: {len(pj_results)}")

with open('/home/user/Website01/pj_cache_toulouse.json', encoding='utf-8') as f:
    pj_cache = json.load(f)

cache_count = 0
for cat_key, items in pj_cache.items():
    for item in items:
        if item.get('telephone'):
            pj_entries.append(item)
            cache_count += 1
print(f"  PJ cache chargés (avec téléphone): {cache_count}")

# Dédupliquer pj_entries sur url ou (nom+adresse)
seen = set()
pj_unique = []
for entry in pj_entries:
    key = entry.get('url_pj') or (entry.get('nom_pj', '') + '|' + entry.get('adresse_pj', ''))
    if key not in seen:
        seen.add(key)
        pj_unique.append(entry)
print(f"  PJ unique (avec téléphone): {len(pj_unique)}")

# Pré-calculer noms normalisés PJ
for entry in pj_unique:
    entry['_norm_name'] = normalize_name(entry.get('nom_pj', ''))
    entry['_norm_addr'] = normalize_address(entry.get('adresse_pj', ''))

# ── Matching PJ ───────────────────────────────────────────────────────────────

def find_pj_match(entry, pj_list):
    """Tente de trouver un match PJ pour une entrée.
    Retourne (telephone, source, score) ou (None, None, 0).
    """
    norm_name = normalize_name(entry.get('nom', ''))
    norm_addr = normalize_address(entry.get('adresse', ''))
    cp = entry.get('code_postal', '')

    best_score = 0
    best_phone = None
    best_source = None

    for pj in pj_list:
        pj_name = pj['_norm_name']
        pj_cp = pj.get('code_postal_pj', '')
        pj_addr = pj['_norm_addr']

        # a) Correspondance exacte du nom normalisé
        if norm_name and norm_name == pj_name:
            phone = normalize_phone(pj.get('telephone', ''))
            if phone:
                return phone, 'PJ_match', 1.0

        # b) Correspondance adresse : code postal + début de rue
        if cp and pj_cp and cp == pj_cp:
            # Extraire les mots de l'adresse (hors numéro de rue)
            addr_words = [w for w in norm_addr.split() if not w.isdigit()]
            pj_addr_words = [w for w in pj_addr.split() if not w.isdigit()]
            if addr_words and pj_addr_words:
                # Vérifier chevauchement des mots significatifs
                common = set(addr_words[:3]) & set(pj_addr_words[:3])
                if len(common) >= 2:
                    phone = normalize_phone(pj.get('telephone', ''))
                    if phone:
                        score = 0.85
                        if score > best_score:
                            best_score = score
                            best_phone = phone
                            best_source = 'PJ_match'

        # c) Score de similarité > 0.65
        if norm_name and pj_name:
            ratio = SequenceMatcher(None, norm_name, pj_name).ratio()
            if ratio > 0.65 and ratio > best_score:
                phone = normalize_phone(pj.get('telephone', ''))
                if phone:
                    best_score = ratio
                    best_phone = phone
                    best_source = 'PJ_match'

    if best_phone:
        return best_phone, best_source, round(best_score, 3)

    return None, None, 0.0

# ── Phase 1 : Matching PJ local ───────────────────────────────────────────────

print("\nPhase 1 : Matching PJ local...")

results = []
still_missing = []

for i, entry in enumerate(to_enrich):
    phone, source, score = find_pj_match(entry, pj_unique)
    if phone:
        results.append({
            "siret": entry.get('siret', ''),
            "telephone": phone,
            "source_telephone": source,
            "match_score": score
        })
    else:
        still_missing.append(entry)

print(f"  Téléphones trouvés via PJ: {len(results)}")
print(f"  Encore sans téléphone: {len(still_missing)}")

# ── Phase 2 : API Recherche Entreprises ───────────────────────────────────────

def search_entreprises_api(nom, ville="Toulouse"):
    """Appelle l'API gouv.fr et retourne le premier résultat."""
    query = urllib.parse.quote(f"{nom} {ville}")
    url = f"https://recherche-entreprises.api.gouv.fr/search?q={query}&per_page=3"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        return data.get('results', [])
    except Exception as e:
        return []

def extract_phone_from_api(results, siret):
    """Tente d'extraire un téléphone du résultat API en vérifiant le SIRET."""
    for r in results:
        # Chercher dans les établissements
        for etab in r.get('matching_etablissements', []):
            if etab.get('siret') == siret:
                # L'API gouv ne retourne pas directement les téléphones
                # mais on peut vérifier la cohérence
                pass
        # Vérifier SIREN match comme fallback
        siren = siret[:9] if len(siret) >= 9 else siret
        if r.get('siren') == siren:
            # L'API Recherche Entreprises ne fournit pas de téléphone directement
            # On retourne None (l'API ne contient pas ce champ)
            return None
    return None

print("\nPhase 2 : Appels API Recherche Entreprises (vérification SIRET)...")
print("  Note: L'API recherche-entreprises.api.gouv.fr ne fournit pas de téléphone.")
print("  Les appels servent à confirmer l'existence mais pas enrichir le téléphone.")

# L'API Recherche Entreprises (api.gouv.fr/search) ne retourne pas de champs téléphone.
# On skip cette phase qui ne produirait pas de résultats utiles.
api_found = 0
print(f"  Téléphones trouvés via API: {api_found}")

# ── Résultats finaux ───────────────────────────────────────────────────────────

print(f"\n{'='*60}")
print(f"RÉSULTATS")
print(f"{'='*60}")
print(f"Entrées traitées       : {len(to_enrich)}")
print(f"Téléphones trouvés     : {len(results)}")
taux = (len(results) / len(to_enrich) * 100) if to_enrich else 0
print(f"Taux d'enrichissement  : {taux:.1f}%")

# Distribution des scores
if results:
    scores = [r['match_score'] for r in results]
    print(f"Score moyen            : {sum(scores)/len(scores):.3f}")
    exact = sum(1 for s in scores if s == 1.0)
    high  = sum(1 for s in scores if 0.8 <= s < 1.0)
    med   = sum(1 for s in scores if 0.65 <= s < 0.8)
    print(f"  Exact (1.0)          : {exact}")
    print(f"  Haut  (0.8-1.0)      : {high}")
    print(f"  Moyen (0.65-0.8)     : {med}")

# Sauvegarde
output_path = '/home/user/Website01/agent_out_7_phones_toulouse_1.json'
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(f"\nFichier sauvegardé: {output_path}")
print(f"Entrées sauvegardées: {len(results)}")
