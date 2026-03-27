#!/usr/bin/env python3
"""
Enrichissement téléphones Toulouse - BATCH 2 (index 700 à 2684)
"""

import json
import re
import time
import urllib.parse
import urllib.request
from difflib import SequenceMatcher

# ── helpers ──────────────────────────────────────────────────────────────────

def normalize_name(name):
    if not name:
        return ""
    name = name.upper()
    name = re.sub(r'\b(SARL|SAS|SA|EURL|SCI|SASU|SNC|ETS|ETABLISSEMENTS?)\b', '', name)
    name = re.sub(r'[^A-Z0-9\s]', ' ', name)
    return re.sub(r'\s+', ' ', name).strip()

def fmt_phone(p):
    if not p:
        return ""
    d = re.sub(r'[^\d]', '', str(p))
    if d.startswith('33') and len(d) == 11:
        d = '0' + d[2:]
    if len(d) == 10 and d.startswith('0'):
        return f"{d[0:2]} {d[2:4]} {d[4:6]} {d[6:8]} {d[8:10]}"
    return str(p)

def similarity(a, b):
    return SequenceMatcher(None, a, b).ratio()

# ── load data ─────────────────────────────────────────────────────────────────

print("Chargement des données...")

with open('/home/user/Website01/entreprises_auto_moto_evry_toulouse_area.json', encoding='utf-8') as f:
    all_entries = json.load(f)

# Filter Toulouse entries
toulouse_entries = [e for e in all_entries if str(e.get('ville', '')).upper() == 'TOULOUSE']
print(f"  Entrées Toulouse totales: {len(toulouse_entries)}")

# Batch 2: indices 700 à 2684
batch = toulouse_entries[700:2685]
print(f"  Batch 2 (700-2684): {len(batch)} entrées")

# Filter entries without phone
no_phone = [e for e in batch if not e.get('telephone') or str(e.get('telephone', '')).strip() == '']
print(f"  Sans téléphone: {len(no_phone)} entrées")

# ── load PJ data ──────────────────────────────────────────────────────────────

pj_entries = []

# pj_results_toulouse.json (list) - fields: nom_pj, code_postal_pj, telephone
try:
    with open('/home/user/Website01/pj_results_toulouse.json', encoding='utf-8') as f:
        data = json.load(f)
    if isinstance(data, list):
        pj_entries.extend(data)
        print(f"  pj_results_toulouse.json: {len(data)} entrées")
except Exception as e:
    print(f"  ERREUR pj_results_toulouse.json: {e}")

# pj_cache_toulouse.json (dict de listes par catégorie)
try:
    with open('/home/user/Website01/pj_cache_toulouse.json', encoding='utf-8') as f:
        cache_data = json.load(f)
    count_before = len(pj_entries)
    if isinstance(cache_data, dict):
        for key, val in cache_data.items():
            if isinstance(val, list):
                pj_entries.extend(val)
    elif isinstance(cache_data, list):
        pj_entries.extend(cache_data)
    print(f"  pj_cache_toulouse.json: {len(pj_entries) - count_before} entrées ajoutées")
except Exception as e:
    print(f"  ERREUR pj_cache_toulouse.json: {e}")

print(f"  Total PJ entries (from pj files): {len(pj_entries)}")

# enriched_toulouse_pj.json - separate structure: fields nom, code_postal, telephone
try:
    with open('/home/user/Website01/enriched_toulouse_pj.json', encoding='utf-8') as f:
        enriched_pj = json.load(f)
    print(f"  enriched_toulouse_pj.json: {len(enriched_pj)} entrées")
except Exception as e:
    print(f"  ERREUR enriched_toulouse_pj.json: {e}")
    enriched_pj = []

print(f"\n  Sample PJ raw entry keys: {list(pj_entries[0].keys()) if pj_entries else 'N/A'}")
print(f"  Sample enriched entry keys: {list(enriched_pj[0].keys()) if enriched_pj else 'N/A'}")

# ── build index ───────────────────────────────────────────────────────────────

# Index PJ entries (pj_results + pj_cache) by code_postal_pj
pj_by_cp = {}
for entry in pj_entries:
    cp = str(entry.get('code_postal_pj', '')).strip()
    if not cp:
        cp = '__UNKNOWN__'
    if cp not in pj_by_cp:
        pj_by_cp[cp] = []
    pj_by_cp[cp].append(entry)

# Index enriched_toulouse_pj by code_postal
enriched_by_cp = {}
for entry in enriched_pj:
    cp = str(entry.get('code_postal', '')).strip()
    if not cp:
        cp = '__UNKNOWN__'
    if cp not in enriched_by_cp:
        enriched_by_cp[cp] = []
    enriched_by_cp[cp].append(entry)

