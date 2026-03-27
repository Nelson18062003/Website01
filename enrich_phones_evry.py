#!/usr/bin/env python3
"""
Agent d'enrichissement de téléphones pour Évry/Colomiers/Muret/Blagnac
Stratégie:
  1. Correspondance directe SIRET dans les fichiers 118000
  2. Fuzzy matching PJ (exact CP + dept CP avec seuils différenciés)
  3. Appel API Recherche Entreprises (ne retourne pas de téléphone - confirmé)
"""
import json
import re
import time
import urllib.request
import urllib.parse
from difflib import SequenceMatcher

# ============================================================
# NORMALISATION
# ============================================================

def normalize_name(name):
    if not name:
        return ""
    name = name.upper()
    name = re.sub(r'\b(SARL|SAS|SA|EURL|SCI|SASU|SNC|ETS|ETABLISSEMENTS?)\b', '', name)
    name = re.sub(r'[^A-Z0-9\s]', ' ', name)
    return re.sub(r'\s+', ' ', name).strip()


def fuzzy_score(a, b):
    return SequenceMatcher(None, a, b).ratio()


def normalize_phone(phone):
    if not phone:
        return None
    phone = re.sub(r'[^\d+]', '', str(phone))
    # French format: convert +33XXXXXXXXX → 0XXXXXXXXX
    if phone.startswith('+33') and len(phone) == 12:
        phone = '0' + phone[3:]
    if phone.startswith('33') and len(phone) == 11:
        phone = '0' + phone[2:]
    if len(phone) == 10 and phone.startswith('0'):
        formatted = ' '.join([phone[i:i+2] for i in range(0, 10, 2)])
        return formatted
    return phone if phone else None


# ============================================================
# CP VALID SETS PER CITY
# ============================================================

# Primary CPs for each city
CITY_EXACT_CP = {
    'EVRY-COURCOURONNES': {'91000', '91080'},
    'BLAGNAC': {'31700'},
    'COLOMIERS': {'31770'},
    'MURET': {'31600'},
}

# Department prefix per city
CITY_DEPT = {
    'EVRY-COURCOURONNES': '91',
    'BLAGNAC': '31',
    'COLOMIERS': '31',
    'MURET': '31',
}


# ============================================================
# CHARGEMENT DES DONNÉES
# ============================================================

def load_json(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"  [WARN] File not found: {path}")
        return None
    except Exception as e:
        print(f"  [ERROR] Cannot load {path}: {e}")
        return None


def load_main_database():
    data = load_json('/home/user/Website01/entreprises_auto_moto_evry_toulouse_area.json')
    if not data:
        return []
    non_toulouse = [e for e in data if e.get('ville', '').upper() != 'TOULOUSE']
    print(f"Base principale: {len(non_toulouse)} entrées hors Toulouse")
    return non_toulouse


def build_pj_lookup():
    """Build list of PJ entries with phone from all PJ result and cache files"""
    pj_entries = []

    # PJ results files (raw search results)
    for fname in [
        'pj_results_evry.json',
        'pj_results_blagnac.json',
        'pj_results_colomiers.json',
        'pj_results_muret.json',
    ]:
        data = load_json(f'/home/user/Website01/{fname}')
        if data:
            added = 0
            for item in data:
                if item.get('telephone') and item.get('nom_pj'):
                    pj_entries.append(item)
                    added += 1
            print(f"  PJ {fname}: {len(data)} items, {added} avec tel")

    # PJ cache files (broader area searches)
    for fname in [
        'pj_cache_evry.json',
        'pj_cache_blagnac.json',
        'pj_cache_colomiers.json',
        'pj_cache_muret.json',
    ]:
        data = load_json(f'/home/user/Website01/{fname}')
        if data and isinstance(data, dict):
            added = 0
            for cat, items in data.items():
                for item in items:
                    if item.get('telephone') and item.get('nom_pj'):
                        pj_entries.append(item)
                        added += 1
            print(f"  Cache {fname}: {sum(len(v) for v in data.values())} items, {added} avec tel")

    print(f"Total entrées PJ avec téléphone: {len(pj_entries)}")
    return pj_entries


def build_118000_lookup():
    """Build siret→phone lookup from 118000 enriched files (direct SIRET match)"""
    lookup = {}
    for fname in [
        'enriched_evry_118000.json',
        'enriched_blagnac_118000.json',
        'enriched_colomiers_118000.json',
        'enriched_muret_118000.json',
    ]:
        data = load_json(f'/home/user/Website01/{fname}')
        if data:
            added = 0
            for item in data:
                siret = item.get('siret')
                phone = item.get('telephone', '').strip()
                if siret and phone:
                    lookup[siret] = phone
                    added += 1
            print(f"  118000 {fname}: {added} avec tel")
    print(f"Total SIRET avec téléphone 118000: {len(lookup)}")
    return lookup


# ============================================================
# FUZZY MATCHING
# ============================================================

