#!/usr/bin/env python3
"""
Enrich garages with phone numbers from OpenStreetMap data.

Strategy:
1. Load existing garages from Excel
2. Load OSM garage data with phone numbers
3. Build city→postcode mapping from Excel to resolve OSM entries missing postcodes
4. Match garages by:
   a. Exact/fuzzy name match within same postal code
   b. Address-based matching within same postal code
   c. Match by city name (both OSM entries with and without postcode)
   d. Name-contains matching for brand/chain garages
5. Update Excel file with found phone numbers
"""

import json
import re
import sys
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

# =============================================================================
# Configuration
# =============================================================================

EXCEL_FILE = "garages_auto_zones_france.xlsx"
OSM_FILE = "osm_garages_phones.json"
OUTPUT_FILE = "garages_auto_zones_france.xlsx"

# =============================================================================
# Name normalization
# =============================================================================

STOP_WORDS = {
    "garage", "garages", "auto", "automobile", "automobiles", "sarl", "sas",
    "eurl", "sa", "srl", "et", "de", "du", "des", "le", "la", "les", "l",
    "un", "une", "en", "au", "aux", "par", "pour", "sur", "chez", "fils",
    "ets", "etablissements", "monsieur", "madame", "mr", "mme", "m",
    "reparation", "entretien", "mecanique", "carrosserie", "service",
    "services", "centre", "atelier", "station", "point", "agent",
    "concessionnaire", "concession", "vente", "france", "international",
    "group", "groupe", "societe", "ste", "société",
}

# Known brand/chain names that appear in both OSM and enterprise data
BRAND_NAMES = {
    "renault", "peugeot", "citroen", "citroën", "norauto", "speedy", "midas",
    "feu vert", "euromaster", "point s", "autobilan", "dekra", "securitest",
    "delko", "toyota", "ford", "volkswagen", "opel", "audi", "bmw", "mercedes",
    "fiat", "dacia", "nissan", "hyundai", "kia", "suzuki", "mazda", "volvo",
    "skoda", "seat", "carglass", "roady", "carter cash", "vulco", "siligom",
    "first stop", "profil plus", "bestdrive", "autovision",
}


def normalize_name(name):
    """Normalize a business name for matching."""
    if not name:
        return ""
    n = str(name).lower().strip()
    n = re.sub(r'\([^)]*\)', '', n)
    n = re.sub(r'[^a-z0-9àâäéèêëïîôùûüÿçœæ]', ' ', n)
    n = n.replace('é', 'e').replace('è', 'e').replace('ê', 'e').replace('ë', 'e')
    n = n.replace('à', 'a').replace('â', 'a').replace('ä', 'a')
    n = n.replace('ù', 'u').replace('û', 'u').replace('ü', 'u')
    n = n.replace('î', 'i').replace('ï', 'i')
    n = n.replace('ô', 'o').replace('ç', 'c')
    n = n.replace('œ', 'oe').replace('æ', 'ae').replace('ÿ', 'y')
    n = re.sub(r'\s+', ' ', n).strip()
    return n


def name_tokens(name):
    """Get significant tokens from a normalized name."""
    normalized = normalize_name(name)
    tokens = set(normalized.split())
    tokens = {t for t in tokens if t not in STOP_WORDS and len(t) > 1}
    return tokens


def name_similarity(name1, name2):
    """Token-based similarity (Jaccard index)."""
    tokens1 = name_tokens(name1)
    tokens2 = name_tokens(name2)
    if not tokens1 or not tokens2:
        return 0.0
    intersection = tokens1 & tokens2
    union = tokens1 | tokens2
    return len(intersection) / len(union) if union else 0.0


def name_contains_check(name1, name2):
    """Check if significant tokens of one name are contained in the other."""
    tokens1 = name_tokens(name1)
    tokens2 = name_tokens(name2)
    if not tokens1 or not tokens2:
        return False
    # One name's tokens are a subset of the other's
    return tokens1.issubset(tokens2) or tokens2.issubset(tokens1)


def extract_brand(name):
    """Extract known brand name from a business name."""
    name_lower = normalize_name(name)
    for brand in BRAND_NAMES:
        brand_norm = normalize_name(brand)
        if brand_norm in name_lower:
            return brand_norm
    return None


