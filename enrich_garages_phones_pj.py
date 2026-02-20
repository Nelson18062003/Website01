#!/usr/bin/env python3
"""
Enrich garages Excel with phone numbers from Pages Jaunes scraped data.

Strategy:
1. Load Pages Jaunes garage data (from scrape_pagesjaunes_garages.py output)
2. Load existing garages_auto_zones_france.xlsx
3. Match by:
   a. Exact name + city (highest confidence)
   b. Name similarity >= 0.75 + same postal code
   c. Name similarity >= 0.70 + same city
4. Update Excel with phone, email, website

Only accepts matches with high confidence to avoid false positives.
"""

import json
import re
import os
import openpyxl

# =============================================================================
# Configuration
# =============================================================================

EXCEL_FILE = "garages_auto_zones_france.xlsx"
PJ_FILE = "pagesjaunes_garages_all.json"
OUTPUT_FILE = "garages_auto_zones_france.xlsx"

# Match thresholds
THRESHOLD_POSTCODE = 0.70   # Minimum Jaccard similarity when same postal code
THRESHOLD_CITY = 0.75       # Minimum Jaccard similarity when same city (looser geo)

# Stop words to remove before comparing names
STOP_WORDS = {
    "garage", "garages", "auto", "automobile", "automobiles", "sarl", "sas",
    "eurl", "sa", "srl", "et", "de", "du", "des", "le", "la", "les", "l",
    "un", "une", "en", "au", "aux", "par", "pour", "sur", "chez", "fils",
    "ets", "etablissements", "monsieur", "madame", "mr", "mme", "m",
    "reparation", "entretien", "mecanique", "carrosserie", "service",
    "services", "centre", "atelier", "station", "point", "agent",
    "concessionnaire", "concession", "vente", "france", "international",
    "group", "groupe", "societe", "ste",
}


# =============================================================================
# Name normalization (reuse pattern from enrich_garages_phones.py)
# =============================================================================

def normalize_name(name):
    """Normalize a business name for matching."""
    if not name:
        return ""
    n = str(name).lower().strip()
    n = re.sub(r"\([^)]*\)", "", n)
    n = re.sub(r"[^a-z0-9àâäéèêëïîôùûüÿçœæ]", " ", n)
    n = n.replace("é", "e").replace("è", "e").replace("ê", "e").replace("ë", "e")
    n = n.replace("à", "a").replace("â", "a").replace("ä", "a")
    n = n.replace("ù", "u").replace("û", "u").replace("ü", "u")
    n = n.replace("î", "i").replace("ï", "i")
    n = n.replace("ô", "o").replace("ç", "c")
    n = n.replace("œ", "oe").replace("æ", "ae").replace("ÿ", "y")
    n = re.sub(r"\s+", " ", n).strip()
    return n


def name_tokens(name):
    """Get significant tokens from a normalized name (stops words removed)."""
    normalized = normalize_name(name)
    tokens = set(normalized.split())
    tokens = {t for t in tokens if t not in STOP_WORDS and len(t) > 1}
    return tokens


def jaccard_similarity(name1, name2):
    """Token-based Jaccard similarity between two names."""
    t1 = name_tokens(name1)
    t2 = name_tokens(name2)
    if not t1 or not t2:
        return 0.0
    inter = t1 & t2
    union = t1 | t2
    return len(inter) / len(union) if union else 0.0


def normalize_city(city):
    """Normalize a city name for matching."""
    if not city:
        return ""
    c = str(city).lower().strip()
    c = re.sub(r"[^a-z0-9àâäéèêëïîôùûüÿçœæ]", " ", c)
    c = c.replace("é", "e").replace("è", "e").replace("ê", "e").replace("ë", "e")
    c = c.replace("à", "a").replace("â", "a")
    c = c.replace("ù", "u").replace("û", "u")
    c = c.replace("î", "i").replace("ô", "o").replace("ç", "c")
    c = c.replace("œ", "oe").replace("æ", "ae")
    c = re.sub(r"\bsaint\b", "st", c)
    c = re.sub(r"\bsainte\b", "ste", c)
    c = re.sub(r"\s+", " ", c).strip()
    return c


def format_phone_international(phone):
    """Convert French phone to international +33 format."""
    if not phone:
        return ""
    p = str(phone).strip()
    for sep in [";", "/", ","]:
        if sep in p:
            p = p.split(sep)[0].strip()

    digits = re.sub(r"[^\d+]", "", p)
    if digits.startswith("+33"):
        digits = "0" + digits[3:]
    elif digits.startswith("0033"):
        digits = "0" + digits[4:]
    elif digits.startswith("33") and len(digits) == 11:
        digits = "0" + digits[2:]

    digits = re.sub(r"[^\d]", "", digits)

    if digits.startswith("0") and len(digits) == 10:
        return (
            f"+33 {digits[1]} {digits[2:4]} {digits[4:6]} "
            f"{digits[6:8]} {digits[8:10]}"
        )
    return p


# =============================================================================
# Load data
# =============================================================================

