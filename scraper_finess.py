#!/usr/bin/env python3
"""Scraper: FINESS (Fichier National des Établissements Sanitaires et Sociaux)"""
import csv
import io
import requests
from scraper_utils import (
    ZONES, setup_logging, save_json, format_phone, format_postal_code, safe_request
)

logger = setup_logging("finess")

# FINESS CSV URLs from data.gouv.fr
FINESS_GEOLOC_URL = "https://static.data.gouv.fr/resources/finess-extraction-du-fichier-des-etablissements/20260312-094547/etalab-cs1100507-stock-20260311-0343.csv"
FINESS_STANDARD_URL = "https://static.data.gouv.fr/resources/finess-extraction-du-fichier-des-etablissements/20260312-094813/etalab-cs1100502-stock-20260311-0344.csv"

# Relevant FINESS category codes for health structures
RELEVANT_CATEGORIES = {
    "101", "106", "109", "114", "122", "128", "129", "131", "141", "146",
    "156", "195", "197", "198", "202", "207", "209", "213", "214", "219",
    "221", "223", "224", "228", "230", "231", "236", "237", "238", "241",
    "246", "249", "252", "253", "255", "262", "265", "286", "289", "292",
    "295", "344", "354", "355", "362", "365", "370", "377", "378", "379",
    "381", "382", "390", "395", "396", "402", "411", "412", "413", "414",
    "415", "418", "422", "427", "430", "432", "433", "437", "440", "441",
    "442", "443", "444", "445", "446", "448", "449", "453", "460", "462",
    "464", "500", "501", "502", "603", "604", "606", "607", "608", "609",
    "610", "611", "614", "620", "623", "624", "627", "628", "629", "630",
    "631", "632", "633", "634", "636", "637", "638", "639", "640", "641",
    "700", "701", "710", "720", "730", "731",
}

# Category code to human-readable category mapping
FINESS_CAT_MAP = {
    # Hospitals
    "101": "Hôpital", "106": "Hôpital", "109": "Hôpital",
    "114": "Hôpital", "122": "Hôpital", "128": "Hôpital",
    "129": "Hôpital", "131": "Hôpital", "141": "Hôpital",
    "146": "Clinique privée", "156": "Clinique privée",
    "195": "Clinique privée", "197": "Clinique privée",
    "198": "Clinique privée",
    # Labs
    "202": "Laboratoire d'analyses médicales",
    "207": "Laboratoire d'analyses médicales",
    "209": "Laboratoire d'analyses médicales",
    # Pharmacies
    "213": "Pharmacie", "214": "Pharmacie",
    # Health centers
    "219": "Centre de santé", "221": "Centre de santé",
    "223": "Centre de santé", "224": "Centre de santé",
    "228": "Centre de santé", "230": "Centre de santé",
    "231": "Centre de santé",
    # Radiology / Imaging
    "236": "Centre de radiologie / Imagerie médicale",
    "237": "Centre de radiologie / Imagerie médicale",
    "238": "Centre de radiologie / Imagerie médicale",
    # Dialysis
    "241": "Centre de dialyse", "246": "Centre de dialyse",
    "249": "Centre de dialyse", "252": "Centre de dialyse",
    "253": "Centre de dialyse", "255": "Centre de dialyse",
    # Other health
    "262": "Centre de santé", "265": "Maison de santé pluridisciplinaire",
    "286": "Autre structure de santé", "289": "Autre structure de santé",
    "292": "Centre de vaccination",
    "295": "Centre de médecine du travail",
    # Medico-social
    "344": "Autre structure de santé", "354": "Autre structure de santé",
    "355": "Autre structure de santé", "362": "Autre structure de santé",
    "365": "Autre structure de santé", "370": "Autre structure de santé",
    "377": "Autre structure de santé", "378": "Autre structure de santé",
    "379": "Autre structure de santé",
    # Default catch-all in processing below
}

TARGET_DEPARTMENTS = {"75", "13", "59"}