def normalize_address(addr):
    """Normalize an address for matching."""
    if not addr:
        return ""
    a = str(addr).lower().strip()
    # Remove common prefixes
    a = re.sub(r'^(za|zi|zac|zae|zone)\s+', '', a)
    a = re.sub(r'[^a-z0-9àâäéèêëïîôùûüÿçœæ]', ' ', a)
    # Normalize abbreviations
    a = re.sub(r'\brue\b', 'r', a)
    a = re.sub(r'\bavenue\b', 'av', a)
    a = re.sub(r'\bboulevard\b', 'bd', a)
    a = re.sub(r'\bchemin\b', 'ch', a)
    a = re.sub(r'\broute\b', 'rt', a)
    a = re.sub(r'\bplace\b', 'pl', a)
    a = re.sub(r'\bimpasse\b', 'imp', a)
    a = re.sub(r'\ballée\b', 'al', a)
    a = re.sub(r'\ballee\b', 'al', a)
    a = re.sub(r'\s+', ' ', a).strip()
    return a


def address_similarity(addr1, addr2):
    """Calculate address similarity using token overlap."""
    a1 = normalize_address(addr1)
    a2 = normalize_address(addr2)
    if not a1 or not a2:
        return 0.0
    tokens1 = set(a1.split())
    tokens2 = set(a2.split())
    # Remove very short tokens (numbers under 3 chars are OK for street numbers)
    tokens1 = {t for t in tokens1 if len(t) > 1}
    tokens2 = {t for t in tokens2 if len(t) > 1}
    if not tokens1 or not tokens2:
        return 0.0
    intersection = tokens1 & tokens2
    union = tokens1 | tokens2
    return len(intersection) / len(union) if union else 0.0


def normalize_city(city):
    """Normalize city name for matching."""
    if not city:
        return ""
    c = str(city).lower().strip()
    c = re.sub(r'[^a-z0-9àâäéèêëïîôùûüÿçœæ]', ' ', c)
    c = c.replace('é', 'e').replace('è', 'e').replace('ê', 'e').replace('ë', 'e')
    c = c.replace('à', 'a').replace('â', 'a').replace('ä', 'a')
    c = c.replace('ù', 'u').replace('û', 'u').replace('ü', 'u')
    c = c.replace('î', 'i').replace('ï', 'i')
    c = c.replace('ô', 'o').replace('ç', 'c')
    c = c.replace('œ', 'oe').replace('æ', 'ae').replace('ÿ', 'y')
    c = re.sub(r'\bsaint\b', 'st', c)
    c = re.sub(r'\bsainte\b', 'ste', c)
    c = re.sub(r'\s+', ' ', c).strip()
    return c


def format_phone_international(phone):
    """Convert French phone to international format +33 X XX XX XX XX."""
    if not phone:
        return ""
    p = str(phone).strip()
    # Handle multiple numbers separated by ; or /
    if ';' in p:
        p = p.split(';')[0].strip()
    if '/' in p:
        p = p.split('/')[0].strip()

    digits = re.sub(r'[^\d+]', '', p)
    if digits.startswith('+33'):
        digits = '0' + digits[3:]
    elif digits.startswith('0033'):
        digits = '0' + digits[4:]
    elif digits.startswith('33') and len(digits) == 11:
        digits = '0' + digits[2:]

    digits = re.sub(r'[^\d]', '', digits)

    if digits.startswith('0') and len(digits) == 10:
        return f"+33 {digits[1]} {digits[2:4]} {digits[4:6]} {digits[6:8]} {digits[8:10]}"
    elif len(digits) == 9 and not digits.startswith('0'):
        return f"+33 {digits[0]} {digits[1:3]} {digits[3:5]} {digits[5:7]} {digits[7:9]}"

    return p


# =============================================================================
# Load data
# =============================================================================

def load_osm_data(filepath, city_to_postcode):
    """Load OSM data, resolve missing postcodes using city mapping."""
    with open(filepath, "r", encoding="utf-8") as f:
        elements = json.load(f)

    osm_by_postcode = {}
    osm_by_city = {}
    total_phones = 0
    resolved_postcodes = 0

    for elem in elements:
        tags = elem.get("tags", {})
        name = tags.get("name", "")
        phone = tags.get("phone", "") or tags.get("contact:phone", "")
        postcode = tags.get("addr:postcode", "")
        city = tags.get("addr:city", "") or tags.get("addr:commune", "")
        street = tags.get("addr:street", "")

        if not name or not phone:
            continue

        total_phones += 1

        # Try to resolve missing postcode from city name
        if not postcode and city:
            city_norm = normalize_city(city)
            if city_norm in city_to_postcode:
                postcode = city_to_postcode[city_norm]
                resolved_postcodes += 1

        entry = {
            "name": name,
            "phone": phone,
            "postcode": postcode,
            "city": city,
            "street": street,
            "osm_id": elem.get("id", ""),
        }

        if postcode:
            osm_by_postcode.setdefault(postcode, []).append(entry)
        if city:
            city_norm = normalize_city(city)
            osm_by_city.setdefault(city_norm, []).append(entry)

    print(f"  OSM entries with phone: {total_phones}")
    print(f"  Postcodes resolved from city: {resolved_postcodes}")
    print(f"  Unique postal codes: {len(osm_by_postcode)}")
    print(f"  Unique cities: {len(osm_by_city)}")

    return osm_by_postcode, osm_by_city