def load_pj_data(filepath):
    """
    Load Pages Jaunes data and index by postal code and city.
    Returns: (by_postcode dict, by_city dict)
    """
    print(f"Chargement {filepath}...")
    with open(filepath, "r", encoding="utf-8") as f:
        entries = json.load(f)

    by_postcode = {}   # postcode → list of PJ entries
    by_city = {}       # normalized_city → list of PJ entries

    for entry in entries:
        pc = str(entry.get("postal_code", "")).strip()
        city = str(entry.get("city", "")).strip()

        if pc:
            by_postcode.setdefault(pc, []).append(entry)
        if city:
            city_norm = normalize_city(city)
            by_city.setdefault(city_norm, []).append(entry)

    total_with_phone = sum(1 for e in entries if e.get("phone"))
    print(f"  {len(entries):,} entrées PJ chargées")
    print(f"  Avec téléphone: {total_with_phone:,}")
    print(f"  Codes postaux uniques: {len(by_postcode):,}")
    print(f"  Villes uniques: {len(by_city):,}")

    return entries, by_postcode, by_city


def load_excel_garages(filepath):
    """Load garage data from the Excel file."""
    print(f"\nChargement {filepath}...")
    wb = openpyxl.load_workbook(filepath)
    ws = wb.active

    garages = []
    for row in range(2, ws.max_row + 1):
        garages.append({
            "row": row,
            "name": str(ws.cell(row=row, column=2).value or ""),
            "address": str(ws.cell(row=row, column=3).value or ""),
            "postal_code": str(ws.cell(row=row, column=4).value or ""),
            "city": str(ws.cell(row=row, column=5).value or ""),
            "phone_intl": str(ws.cell(row=row, column=10).value or ""),
            "phone_orig": str(ws.cell(row=row, column=11).value or ""),
            "email": str(ws.cell(row=row, column=12).value or ""),
        })

    print(f"  {len(garages):,} garages chargés")
    already = sum(1 for g in garages if g["phone_intl"] not in ("", "None"))
    print(f"  Déjà avec téléphone: {already:,}")
    return garages, wb, ws


# =============================================================================
# Matching engine
# =============================================================================

def find_best_pj_match(garage, pj_candidates, threshold):
    """
    Find the best Pages Jaunes match for a garage among candidates.

    Returns: (best_entry, score, method) or (None, 0, "")
    """
    garage_name = garage["name"]
    norm_garage = normalize_name(garage_name)

    best_score = 0.0
    best_entry = None
    best_method = ""

    for entry in pj_candidates:
        pj_name = entry.get("name", "")
        norm_pj = normalize_name(pj_name)

        # 1. Exact normalized name match
        if norm_garage and norm_pj and norm_garage == norm_pj:
            return entry, 1.0, "exact_name"

        # 2. Jaccard token similarity
        score = jaccard_similarity(garage_name, pj_name)

        if score > best_score:
            best_score = score
            best_entry = entry
            best_method = "name_jaccard"

    if best_score >= threshold and best_entry:
        return best_entry, best_score, best_method

    return None, 0.0, ""


def enrich_garages(garages, by_postcode, by_city):
    """
    Match each garage to a Pages Jaunes entry and collect phone/email/website.
    """
    stats = {
        "already_had": 0,
        "matched_postcode": 0,
        "matched_city": 0,
        "no_match": 0,
    }

    # Track used PJ entries to avoid assigning same phone to multiple garages
    used_pj_names_postcode = set()  # (name_norm, postcode)

    total = len(garages)

    for i, garage in enumerate(garages):
        # Skip if already has phone
        if garage["phone_intl"] and garage["phone_intl"] not in ("", "None"):
            stats["already_had"] += 1
            continue

        postal_code = garage["postal_code"]
        city = garage["city"]
        found = False

        # --- Strategy 1: Match by postal code ---
        if not found and postal_code in by_postcode:
            candidates = by_postcode[postal_code]
            # Only consider PJ entries that have a phone number
            candidates_with_phone = [
                c for c in candidates
                if c.get("phone")
                and (normalize_name(c["name"]), postal_code) not in used_pj_names_postcode
            ]
            if candidates_with_phone:
                match, score, method = find_best_pj_match(
                    garage, candidates_with_phone, THRESHOLD_POSTCODE
                )
                if match:
                    _apply_match(garage, match, f"PJ (postcode+{method})", score)
                    used_pj_names_postcode.add(
                        (normalize_name(match["name"]), postal_code)
                    )
                    stats["matched_postcode"] += 1
                    found = True

        # --- Strategy 2: Match by city name ---
        if not found and city:
            city_norm = normalize_city(city)
            if city_norm in by_city:
                candidates = by_city[city_norm]
                candidates_with_phone = [
                    c for c in candidates
                    if c.get("phone")
                ]
                if candidates_with_phone:
                    match, score, method = find_best_pj_match(
                        garage, candidates_with_phone, THRESHOLD_CITY
                    )
                    if match:
                        _apply_match(garage, match, f"PJ (city+{method})", score)
                        stats["matched_city"] += 1
                        found = True

        if not found and garage["phone_intl"] in ("", "None"):
            stats["no_match"] += 1

        # Progress
        if (i + 1) % 5000 == 0 or (i + 1) == total:
            matched = stats["matched_postcode"] + stats["matched_city"]
            pct = matched / max(1, total - stats["already_had"]) * 100
            print(
                f"  [{i+1:,}/{total:,}] "
                f"Nouveaux: {matched:,} ({pct:.1f}%) | "
                f"PC: {stats['matched_postcode']:,} | "
                f"Ville: {stats['matched_city']:,}"
            )

    # Print final stats
    print(f"\n  === Résultats du matching ===")
    print(f"  Total garages:               {total:,}")
    print(f"  Déjà avec téléphone:         {stats['already_had']:,}")
    print(f"  Match par code postal:       {stats['matched_postcode']:,}")
    print(f"  Match par ville:             {stats['matched_city']:,}")
    matchable = total - stats["already_had"]
    new_matches = stats["matched_postcode"] + stats["matched_city"]
    coverage = new_matches / max(1, matchable) * 100
    print(f"  Total nouveaux téléphones:   {new_matches:,} / {matchable:,} ({coverage:.1f}%)")

    return garages