def download_finess_csv(url):
    """Download and parse FINESS CSV."""
    logger.info(f"Downloading FINESS CSV from {url[:80]}...")
    try:
        r = requests.get(url, timeout=120, stream=True)
        if r.status_code != 200:
            logger.error(f"FINESS download failed: HTTP {r.status_code}")
            return []

        content = r.content.decode('utf-8', errors='replace')
        logger.info(f"Downloaded {len(content)} bytes")

        # The FINESS CSV has no real header row; line 0 is metadata.
        # Each data row has 32 semicolon-separated fields:
        #  0: type (structureet/geolocalisation)
        #  1: nofinesset  2: nofinessej  3: rs (short name)  4: rslongue
        #  5: complrs  6: compldistrib  7: numvoie  8: typvoie  9: voie
        # 10: compvoie  11: lieuditbp  12: commune_code  13: departement
        # 14: libdepartement  15: ligneacheminement (postal+city)
        # 16: telephone  17: telecopie  18: categetab  19: libcategetab
        # 20: categagretab  21: libcategagretab  22: siret  23: codeape
        # 24: codemft  25: libmft  26: codesph  27: libsph
        lines = content.split('\n')
        rows = []
        for line in lines[1:]:  # skip metadata header
            if not line.strip():
                continue
            fields = line.split(';')
            if len(fields) < 20:
                continue
            rows.append(fields)

        logger.info(f"Parsed {len(rows)} rows from FINESS CSV")
        return rows
    except Exception as e:
        logger.error(f"Error downloading FINESS: {e}")
        return []


def process_finess_rows(rows):
    """Process FINESS rows and filter for our target zones."""
    results = []

    for fields in rows:
        dept = fields[13].strip() if len(fields) > 13 else ""

        if dept not in TARGET_DEPARTMENTS:
            continue

        # Parse postal code and city from ligneacheminement (field 15)
        achemin = fields[15].strip() if len(fields) > 15 else ""
        # Format is typically "75007 PARIS" or "13001 MARSEILLE"
        cp = ""
        ville = ""
        if achemin:
            parts = achemin.split(" ", 1)
            cp = parts[0] if parts else ""
            ville = parts[1] if len(parts) > 1 else ""

        # Get category code
        cat_code = fields[18].strip() if len(fields) > 18 else ""

        # Build address from numvoie (7), typvoie (8), voie (9), compvoie (10), lieuditbp (11)
        addr_parts = []
        for idx in [7, 8, 9, 10, 11]:
            if len(fields) > idx and fields[idx].strip():
                addr_parts.append(fields[idx].strip())

        # Raison sociale: prefer rslongue (4), fallback to rs (3)
        rs = (fields[4].strip() if len(fields) > 4 and fields[4].strip() else
              fields[3].strip() if len(fields) > 3 else "")

        telephone = fields[16].strip() if len(fields) > 16 else ""
        finess_num = fields[1].strip() if len(fields) > 1 else ""
        siret = fields[22].strip() if len(fields) > 22 else ""

        record = {
            "raison_sociale": rs,
            "categorie": FINESS_CAT_MAP.get(cat_code, "Structure de santé"),
            "code_naf": "",
            "libelle_naf": "",
            "telephone": format_phone(telephone),
            "adresse": " ".join(addr_parts),
            "code_postal": format_postal_code(cp),
            "ville": ville,
            "siret": siret,
            "siren": "",
            "site_web": "",
            "email": "",
            "effectif": "",
            "date_creation": "",
            "finess": finess_num,
            "source": "FINESS",
        }

        if record["raison_sociale"]:
            results.append(record)

    return results


def main():
    # Try geolocated version first, then standard
    rows = download_finess_csv(FINESS_GEOLOC_URL)
    if not rows:
        logger.info("Trying standard FINESS CSV...")
        rows = download_finess_csv(FINESS_STANDARD_URL)

    if not rows:
        logger.error("Could not download any FINESS data")
        save_json([], "finess.json")
        return []

    # Log sample row
    if rows:
        logger.info(f"FINESS sample row (first 5 fields): {rows[0][:5]}")

    results = process_finess_rows(rows)

    # Stats
    by_dept = {}
    for r in results:
        cp = r["code_postal"]
        dept = cp[:2] if cp else "??"
        by_dept[dept] = by_dept.get(dept, 0) + 1

    logger.info(f"FINESS: {len(results)} structures in target zones")
    for dept, count in sorted(by_dept.items()):
        logger.info(f"  Dept {dept}: {count}")

    save_json(results, "finess.json")
    logger.info("Saved to data/finess.json")
    return results


if __name__ == "__main__":
    main()