def build_city_postcode_mapping(ws):
    """Build city→postcode mapping from Excel data."""
    mapping = {}
    for row in range(2, ws.max_row + 1):
        city = str(ws.cell(row=row, column=5).value or "")
        postcode = str(ws.cell(row=row, column=4).value or "")
        if city and postcode:
            city_norm = normalize_city(city)
            if city_norm not in mapping:
                mapping[city_norm] = postcode
    return mapping


def load_garages_from_excel(filepath):
    """Load garage data from Excel."""
    wb = openpyxl.load_workbook(filepath)
    ws = wb.active

    garages = []
    for row in range(2, ws.max_row + 1):
        garage = {
            "row": row,
            "name": str(ws.cell(row=row, column=2).value or ""),
            "address": str(ws.cell(row=row, column=3).value or ""),
            "postal_code": str(ws.cell(row=row, column=4).value or ""),
            "city": str(ws.cell(row=row, column=5).value or ""),
            "dept_num": str(ws.cell(row=row, column=6).value or ""),
            "phone_intl": str(ws.cell(row=row, column=10).value or ""),
            "phone_orig": str(ws.cell(row=row, column=11).value or ""),
        }
        garages.append(garage)

    return garages, wb, ws


# =============================================================================
# Matching engine
# =============================================================================

def find_best_match(garage, osm_entries, use_address=True, threshold=0.30):
    """Find best matching OSM entry using multiple signals."""
    best_score = 0
    best_entry = None
    best_method = ""
    garage_name = garage["name"]
    garage_addr = garage.get("address", "")

    for entry in osm_entries:
        osm_name = entry["name"]
        osm_street = entry.get("street", "")

        # 1. Exact name match → high confidence
        n1 = normalize_name(garage_name)
        n2 = normalize_name(osm_name)
        if n1 and n2 and n1 == n2:
            return entry, 1.0, "exact_name"

        # 2. Token-based name similarity
        name_score = name_similarity(garage_name, osm_name)

        # 3. Name contains check (one name contains all significant tokens of the other)
        contains_bonus = 0.15 if name_contains_check(garage_name, osm_name) else 0

        # 4. Brand matching - boost if same brand detected
        brand_bonus = 0
        garage_brand = extract_brand(garage_name)
        osm_brand = extract_brand(osm_name)
        if garage_brand and osm_brand and garage_brand == osm_brand:
            brand_bonus = 0.2

        # 5. Address similarity bonus
        addr_bonus = 0
        if use_address and garage_addr and osm_street:
            addr_sim = address_similarity(garage_addr, osm_street)
            if addr_sim > 0.3:
                addr_bonus = addr_sim * 0.3  # Up to 0.3 bonus

        # Combined score
        combined = name_score + contains_bonus + brand_bonus + addr_bonus
        # Cap at 1.0
        combined = min(combined, 1.0)

        if combined > best_score:
            best_score = combined
            best_entry = entry
            if name_score >= 0.8:
                best_method = "name_exact"
            elif brand_bonus > 0:
                best_method = "brand"
            elif addr_bonus > 0:
                best_method = "name+addr"
            else:
                best_method = "name_fuzzy"

    if best_score >= threshold:
        return best_entry, best_score, best_method

    return None, 0.0, ""