def find_pj_phone(entry, pj_entries, threshold_exact=0.65, threshold_dept=0.80):
    """
    Find phone in PJ data by fuzzy matching name + postal code.

    Two-tier matching:
    - Exact CP match: threshold 0.65 (more permissive - same city)
    - Dept CP match: threshold 0.80 (strict - different city, same dept)
    """
    name_norm = normalize_name(entry.get('nom', ''))
    cp = str(entry.get('code_postal', '')).strip()
    ville = entry.get('ville', '').upper()

    if not name_norm:
        return None, None, 0

    # Get valid CPs and department for this city
    valid_cps = CITY_EXACT_CP.get(ville, {cp})
    dept = CITY_DEPT.get(ville, cp[:2] if len(cp) >= 2 else '')

    best_exact_score = 0
    best_exact_pj = None
    best_dept_score = 0
    best_dept_pj = None

    for pj in pj_entries:
        pj_cp = str(pj.get('code_postal_pj', '')).strip()
        pj_phone = pj.get('telephone', '').strip()

        if not pj_phone:
            continue

        pj_name_norm = normalize_name(pj.get('nom_pj', ''))
        if not pj_name_norm:
            continue

        score = fuzzy_score(name_norm, pj_name_norm)

        if pj_cp in valid_cps:
            # Exact CP match (same city)
            if score > best_exact_score:
                best_exact_score = score
                best_exact_pj = pj
        elif dept and pj_cp.startswith(dept):
            # Same department but different city
            if score > best_dept_score:
                best_dept_score = score
                best_dept_pj = pj

    # Return best match, preferring exact CP
    if best_exact_score >= threshold_exact:
        return best_exact_pj.get('telephone'), best_exact_pj.get('nom_pj'), best_exact_score
    if best_dept_score >= threshold_dept:
        return best_dept_pj.get('telephone'), best_dept_pj.get('nom_pj'), best_dept_score

    return None, None, max(best_exact_score, best_dept_score)


# ============================================================
# API RECHERCHE ENTREPRISES (validation uniquement - ne retourne pas de tél)
# ============================================================

def search_api_entreprises(nom, siret=None):
    """
    Search Recherche Entreprises API.
    Note: The SIRENE API does NOT contain phone numbers.
    This function is kept for potential future enrichment but returns None.
    """
    return None


# ============================================================
# MAIN ENRICHMENT LOGIC
# ============================================================

def main():
    print("=" * 60)
    print("AGENT ENRICHISSEMENT TÉLÉPHONES - EVRY/COLOMIERS/MURET/BLAGNAC")
    print("=" * 60)

    # 1. Load data
    print("\n[1] Chargement base principale...")
    non_toulouse = load_main_database()

    print("\n[2] Chargement données PJ...")
    pj_entries = build_pj_lookup()

    print("\n[3] Chargement données 118000...")
    lookup_118000 = build_118000_lookup()

    # 2. Identify entries without phone
    without_phone = [e for e in non_toulouse if not e.get('telephone')]
    with_phone_already = [e for e in non_toulouse if e.get('telephone')]
    print(f"\nEntrées sans téléphone: {len(without_phone)}")
    print(f"Entrées avec téléphone: {len(with_phone_already)}")

    results = []
    stats = {'118000': 0, 'pj_exact': 0, 'pj_dept': 0, 'not_found': 0}

    # 3. Direct SIRET match with 118000 data
    print("\n[4] Enrichissement par SIRET direct (118000)...")
    remaining = []
    for entry in without_phone:
        siret = entry.get('siret')
        if siret and siret in lookup_118000:
            phone = normalize_phone(lookup_118000[siret])
            if phone:
                results.append({
                    'siret': siret,
                    'telephone': phone,
                    'source_telephone': '118000',
                    '_nom': entry.get('nom'),
                    '_ville': entry.get('ville'),
                })
                stats['118000'] += 1
                continue
        remaining.append(entry)

    print(f"  Trouvés via 118000: {stats['118000']}, restants: {len(remaining)}")

    # 4. Fuzzy matching PJ (exact CP threshold=0.65, dept threshold=0.80)
    print("\n[5] Fuzzy matching PJ (exact CP >=0.65 / même dept >=0.80)...")
    still_remaining = []
    for entry in remaining:
        phone, match_name, score = find_pj_phone(
            entry, pj_entries,
            threshold_exact=0.65,
            threshold_dept=0.80
        )
        if phone:
            phone_norm = normalize_phone(phone)
            if phone_norm:
                # Determine source type
                cp = str(entry.get('code_postal', '')).strip()
                ville = entry.get('ville', '').upper()
                valid_cps = CITY_EXACT_CP.get(ville, {cp})
                results.append({
                    'siret': entry.get('siret'),
                    'telephone': phone_norm,
                    'source_telephone': 'PJ',
                    '_nom': entry.get('nom'),
                    '_ville': entry.get('ville'),
                    '_match_name': match_name,
                    '_match_score': round(score, 3),
                })
                stats['pj_exact'] += 1
                continue
        still_remaining.append(entry)

    print(f"  Trouvés via PJ fuzzy: {stats['pj_exact']}, restants: {len(still_remaining)}")
    stats['not_found'] = len(still_remaining)

    # 5. Summary
    total_enriched = stats['118000'] + stats['pj_exact']
    print("\n" + "=" * 60)
    print("RÉSUMÉ:")
    print(f"  118000 (SIRET direct): {stats['118000']}")
    print(f"  PJ (fuzzy):            {stats['pj_exact']}")
    print(f"  Non trouvés:           {stats['not_found']}")
    print(f"  TOTAL enrichis:        {total_enriched}")
    print("=" * 60)

    # 6. Save output (format: siret, telephone, source_telephone)
    output = []
    seen_sirets = set()
    for r in results:
        siret = r.get('siret')
        if siret and siret not in seen_sirets:
            seen_sirets.add(siret)
            output.append({
                'siret': siret,
                'telephone': r['telephone'],
                'source_telephone': r['source_telephone'],
            })

    output_path = '/home/user/Website01/agent_out_9_phones_evry.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nFichier sauvegardé: {output_path}")
    print(f"Total entrées: {len(output)}")

    # Show sample with details
    print("\nDétail des enrichissements (avec contexte):")
    for r in results[:15]:
        print(f"  [{r['source_telephone']}] {r['_nom']} | tel: {r['telephone']}", end='')
        if r.get('_match_name'):
            print(f" | via: {r['_match_name']} (score={r.get('_match_score','')})", end='')
        print()

    return output


if __name__ == '__main__':
    main()
