#!/usr/bin/env python3
"""Scraper: Annuaire Santé (data.gouv.fr RPPS extract) — Official health professionals directory.

Uses the open-data RPPS extract published on data.gouv.fr by the French government.
Streams the large pipe-delimited file and filters for Paris (75), Marseille (13), Lille (59).
"""
import sys
import time
import re
import json
import requests
from scraper_utils import (
    HEADERS, setup_logging, save_json, format_phone, format_postal_code
)

logger = setup_logging("annuaire_sante")

# The RPPS open data extract on data.gouv.fr
DATASET_URL = (
    "https://static.data.gouv.fr/resources/"
    "annuaire-sante-extractions-des-donnees-en-libre-acces-des-professionnels-"
    "intervenant-dans-le-systeme-de-sante-rpps/"
    "20260331-074104/ps-libreacces-personne-activite.txt"
)

# Map profession codes to NAF-like categories
PROFESSION_CATEGORY_MAP = {
    "1": ("Cabinet médical / Médecin généraliste", "86.21Z"),
    "10": ("Cabinet médical / Médecin généraliste", "86.21Z"),       # Médecin
    "21": ("Pharmacien", "47.73Z"),                                   # Pharmacien (actual mapping)
    "40": ("Cabinet dentaire", "86.23Z"),                             # Chirurgien-dentiste
    "50": ("Sage-femme", "86.90F"),                                   # Sage-femme
    "60": ("Pharmacien", "47.73Z"),                                   # Pharmacien
    "69": ("Pharmacien", "47.73Z"),                                   # Pharmacien adjoint
    "70": ("Cabinet de kinésithérapie / Rééducation", "86.90E"),      # Masseur-kinésithérapeute
    "80": ("Infirmier", "86.90D"),                                    # Infirmier
    "81": ("Infirmier", "86.90D"),                                    # Infirmier
    "91": ("Orthophoniste", "86.90E"),                                # Orthophoniste
    "92": ("Orthoptiste", "86.90E"),                                  # Orthoptiste
    "93": ("Pédicure-podologue", "86.90E"),                           # Pédicure-podologue
    "94": ("Audio-prothésiste", "86.90E"),                            # Audio-prothésiste
    "95": ("Opticien-lunetier", "47.78A"),                            # Opticien
    "96": ("Ergothérapeute", "86.90E"),                               # Ergothérapeute
    "98": ("Psychomotricien", "86.90E"),                              # Psychomotricien
    "26": ("Laboratoire d'analyses médicales", "86.90B"),             # Biologiste médical
    "28": ("Laboratoire d'analyses médicales", "86.90B"),             # Biologiste médical adjoint
    "31": ("Cabinet de médecin spécialiste", "86.22C"),               # Spécialiste chirurgical
    "32": ("Cabinet de médecin spécialiste", "86.22C"),               # Spécialiste médical
    "33": ("Cabinet de médecin spécialiste", "86.22C"),               # Spécialiste psychiatre
    "34": ("Cabinet de médecin spécialiste", "86.22C"),               # Spécialiste santé publique
    "35": ("Cabinet de médecin spécialiste", "86.22C"),               # Spécialiste
}

# Filter by postal code prefix (dept column is often empty in the data)
ZONE_POSTAL_PREFIXES = {
    "paris": ["750"],       # 75001-75020
    "marseille": ["130"],   # 13001-13016 and nearby
    "lille": ["590"],       # 59000, 59800, etc.
}