def _apply_match(garage, pj_entry, source, score):
    """Apply matched Pages Jaunes data to a garage record."""
    phone = pj_entry.get("phone", "")
    phone_intl = pj_entry.get("phone_intl", "")
    if phone and not phone_intl:
        phone_intl = format_phone_international(phone)

    garage["phone_orig"] = phone
    garage["phone_intl"] = phone_intl
    garage["match_source"] = source
    garage["match_score"] = round(score, 3)

    # Email and website (only fill if currently empty)
    if not garage.get("email") or garage["email"] in ("", "None"):
        garage["email"] = pj_entry.get("email", "")
    garage["website"] = pj_entry.get("website", "")


# =============================================================================
# Excel update
# =============================================================================

def update_excel(garages, wb, ws, output_file):
    """Write enriched phone/email data back to Excel."""
    updated_phone = 0
    updated_email = 0

    for garage in garages:
        if not garage.get("match_source"):
            continue

        row = garage["row"]
        # Column 10 = Téléphone (International)
        # Column 11 = Téléphone (Original)
        # Column 12 = Email
        ws.cell(row=row, column=10, value=garage.get("phone_intl", ""))
        ws.cell(row=row, column=11, value=garage.get("phone_orig", ""))
        updated_phone += 1

        if garage.get("email"):
            ws.cell(row=row, column=12, value=garage["email"])
            updated_email += 1

    # Update the Résumé sheet counters if present
    if "Résumé" in wb.sheetnames:
        ws_s = wb["Résumé"]
        phone_count = sum(
            1 for g in garages
            if g.get("phone_intl") and g["phone_intl"] not in ("", "None")
        )
        for row in range(1, ws_s.max_row + 1):
            cell_val = ws_s.cell(row=row, column=1).value
            if cell_val and "téléphone" in str(cell_val).lower():
                ws_s.cell(row=row, column=2, value=phone_count)
                break

    wb.save(output_file)
    print(f"\n  Lignes téléphone mises à jour: {updated_phone:,}")
    print(f"  Lignes email mises à jour:     {updated_email:,}")
    print(f"  Fichier sauvegardé:            {output_file}")


# =============================================================================
# Main
# =============================================================================

def main():
    print("=" * 70)
    print("  ENRICHISSEMENT TÉLÉPHONIQUE via Pages Jaunes")
    print("=" * 70)

    # Check input files
    if not os.path.exists(PJ_FILE):
        print(f"\n[ERREUR] Fichier Pages Jaunes introuvable: {PJ_FILE}")
        print("Veuillez d'abord lancer: python scrape_pagesjaunes_garages.py")
        return

    if not os.path.exists(EXCEL_FILE):
        print(f"\n[ERREUR] Fichier Excel introuvable: {EXCEL_FILE}")
        return

    # Load Pages Jaunes data
    pj_entries, by_postcode, by_city = load_pj_data(PJ_FILE)

    # Load garage Excel
    garages, wb, ws = load_excel_garages(EXCEL_FILE)

    # Enrich
    print(f"\nMatching en cours ({len(garages):,} garages)...")
    garages = enrich_garages(garages, by_postcode, by_city)

    # Save
    print(f"\nSauvegarde dans {OUTPUT_FILE}...")
    update_excel(garages, wb, ws, OUTPUT_FILE)

    # Final summary
    print("\n" + "=" * 70)
    print("  RÉSUMÉ FINAL")
    print("=" * 70)
    total_with_phone = sum(
        1 for g in garages
        if g.get("phone_intl") and g["phone_intl"] not in ("", "None")
    )
    total_with_email = sum(
        1 for g in garages
        if g.get("email") and g["email"] not in ("", "None")
    )
    print(f"  Total garages:       {len(garages):,}")
    print(f"  Avec téléphone:      {total_with_phone:,} "
          f"({total_with_phone / len(garages) * 100:.1f}%)")
    print(f"  Avec email:          {total_with_email:,}")
    print(f"\nTerminé!")


if __name__ == "__main__":
    main()