print(f"\n  PJ codes postaux: {list(pj_by_cp.keys())[:10]}")
print(f"  Enriched codes postaux: {list(enriched_by_cp.keys())[:10]}")

# ── matching function ─────────────────────────────────────────────────────────

def get_pj_phone(entry_nom, entry_cp):
    """Chercher téléphone dans PJ par similarité nom + même CP"""
    norm_target = normalize_name(entry_nom)
    if not norm_target:
        return None, 0.0

    cp_str = str(entry_cp).strip()
    best_score = 0.0
    best_phone = None

    # Search in pj_results + pj_cache (nom_pj field)
    candidates = pj_by_cp.get(cp_str, []) + pj_by_cp.get('__UNKNOWN__', [])

    for pj in candidates:
        pj_nom = str(pj.get('nom_pj', '') or '')
        norm_pj = normalize_name(pj_nom)
        if not norm_pj:
            continue
        score = similarity(norm_target, norm_pj)
        if score > best_score:
            best_score = score
            phone_raw = str(pj.get('telephone', '') or '')
            if phone_raw:
                best_phone = phone_raw

    # Also search in enriched_toulouse_pj (nom field)
    candidates2 = enriched_by_cp.get(cp_str, []) + enriched_by_cp.get('__UNKNOWN__', [])

    for pj in candidates2:
        pj_nom = str(pj.get('nom', '') or '')
        norm_pj = normalize_name(pj_nom)
        if not norm_pj:
            continue
        score = similarity(norm_target, norm_pj)
        if score > best_score:
            best_score = score
            phone_raw = str(pj.get('telephone', '') or '')
            if phone_raw:
                best_phone = phone_raw

    if best_score >= 0.65 and best_phone:
        return fmt_phone(best_phone), best_score

    return None, best_score

# ── API function ──────────────────────────────────────────────────────────────

def api_search_phone(nom, siret):
    """Rechercher téléphone via API gouvernementale"""
    url = f"https://recherche-entreprises.api.gouv.fr/search?q={urllib.parse.quote(nom)}&per_page=3"

    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))

            results = data.get('results', [])
            if not results:
                return None

            # Check first result SIRET match
            first = results[0]
            first_siret = str(first.get('siret', first.get('siren', '')))
            target_siret = str(siret or '')

            if target_siret and (first_siret == target_siret or
                                  first_siret[:9] == target_siret[:9]):
                # Try to extract phone from matching etablissement
                etablissements = first.get('matching_etablissements', [])
                for etab in etablissements:
                    phone = etab.get('telephone', '')
                    if phone:
                        return fmt_phone(str(phone))
                # Also check at root level
                phone = first.get('telephone', '')
                if phone:
                    return fmt_phone(str(phone))

            return None

        except urllib.error.HTTPError as e:
            if e.code == 429:
                print(f"    Rate limit (429), attente 5s...")
                time.sleep(5)
            else:
                return None
        except Exception:
            return None

    return None

# ── main processing ───────────────────────────────────────────────────────────

print(f"\nTraitement de {len(no_phone)} entrées sans téléphone...")
print("─" * 60)

results = []
found_pj = 0
found_api = 0
processed = 0

for i, entry in enumerate(no_phone):
    siret = entry.get('siret', '')
    nom = entry.get('nom', '')
    cp = str(entry.get('code_postal', ''))

    if i % 200 == 0:
        print(f"  [{i}/{len(no_phone)}] PJ: {found_pj}, API: {found_api}")

    processed += 1

    # Step 1: PJ matching
    phone_pj, score = get_pj_phone(nom, cp)

    if phone_pj:
        found_pj += 1
        results.append({
            "siret": siret,
            "telephone": phone_pj,
            "source_telephone": "PJ_match"
        })
        continue

    # Step 2: API search
    if nom and siret:
        time.sleep(0.2)
        phone_api = api_search_phone(nom, siret)
        if phone_api:
            found_api += 1
            results.append({
                "siret": siret,
                "telephone": phone_api,
                "source_telephone": "API"
            })

print(f"\n{'─' * 60}")
print(f"Traitement terminé:")
print(f"  Entrées traitées:      {processed}")
print(f"  Téléphones PJ:         {found_pj}")
print(f"  Téléphones API:        {found_api}")
print(f"  Total enrichissements: {len(results)}")

# ── save results ──────────────────────────────────────────────────────────────

output_path = '/home/user/Website01/agent_out_8_phones_toulouse_2.json'
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(f"\nRésultats sauvegardés: {output_path}")