# Target professions (medical structures we care about)
TARGET_PROF_CODES = {
    "10",   # Médecin
    "21",   # Pharmacien (per actual data mapping)
    "40",   # Chirurgien-Dentiste
    "50",   # Sage-Femme
    "70",   # Masseur-Kinésithérapeute
    "26",   # Biologiste médical
    "80",   # Infirmier
    "91",   # Orthophoniste
    "92",   # Orthoptiste
    "93",   # Pédicure-podologue
    "60",   # Pharmacien (alternate code)
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def build_address(fields):
    """Build address string from address component fields."""
    parts = []
    # Number + street
    num = fields[28].strip()  # Numéro Voie
    rep = fields[29].strip()  # Indice répétition
    type_voie = fields[31].strip()  # Libellé type de voie
    nom_voie = fields[32].strip()  # Libellé Voie

    if num:
        addr = num
        if rep:
            addr += rep
        parts.append(addr)
    if type_voie:
        parts.append(type_voie)
    if nom_voie:
        parts.append(nom_voie)

    return " ".join(parts)


def parse_record(fields, zone_name):
    """Parse a pipe-delimited record into our standard format."""
    prof_code = fields[9].strip()
    prof_label = fields[10].strip()

    cat_info = PROFESSION_CATEGORY_MAP.get(prof_code, (prof_label, ""))
    category, naf_code = cat_info

    # Build name: prefer raison sociale, then "Dr NOM Prénom"
    raison_sociale = fields[24].strip()
    nom = fields[7].strip()
    prenom = fields[8].strip()
    civilite = fields[3].strip() or fields[5].strip()

    if not raison_sociale:
        name_parts = []
        if civilite:
            name_parts.append(civilite)
        if nom:
            name_parts.append(nom)
        if prenom:
            name_parts.append(prenom)
        raison_sociale = " ".join(name_parts)
        if not raison_sociale:
            raison_sociale = prof_label

    telephone = format_phone(fields[40].strip()) if len(fields) > 40 else ""
    adresse = build_address(fields)
    code_postal = format_postal_code(fields[35].strip()) if fields[35].strip() else ""
    ville = fields[37].strip() if len(fields) > 37 else ""

    siret = fields[19].strip() if len(fields) > 19 else ""
    siren = fields[20].strip() if len(fields) > 20 else ""
    finess = fields[21].strip() if len(fields) > 21 else ""

    email = fields[43].strip() if len(fields) > 43 else ""

    record = {
        "raison_sociale": raison_sociale,
        "nom": nom,
        "prenom": prenom,
        "profession": prof_label,
        "categorie": category,
        "code_naf": naf_code,
        "libelle_naf": "",
        "telephone": telephone,
        "adresse": adresse,
        "code_postal": code_postal,
        "ville": ville,
        "siret": siret,
        "siren": siren,
        "finess": finess,
        "site_web": "",
        "email": email,
        "effectif": "",
        "date_creation": "",
        "source": "Annuaire Santé (RPPS)",
        "zone": zone_name,
    }
    return record


def stream_and_filter():
    """Stream the large RPPS file and filter for target departments/cities."""
    logger.info(f"Streaming RPPS data from data.gouv.fr...")
    logger.info(f"URL: {DATASET_URL}")

    results_by_zone = {z: [] for z in ZONE_POSTAL_PREFIXES}

    try:
        r = SESSION.get(DATASET_URL, stream=True, timeout=30)
        r.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to connect to data.gouv.fr: {e}")
        return results_by_zone

    logger.info(f"Connected. Streaming and filtering...")
    total_lines = 0
    matched = 0
    skipped_no_activity = 0
    header = None
    buffer = ""

    try:
        for chunk in r.iter_content(chunk_size=1024 * 256, decode_unicode=False):
            if not chunk:
                continue
            # Decode with latin-1 (the file uses Windows-1252/latin encoding based on the garbled chars)
            try:
                text = chunk.decode('utf-8', errors='replace')
            except:
                text = chunk.decode('latin-1', errors='replace')

            buffer += text
            lines = buffer.split('\n')
            # Keep last partial line in buffer
            buffer = lines[-1]
            lines = lines[:-1]

            for line in lines:
                total_lines += 1

                if total_lines == 1:
                    header = line.split('|')
                    logger.info(f"Header has {len(header)} columns")
                    continue

                if not line.strip():
                    continue

                fields = line.split('|')
                if len(fields) < 45:
                    continue

                # Filter by profession code
                prof_code = fields[9].strip()
                if prof_code not in TARGET_PROF_CODES:
                    continue

                # Filter by postal code prefix to determine zone
                cp = fields[35].strip()
                if not cp:
                    continue

                zone_name = None
                for zn, prefixes in ZONE_POSTAL_PREFIXES.items():
                    for prefix in prefixes:
                        if cp.startswith(prefix):
                            zone_name = zn
                            break
                    if zone_name:
                        break

                if not zone_name:
                    continue

                record = parse_record(fields, zone_name)
                results_by_zone[zone_name].append(record)
                matched += 1

                if matched % 5000 == 0:
                    logger.info(f"  Matched {matched} records so far (scanned {total_lines} lines)...")

    except Exception as e:
        logger.error(f"Error during streaming: {e}")

    logger.info(f"Streaming complete. Scanned {total_lines} lines, matched {matched} records.")
    return results_by_zone


def deduplicate(records):
    """Remove duplicate records based on name + postal code + profession."""
    seen = set()
    unique = []
    for r in records:
        key = (
            r.get("nom", "").upper(),
            r.get("prenom", "").upper(),
            r.get("code_postal", ""),
            r.get("profession", ""),
        )
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def main():
    zone = sys.argv[1] if len(sys.argv) > 1 else "all"

    if zone == "all":
        zones = ["paris", "marseille", "lille"]
    else:
        zones = [zone]

    # Stream and filter all data in one pass
    results_by_zone = stream_and_filter()

    all_results = []
    for z in zones:
        zone_results = results_by_zone.get(z, [])
        # Deduplicate
        zone_results = deduplicate(zone_results)
        logger.info(f"Annuaire Santé {z.upper()}: {len(zone_results)} unique records")
        all_results.extend(zone_results)

    logger.info(f"Total: {len(all_results)} records across {len(zones)} zones")

    filename = f"annuaire_sante_{zone}.json"
    save_json(all_results, filename)
    logger.info(f"Saved to data/{filename}")

    # Print summary
    print(f"\n=== ANNUAIRE SANTE RESULTS ===")
    for z in zones:
        zone_results = [r for r in all_results if r.get("zone") == z]
        print(f"  {z.upper()}: {len(zone_results)} records")
        # Count by profession
        profs = {}
        for r in zone_results:
            p = r.get("profession", "Unknown")
            profs[p] = profs.get(p, 0) + 1
        for p, c in sorted(profs.items(), key=lambda x: -x[1])[:8]:
            print(f"    {p}: {c}")
    print(f"  TOTAL: {len(all_results)} records")
    print(f"  Saved to: data/{filename}")

    return all_results


if __name__ == "__main__":
    main()