def enrich_garages(garages, osm_by_postcode, osm_by_city):
    """Multi-strategy matching to enrich garages with phone numbers."""
    stats = {
        "postcode_exact": 0,
        "postcode_fuzzy": 0,
        "postcode_brand": 0,
        "city_match": 0,
        "already_had": 0,
    }
    total = len(garages)
    used_osm_ids = set()  # Track used OSM entries to avoid duplicates

    for i, garage in enumerate(garages):
        # Skip if already has phone
        if garage["phone_intl"] and garage["phone_intl"] not in ("", "None"):
            stats["already_had"] += 1
            continue

        found = False
        postal_code = garage["postal_code"]
        city = garage["city"]

        # Strategy 1: Match by postal code
        if not found and postal_code and postal_code in osm_by_postcode:
            # Filter out already-used OSM entries
            available = [e for e in osm_by_postcode[postal_code]
                        if e["osm_id"] not in used_osm_ids]
            if available:
                match, score, method = find_best_match(garage, available, threshold=0.30)
                if match:
                    phone_intl = format_phone_international(match["phone"])
                    garage["phone_intl"] = phone_intl
                    garage["phone_orig"] = match["phone"]
                    garage["match_source"] = f"OSM ({method})"
                    garage["match_score"] = score
                    used_osm_ids.add(match["osm_id"])
                    if method == "brand":
                        stats["postcode_brand"] += 1
                    elif score >= 0.7:
                        stats["postcode_exact"] += 1
                    else:
                        stats["postcode_fuzzy"] += 1
                    found = True

        # Strategy 2: Match by city name
        if not found and city:
            city_norm = normalize_city(city)
            if city_norm in osm_by_city:
                available = [e for e in osm_by_city[city_norm]
                            if e["osm_id"] not in used_osm_ids]
                if available:
                    match, score, method = find_best_match(
                        garage, available, use_address=True, threshold=0.35
                    )
                    if match:
                        phone_intl = format_phone_international(match["phone"])
                        garage["phone_intl"] = phone_intl
                        garage["phone_orig"] = match["phone"]
                        garage["match_source"] = f"OSM (city+{method})"
                        garage["match_score"] = score
                        used_osm_ids.add(match["osm_id"])
                        stats["city_match"] += 1

        # Progress
        if (i + 1) % 5000 == 0 or (i + 1) == total:
            total_matched = sum(v for k, v in stats.items() if k != "already_had")
            pct = total_matched / total * 100
            print(f"  [{i+1:,}/{total:,}] "
                  f"Matched: {total_matched:,} ({pct:.1f}%)")

    total_matched = sum(v for k, v in stats.items() if k != "already_had")
    print(f"\n  === Résultats ===")
    print(f"  Total garages: {total:,}")
    print(f"  Déjà avec téléphone: {stats['already_had']:,}")
    print(f"  Nouveaux téléphones trouvés: {total_matched:,}")
    print(f"    Match exact (postcode, score>=0.7): {stats['postcode_exact']:,}")
    print(f"    Match fuzzy (postcode): {stats['postcode_fuzzy']:,}")
    print(f"    Match marque (postcode): {stats['postcode_brand']:,}")
    print(f"    Match par ville: {stats['city_match']:,}")

    return garages


# =============================================================================
# Excel update
# =============================================================================

def update_excel(garages, wb, ws, output_file):
    """Update the Excel file with enriched phone data."""
    updated = 0
    for garage in garages:
        if garage.get("match_source"):
            row = garage["row"]
            ws.cell(row=row, column=10, value=garage["phone_intl"])
            ws.cell(row=row, column=11, value=garage["phone_orig"])
            updated += 1

    wb.save(output_file)
    print(f"\n  {updated:,} lignes mises à jour dans {output_file}")

    # Update summary sheet
    if "Résumé" in wb.sheetnames:
        ws_s = wb["Résumé"]
        phone_count = sum(1 for g in garages
                         if g["phone_intl"] not in ("", "None"))
        for row in range(1, ws_s.max_row + 1):
            cell_val = ws_s.cell(row=row, column=1).value
            if cell_val and "téléphone" in str(cell_val).lower():
                ws_s.cell(row=row, column=2, value=phone_count)
                break
        wb.save(output_file)


# =============================================================================
# Main
# =============================================================================

def main():
    print("=" * 70)
    print("  ENRICHISSEMENT TÉLÉPHONIQUE DES GARAGES v2")
    print("  Source: OpenStreetMap")
    print("=" * 70)

    # Load Excel first to build city→postcode mapping
    print(f"\n1. Chargement des garages ({EXCEL_FILE})...")
    garages, wb, ws = load_garages_from_excel(EXCEL_FILE)
    print(f"  {len(garages):,} garages chargés")

    print(f"\n2. Construction du mapping ville→code postal...")
    city_to_postcode = build_city_postcode_mapping(ws)
    print(f"  {len(city_to_postcode):,} villes mappées")

    # Load OSM data with postcode resolution
    print(f"\n3. Chargement des données OSM ({OSM_FILE})...")
    osm_by_postcode, osm_by_city = load_osm_data(OSM_FILE, city_to_postcode)

    # Enrich
    print(f"\n4. Enrichissement en cours...")
    garages = enrich_garages(garages, osm_by_postcode, osm_by_city)

    # Save
    print(f"\n5. Sauvegarde...")
    update_excel(garages, wb, ws, OUTPUT_FILE)

    print(f"\nTerminé!")


if __name__ == "__main__":
    main()
