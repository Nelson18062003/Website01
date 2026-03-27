#!/usr/bin/env python3
"""
Agent d'enrichissement de téléphones pour Évry/Colomiers/Muret/Blagnac
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
    # French format: convert 33XXXXXXXXX → 0XXXXXXXXX
    if phone.startswith('33') and len(phone) == 11:
        phone = '0' + phone[2:]
    if phone.startswith('+33') and len(phone) == 12:
        phone = '0' + phone[3:]
    if len(phone) == 10 and phone.startswith('0'):
        formatted = ' '.join([phone[i:i+2] for i in range(0, 10, 2)])
        return formatted
    return phone if phone else None


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
    # Filter non-toulouse
    non_toulouse = [e for e in data if e.get('ville', '').upper() != 'TOULOUSE']
    print(f"Base principale: {len(non_toulouse)} entrées hors Toulouse")
    return non_toulouse


def build_pj_lookup():
    """Build a unified lookup: list of dicts with nom_pj, telephone, code_postal_pj, ville_pj"""
    pj_entries = []

    # PJ results files
    for fname, city_hint in [
        ('pj_results_evry.json', 'EVRY'),
        ('pj_results_blagnac.json', 'BLAGNAC'),
        ('pj_results_colomiers.json', 'COLOMIERS'),
        ('pj_results_muret.json', 'MURET'),
    ]:
        data = load_json(f'/home/user/Website01/{fname}')
        if data:
            for item in data:
                if item.get('telephone'):
                    pj_entries.append(item)
            print(f"  PJ {fname}: {len(data)} items, {sum(1 for x in data if x.get('telephone'))} avec tel")

    # PJ cache files
    for fname in ['pj_cache_evry.json', 'pj_cache_blagnac.json', 'pj_cache_colomiers.json', 'pj_cache_muret.json']:
        data = load_json(f'/home/user/Website01/{fname}')
        if data and isinstance(data, dict):
            for cat, items in data.items():
                for item in items:
                    if item.get('telephone'):
                        pj_entries.append(item)
            total = sum(len(v) for v in data.values())
            with_tel = sum(1 for v in data.values() for x in v if x.get('telephone'))
            print(f"  Cache {fname}: {total} items, {with_tel} avec tel")

    # Enriched PJ files (those may have PJ matches with phones)
    for fname in ['enriched_evry_pj.json', 'enriched_blagnac_pj.json',
                  'enriched_colomiers_pj.json', 'enriched_muret_pj.json']:
        data = load_json(f'/home/user/Website01/{fname}')
        if data:
            for item in data:
                if item.get('telephone') and item.get('nom_pj'):
                    # Already in siret-indexed format, adapt
                    pj_entries.append({
                        'nom_pj': item.get('nom_pj', ''),
                        'telephone': item.get('telephone', ''),
                        'code_postal_pj': item.get('code_postal_pj', item.get('code_postal', '')),
                        'ville_pj': item.get('ville_pj', item.get('ville', '')),
                        'adresse_pj': item.get('adresse_pj', ''),
                        '_siret': item.get('siret'),  # direct match possible
                    })
            print(f"  Enriched PJ {fname}: {sum(1 for x in data if x.get('telephone') and x.get('nom_pj'))} avec tel+nom_pj")

    print(f"Total entrées PJ avec téléphone: {len(pj_entries)}")
    return pj_entries


def build_118000_lookup():
    """Build siret→phone lookup from 118000 enriched files"""
    lookup = {}
    for fname in ['enriched_evry_118000.json', 'enriched_blagnac_118000.json',
                  'enriched_colomiers_118000.json', 'enriched_muret_118000.json']:
        data = load_json(f'/home/user/Website01/{fname}')
        if data:
            for item in data:
                siret = item.get('siret')
                phone = item.get('telephone')
                if siret and phone and phone.strip():
                    lookup[siret] = phone.strip()
            print(f"  118000 {fname}: {sum(1 for x in data if x.get('telephone') and x.get('telephone').strip())} avec tel")
    print(f"Total SIRET avec téléphone 118000: {len(lookup)}")
    return lookup


def build_siret_phone_map(non_toulouse):
    """Build siret→phone from already enriched entries in main database"""
    siret_map = {}
    for e in non_toulouse:
        siret = e.get('siret')
        phone = e.get('telephone')
        if siret and phone:
            siret_map[siret] = phone
    return siret_map


# ============================================================
# FUZZY MATCHING
# ============================================================

def find_pj_phone(entry, pj_entries, threshold=0.65):
    """Find phone in PJ data by fuzzy matching name + postal code"""
    name_norm = normalize_name(entry.get('nom', ''))
    cp = str(entry.get('code_postal', '')).strip()

    if not name_norm:
        return None, None, 0

    best_score = 0
    best_phone = None
    best_match_name = None

    for pj in pj_entries:
        pj_cp = str(pj.get('code_postal_pj', '')).strip()
        pj_phone = pj.get('telephone', '').strip()

        if not pj_phone:
            continue

        # Postal code filter: must match or be nearby
        # For Evry, various codes: 91000, 91080, etc.
        # Allow if same first 2 digits (same department) or exact match
        cp_match = False
        if cp and pj_cp:
            if cp == pj_cp:
                cp_match = True
            elif cp[:2] == pj_cp[:2]:  # same department
                cp_match = True
        elif not cp or not pj_cp:
            cp_match = True  # unknown, allow

        if not cp_match:
            continue

        pj_name_norm = normalize_name(pj.get('nom_pj', ''))
        if not pj_name_norm:
            continue

        score = fuzzy_score(name_norm, pj_name_norm)
        if score > best_score:
            best_score = score
            best_phone = pj_phone
            best_match_name = pj.get('nom_pj')

    if best_score >= threshold:
        return best_phone, best_match_name, best_score
    return None, None, best_score


# ============================================================
# API RECHERCHE ENTREPRISES
# ============================================================

def search_api_entreprises(nom, siret=None):
    """
    Search the Recherche Entreprises API for phone number.
    Returns phone or None.
    """
    try:
        # Try by SIRET first
        if siret:
            url = f"https://recherche-entreprises.api.gouv.fr/search?q={urllib.parse.quote(siret)}&per_page=1"
        else:
            url = f"https://recherche-entreprises.api.gouv.fr/search?q={urllib.parse.quote(nom)}&per_page=3"

        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))

        results = data.get('results', [])
        if not results:
            return None

        # Try to match by siret
        if siret:
            for r in results:
                for etab in r.get('matching_etablissements', []):
                    if etab.get('siret') == siret:
                        phone = etab.get('telephone') or r.get('telephone')
                        if phone:
                            return phone
                # Also check siege
                if r.get('siege', {}).get('siret') == siret:
                    phone = r.get('siege', {}).get('telephone') or r.get('telephone')
                    if phone:
                        return phone

        # Fallback: take first result phone
        r = results[0]
        phone = (r.get('siege', {}) or {}).get('telephone') or r.get('telephone')
        return phone

    except Exception as e:
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
    stats = {'pj': 0, '118000': 0, 'api': 0, 'not_found': 0}

    print("\n[4] Enrichissement par SIRET (118000 direct)...")
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
                    'nom': entry.get('nom'),
                    'ville': entry.get('ville'),
                })
                stats['118000'] += 1
                continue
        remaining.append(entry)

    print(f"  Trouvés via 118000: {stats['118000']}, restants: {len(remaining)}")

    print("\n[5] Fuzzy matching PJ...")
    still_remaining = []
    for entry in remaining:
        phone, match_name, score = find_pj_phone(entry, pj_entries, threshold=0.65)
        if phone:
            phone_norm = normalize_phone(phone)
            if phone_norm:
                results.append({
                    'siret': entry.get('siret'),
                    'telephone': phone_norm,
                    'source_telephone': 'PJ',
                    'nom': entry.get('nom'),
                    'ville': entry.get('ville'),
                    '_match_name': match_name,
                    '_match_score': round(score, 3),
                })
                stats['pj'] += 1
                continue
        still_remaining.append(entry)

    print(f"  Trouvés via PJ fuzzy: {stats['pj']}, restants: {len(still_remaining)}")

    print(f"\n[6] API Recherche Entreprises pour {len(still_remaining)} entrées restantes...")
    for i, entry in enumerate(still_remaining):
        nom = entry.get('nom', '')
        siret = entry.get('siret')

        if i % 20 == 0:
            print(f"  ... {i}/{len(still_remaining)} traités, {stats['api']} trouvés")

        phone = search_api_entreprises(nom, siret)
        time.sleep(0.2)

        if phone:
            phone_norm = normalize_phone(phone)
            if phone_norm:
                results.append({
                    'siret': siret,
                    'telephone': phone_norm,
                    'source_telephone': 'API',
                    'nom': nom,
                    'ville': entry.get('ville'),
                })
                stats['api'] += 1
            else:
                stats['not_found'] += 1
        else:
            stats['not_found'] += 1

    print(f"  Trouvés via API: {stats['api']}")

    # 3. Summary
    print("\n" + "=" * 60)
    print("RÉSUMÉ:")
    print(f"  118000:   {stats['118000']}")
    print(f"  PJ:       {stats['pj']}")
    print(f"  API:      {stats['api']}")
    print(f"  Non trouvés: {stats['not_found']}")
    print(f"  TOTAL enrichis: {len(results)}")
    print("=" * 60)

    # 4. Save output (only new enrichments: siret, telephone, source_telephone)
    output = []
    seen_sirets = set()
    for r in results:
        siret = r['siret']
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

    # Show sample
    print("\nEchantillon résultats:")
    for r in output[:5]:
        print(f"  {r}")

    return output


if __name__ == '__main__':
    main()
